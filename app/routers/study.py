# -*- coding: utf-8 -*-
"""学员端课程与学习路由（/api/v1/courses、/api/v1/study）——技术设计文档 §5。"""
import json
import logging
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.deps import get_current_user, get_db
from app.errors import err, ok
from app.errors import ERR_NOT_FOUND, ERR_MUST_CHANGE_PWD
from app.models import Course, StudyRecord, User
from app.schemas import (ConfirmIn, HeartbeatIn, StopIn, StudyStartIn)
from app.util import fmt_local

log = logging.getLogger("app.study")
router = APIRouter()

CHUNK = 64 * 1024


@router.get("/courses")
def list_courses(request: Request, user: User = Depends(get_current_user), db=Depends(get_db)):
    """上架课程列表（含个人累计秒数、断点、达标状态与学时口径）。"""
    mpc = request.app.state.settings.study.minutes_per_credit
    courses = db.query(Course).filter(Course.status == 1).order_by(Course.category, Course.title).all()
    records = {r.course_id: r for r in db.query(StudyRecord).filter(StudyRecord.user_id == user.id)}
    items = []
    for c in courses:
        r = records.get(c.id)
        total = r.total_seconds if r else 0
        required = c.required_minutes * 60
        items.append({
            "id": c.id,
            "title": c.title,
            "category": c.category or "通用",
            "file_name": Path(c.file_name).name,
            "file_size": c.file_size,
            "required_minutes": c.required_minutes,
            "required_seconds": required,
            "required_credits": round(c.required_minutes / mpc, 1),  # 达标学时（每 mpc 分钟=1 学时）
            "total_seconds": total,
            "percent": min(100, round(total * 100.0 / required, 1)) if required else 100,
            "completed": bool(r and r.status == "completed"),
            "status_text": ("已完成" if (r and r.status == "completed")
                            else ("学习中" if r else "未开始")),
            "last_study_at": fmt_local(r.last_study_at) if r and r.last_study_at else "",
        })
    return ok(items)


@router.get("/courses/{course_id}/file")
def download_course_file(course_id: int, request: Request,
                         user: User = Depends(get_current_user), db=Depends(get_db)):
    """课程 PDF 流式下载（支持 Range，供手机阅读器分页加载大 PDF）。

    安全：路径由数据库 id 反查，不接受用户输入的路径参数，杜绝路径穿越（§7）。
    """
    course = db.get(Course, course_id)
    if not course or course.status != 1:
        raise err(ERR_NOT_FOUND, "课程不存在或已下架")
    settings = request.app.state.settings
    fpath = Path(settings.courses_dir) / course.file_name
    if not fpath.is_file():
        raise err(ERR_NOT_FOUND, "课程文件缺失")
    size = fpath.stat().st_size
    filename = Path(course.file_name).name

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": "inline; filename*=UTF-8''%s" % quote(filename),
    }

    range_header = request.headers.get("range")
    start, end = 0, size - 1
    status_code = 200
    if range_header and range_header.startswith("bytes="):
        try:
            spec = range_header[6:].split(",")[0].strip()
            s_str, e_str = spec.split("-", 1)
            if s_str:
                start = int(s_str)
                if e_str:
                    end = min(int(e_str), size - 1)
            else:  # bytes=-N（后 N 字节）
                suffix = int(e_str)
                start = max(0, size - suffix)
                end = size - 1
            if start > end or start >= size:
                raise err(ERR_NOT_FOUND, "请求范围不合法")
            status_code = 206
            headers["Content-Range"] = "bytes %d-%d/%d" % (start, end, size)
        except (ValueError, IndexError):
            start, end = 0, size - 1
            status_code = 200

    length = end - start + 1
    headers["Content-Length"] = str(length)

    def iter_file():
        with open(fpath, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(CHUNK, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(iter_file(), status_code=status_code,
                             media_type="application/pdf", headers=headers)


# ======================================================================
# 学习引擎接口
# ======================================================================
@router.post("/study/start")
def study_start(body: StudyStartIn, request: Request,
                user: User = Depends(get_current_user)):
    """开始/恢复学习，返回会话 id 与断点位置。"""
    if user.must_change_pwd:
        raise err(ERR_MUST_CHANGE_PWD)
    st = request.app.state
    client_ip = (request.client.host if request.client else "") or ""
    user_agent = request.headers.get("user-agent", "")
    data = st.engine.start(user, body.course_id, client_ip, user_agent)
    return ok(data)


@router.post("/study/heartbeat")
def study_heartbeat(body: HeartbeatIn, request: Request,
                    user: User = Depends(get_current_user)):
    """心跳上报：幂等且服务端权威（间隔/弹窗/单日上限全部由服务端裁决）。"""
    st = request.app.state
    return ok(st.engine.heartbeat(user, body.session_id, body.last_position, body.visible))


@router.post("/study/confirm")
def study_confirm(body: ConfirmIn, request: Request,
                  user: User = Depends(get_current_user)):
    """防挂机弹窗确认应答。"""
    st = request.app.state
    return ok(st.engine.confirm(user, body.session_id, body.token))


@router.post("/study/stop")
def study_stop(body: StopIn, request: Request,
               user: User = Depends(get_current_user)):
    """主动结束本次学习段（关页/切走触发）。"""
    st = request.app.state
    return ok(st.engine.stop(user, body.session_id, body.last_position, body.reason))
