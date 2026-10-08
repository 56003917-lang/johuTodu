# -*- coding: utf-8 -*-
"""学习引擎（技术设计文档 §6）：计时 / 防挂机 / 断点 / 单日上限。

学时可信的全部落点：
1. 服务端权威计时——完全不信任前端时钟，以"收到心跳的服务端时间差"为唯一依据；
2. 防挂机随机挑战状态机——令牌服务端生成、一次性、与会话绑定；
3. 单日计入上限——防"挂夜"刷学时；
4. 明细只增不改——study_sessions 封口后不再修改，台账永远可解释。

运行时挑战状态保存在进程内存（单进程架构），DB 每次心跳落库会话计数与累计值，
服务重启时未结束的学习段统一以 offline 封口（§10 升级发布说明）。
"""
import json
import logging
import math
import random
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

from sqlalchemy import func

from app.config import Settings
from app.db import Database
from app.errors import ApiError, err
from app.errors import ERR_SESSION_GONE, ERR_NOT_FOUND, ERR_COURSE_FILE, ERR_CHALLENGE
from app.models import Course, StudyRecord, StudySession
from app.util import iso, parse_iso, today_window_utc

log = logging.getLogger("app.engine")


@dataclass
class RuntimeSession:
    """单条学习会话的进程内状态（挑战/暂停等；计数器镜像到 DB）。"""
    session_id: int
    user_id: int
    course_id: int
    record_id: int
    last_heartbeat_at: datetime
    heartbeat_count: int = 0
    gained_seconds: int = 0
    confirm_ok: int = 0
    confirm_miss: int = 0
    pending_token: Optional[str] = None
    pending_issued_at: Optional[datetime] = None
    paused: bool = False
    paused_at: Optional[datetime] = None      # 超时时刻（本间隔内学时只计到此刻）
    next_challenge_at: Optional[datetime] = None


class StudyEngine:
    def __init__(self, db: Database, settings: Settings, clock=None):
        from app.util import utcnow
        self.db = db
        self.s = settings
        self.study = settings.study
        self.clock = clock or utcnow
        self._rt: Dict[int, RuntimeSession] = {}
        self._lock = threading.RLock()
        self._rng = random.Random()

    # ================== 开课 / 断点恢复 ==================
    def start(self, user, course_id: int, client_ip: str = "", user_agent: str = "") -> dict:
        """开始/恢复学习：建累计记录（若无）+ 开学习段 + 返回断点。"""
        now = self.clock()
        with self._lock:
            with self.db.session() as s:
                course = s.get(Course, course_id)
                if not course or course.status != 1:
                    raise err(ERR_NOT_FOUND, "课程不存在或已下架")
                fpath = Path(self.s.courses_dir) / course.file_name
                if not fpath.is_file():
                    raise err(ERR_COURSE_FILE)

                record = (s.query(StudyRecord)
                          .filter(StudyRecord.user_id == user.id, StudyRecord.course_id == course_id)
                          .one_or_none())
                if not record:
                    record = StudyRecord(user_id=user.id, course_id=course_id,
                                         total_seconds=0, status="in_progress",
                                         first_started_at=iso(now))
                    s.add(record)
                    s.flush()

                # 同一课程重复打开（双开标签页）→ 先封口旧学习段，防止双倍计时
                self._close_open_rows(s, user.id, course_id, now, reason="timeout")

                row = StudySession(
                    user_id=user.id, course_id=course_id, record_id=record.id,
                    started_at=iso(now), client_ip=client_ip[:64] or "",
                    user_agent=(user_agent or "")[:256],
                )
                s.add(row)
                s.flush()
                self._rt[row.id] = RuntimeSession(
                    session_id=row.id, user_id=user.id, course_id=course_id,
                    record_id=record.id, last_heartbeat_at=now,
                    next_challenge_at=now + timedelta(seconds=self._rand_challenge_gap()),
                )
                s.commit()
                return {
                    "session_id": row.id,
                    "course_id": course_id,
                    "total_seconds": record.total_seconds,
                    "required_seconds": course.required_minutes * 60,
                    "completed": record.status == "completed",
                    "last_position": self._load_position(record.last_position),
                    "paused": False,
                    "heartbeat_interval_s": self.study.heartbeat_interval_s,
                }

    # ================== 心跳（核心接口） ==================
    def heartbeat(self, user, session_id: int, position: Optional[dict], visible: bool) -> dict:
        with self._lock:
            rs = self._get_rt(session_id, user.id)
            now = self.clock()
            with self.db.session() as s:
                row, record, course = self._load(s, rs)
                was_paused = rs.paused
                # ---- 防挂机状态机先走：超时可能落在本间隔中间 ----
                challenge = self._challenge_state(rs, record, now)
                # ---- 有效时长计算（§6.1 服务端口径，唯一计时依据） ----
                # 超时发生时，本间隔只计到超时时刻；已在暂停期则整段不计
                eff_end = rs.paused_at if (rs.paused and not was_paused and rs.paused_at) else now
                delta = (eff_end - rs.last_heartbeat_at).total_seconds()
                if was_paused or delta <= 0:
                    gained_raw = 0.0            # 暂停期间 / 时钟回拨重放，不计
                elif delta > self.study.max_gap_s:
                    gained_raw = 0.0            # 断线超长间隔，本段不计
                elif not visible:
                    gained_raw = 0.0            # 切屏/后台，不计（前后端双保险）
                else:
                    gained_raw = delta          # 正常：15s 间隔计 15s
                rs.last_heartbeat_at = now
                rs.heartbeat_count += 1

                gained = 0
                if gained_raw > 0:
                    used = self._daily_gained(s, user.id, now)
                    gained = int(min(gained_raw, max(0, self.study.daily_cap_s - used)))
                if gained > 0:
                    record.total_seconds += gained
                record.last_study_at = iso(now)
                if position is not None:
                    record.last_position = json.dumps(position, ensure_ascii=False)
                self._check_complete(record, course, now)

                rs.gained_seconds += gained
                self._flush_row(rs, row)
                s.commit()
                return {
                    "gained_seconds": gained,
                    "total_seconds": record.total_seconds,
                    "required_seconds": course.required_minutes * 60,
                    "completed": record.status == "completed",
                    "paused": rs.paused,
                    "challenge": challenge,
                }

    # ================== 防挂机确认 ==================
    def confirm(self, user, session_id: int, token: str) -> dict:
        """弹窗确认应答：校验令牌（一次性、与会话绑定）。"""
        with self._lock:
            rs = self._get_rt(session_id, user.id)
            now = self.clock()
            with self.db.session() as s:
                row, record, course = self._load(s, rs)
                if not rs.pending_token or token != rs.pending_token:
                    raise err(ERR_CHALLENGE)
                elapsed = (now - rs.pending_issued_at).total_seconds()
                if elapsed < 1.0:
                    # 确认间隔过短视为异常：只记录，不惩罚（§6.2 防作弊细节）
                    log.warning("异常快速应答: user=%s session=%s elapsed=%.3fs",
                                user.employee_no, session_id, elapsed)
                resumed = rs.paused
                if rs.paused:
                    # 超时后的重新确认：计时锚点重置到确认时刻，此后正常累计
                    rs.last_heartbeat_at = now
                    rs.paused_at = None
                rs.paused = False
                rs.pending_token = None
                rs.pending_issued_at = None
                rs.confirm_ok += 1
                rs.next_challenge_at = now + timedelta(seconds=self._rand_challenge_gap())
                self._flush_row(rs, row)
                s.commit()
                return {
                    "resumed": resumed,
                    "paused": False,
                    "confirm_ok": rs.confirm_ok,
                    "total_seconds": record.total_seconds,
                    "required_seconds": course.required_minutes * 60,
                    "completed": record.status == "completed",
                }

    # ================== 主动结束 ==================
    def stop(self, user, session_id: int, position: Optional[dict], reason: str = "normal") -> dict:
        reason = reason if reason in ("normal", "logout") else "normal"
        with self._lock:
            rs = self._get_rt(session_id, user.id)
            now = self.clock()
            with self.db.session() as s:
                row, record, course = self._load(s, rs)
                gained = self._final_gain(rs, now)
                if gained > 0:
                    record.total_seconds += gained
                record.last_study_at = iso(now)
                if position is not None:
                    record.last_position = json.dumps(position, ensure_ascii=False)
                self._check_complete(record, course, now)
                rs.gained_seconds += gained
                self._flush_row(rs, row)
                row.ended_at = iso(now)
                row.end_reason = reason
                s.commit()
                self._rt.pop(session_id, None)
                return {
                    "gained_seconds": gained,
                    "total_seconds": record.total_seconds,
                    "required_seconds": course.required_minutes * 60,
                    "completed": record.status == "completed",
                }

    def stop_all_for_user(self, user_id: int, reason: str = "logout") -> int:
        """登出时封口该用户全部进行中的学习段。"""
        n = 0
        with self._lock:
            sids = [sid for sid, rs in self._rt.items() if rs.user_id == user_id]
            for sid in sids:
                rs = self._rt.get(sid)
                now = self.clock()
                with self.db.session() as s:
                    row, record, course = self._load(s, rs)
                    gained = self._final_gain(rs, now)
                    if gained > 0:
                        record.total_seconds += gained
                    record.last_study_at = iso(now)
                    self._check_complete(record, course, now)
                    rs.gained_seconds += gained
                    self._flush_row(rs, row)
                    row.ended_at = iso(now)
                    row.end_reason = reason
                    s.commit()
                self._rt.pop(sid, None)
                n += 1
            # 内存态丢失但 DB 仍开放的学习段（异常路径兜底）
            self._close_open_rows_db_only(user_id=user_id, reason=reason)
        return n

    # ================== 后台清理 ==================
    def sweep(self) -> int:
        """心跳中断超过 max_gap 的学习段自动封口（end_reason=timeout，§6.1）。"""
        now = self.clock()
        closed = 0
        with self._lock:
            stale = [sid for sid, rs in self._rt.items()
                     if (now - rs.last_heartbeat_at).total_seconds() > self.study.max_gap_s]
            for sid in stale:
                rs = self._rt.get(sid)
                with self.db.session() as s:
                    row, record, course = self._load(s, rs)
                    row.ended_at = iso(rs.last_heartbeat_at + timedelta(seconds=self.study.heartbeat_interval_s))
                    row.end_reason = "timeout"
                    self._flush_row(rs, row)
                    s.commit()
                self._rt.pop(sid, None)
                closed += 1
        return closed

    def close_stale_at_startup(self) -> int:
        """服务重启时封口全部遗留开放学习段（end_reason=offline）。"""
        now = iso(self.clock())
        n = 0
        with self.db.session() as s:
            rows = s.query(StudySession).filter(StudySession.ended_at.is_(None)).all()
            for row in rows:
                row.ended_at = now
                row.end_reason = "offline"
                n += 1
            s.commit()
        return n

    # ================== 内部实现 ==================
    def _get_rt(self, session_id: int, user_id: int) -> RuntimeSession:
        rs = self._rt.get(session_id)
        if not rs or rs.user_id != user_id:
            # 会话不存在或不属于当前用户（防越权，§9）
            raise err(ERR_SESSION_GONE)
        return rs

    def _load(self, s, rs: RuntimeSession):
        row = s.get(StudySession, rs.session_id)
        record = s.get(StudyRecord, rs.record_id)
        course = s.get(Course, rs.course_id)
        if not (row and record and course):
            raise err(ERR_SESSION_GONE)
        return row, record, course

    def _final_gain(self, rs: RuntimeSession, now: datetime) -> int:
        """结束学习段时的最后一段有效时长（同样受 max_gap/暂停约束）。"""
        delta = (now - rs.last_heartbeat_at).total_seconds()
        if delta <= 0 or delta > self.study.max_gap_s or rs.paused:
            return 0
        return int(delta)

    def _challenge_state(self, rs: RuntimeSession, record: StudyRecord, now: datetime) -> Optional[dict]:
        """防挂机随机挑战状态机（§6.2）。

        - 触发：now ≥ next_challenge_at 时签发一次性令牌；
        - 超时：应答时限内未确认 → paused + confirm_miss+1（台账可见），令牌保留供"重新确认恢复"；
        - 待答期间：每次心跳回传同一令牌与剩余时限（前端重绘/兜底展示）。
        """
        if rs.pending_token:
            remain = self.study.challenge_timeout_s - (now - rs.pending_issued_at).total_seconds()
            if remain <= 0 and not rs.paused:
                rs.paused = True
                rs.paused_at = rs.pending_issued_at + timedelta(seconds=self.study.challenge_timeout_s)
                rs.confirm_miss += 1
                record.challenge_miss += 1
                log.info("防挂机超时: session=%s user=%s", rs.session_id, rs.user_id)
            return {"token": rs.pending_token, "timeout_s": max(0, int(math.ceil(remain)))}
        if rs.paused or now >= rs.next_challenge_at:
            rs.pending_token = secrets.token_hex(4)
            rs.pending_issued_at = now
            return {"token": rs.pending_token, "timeout_s": self.study.challenge_timeout_s}
        return None

    def _rand_challenge_gap(self) -> int:
        return self._rng.randint(self.study.challenge_min_s, self.study.challenge_max_s)

    def _daily_gained(self, s, user_id: int, now: datetime) -> int:
        """当日已计入学时（口径：本地自然日内开始的学习段；单进程内存态重启可从 DB 恢复）。"""
        start, end = today_window_utc(now)
        total = (s.query(func.coalesce(func.sum(StudySession.gained_seconds), 0))
                 .filter(StudySession.user_id == user_id,
                         StudySession.started_at >= iso(start),
                         StudySession.started_at < iso(end))
                 .scalar())
        return int(total or 0)

    def _check_complete(self, record: StudyRecord, course: Course, now: datetime) -> None:
        """达标判定在服务端；达标后继续学习仍累计（超额如实记录），状态不再回退（§6.3）。"""
        if record.status != "completed" and record.total_seconds >= course.required_minutes * 60:
            record.status = "completed"
            record.completed_at = iso(now)

    def _flush_row(self, rs: RuntimeSession, row: StudySession) -> None:
        row.gained_seconds = rs.gained_seconds
        row.heartbeat_count = rs.heartbeat_count
        row.confirm_ok = rs.confirm_ok
        row.confirm_miss = rs.confirm_miss

    def _close_open_rows(self, s, user_id: int, course_id: int, now: datetime, reason: str) -> None:
        rows = (s.query(StudySession)
                .filter(StudySession.user_id == user_id,
                        StudySession.course_id == course_id,
                        StudySession.ended_at.is_(None))
                .all())
        for row in rows:
            self._rt.pop(row.id, None)
            row.ended_at = iso(now)
            row.end_reason = reason

    def _close_open_rows_db_only(self, user_id: int, reason: str) -> None:
        with self.db.session() as s:
            rows = (s.query(StudySession)
                    .filter(StudySession.user_id == user_id,
                            StudySession.ended_at.is_(None))
                    .all())
            now = iso(self.clock())
            for row in rows:
                row.ended_at = now
                row.end_reason = reason
            if rows:
                s.commit()

    @staticmethod
    def _load_position(raw: Optional[str]) -> Optional[dict]:
        if not raw:
            return None
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else None
        except (ValueError, TypeError):
            return None

    # ---- 供管理端/导出使用的当日口径 ----
    def daily_report(self, user_id: int, now: datetime = None) -> dict:
        now = now or self.clock()
        start, end = today_window_utc(now)
        with self.db.session() as s:
            total = (s.query(func.coalesce(func.sum(StudySession.gained_seconds), 0))
                     .filter(StudySession.user_id == user_id,
                             StudySession.started_at >= iso(start),
                             StudySession.started_at < iso(end))
                     .scalar())
        return {"daily_seconds": int(total or 0), "daily_cap_s": self.study.daily_cap_s}
