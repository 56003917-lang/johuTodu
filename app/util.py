# -*- coding: utf-8 -*-
"""通用工具：时间统一口径（技术设计文档 §4.3）。

约定：数据库内所有时间一律存 UTC ISO8601 字符串，展示层转本地时间；
"单日/按日"口径均以服务器本地自然日为准（学时按自然日统计是检查口径）。
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple


def utcnow() -> datetime:
    """带时区的当前 UTC 时间。"""
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    """datetime → 统一格式的 UTC ISO8601 字符串（全库统一，保证字符串比较有序）。"""
    return dt.astimezone(timezone.utc).isoformat()


def parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def today_window_utc(now: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    """服务器本地"今天"对应的 UTC 时间窗 [start, end)。

    单日计入学时上限（§6.1）与按日过滤均以此窗口为准。
    """
    now = now or utcnow()
    local_midnight = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    start = local_midnight.astimezone(timezone.utc)
    return start, start + timedelta(days=1)


def date_range_utc(date_from: Optional[str], date_to: Optional[str]) -> Tuple[Optional[datetime], Optional[datetime]]:
    """导出过滤参数 YYYY-MM-DD（按本地日解释）→ UTC 边界 [from 00:00, to+1 00:00)。"""
    start = end = None
    try:
        if date_from:
            d = datetime.strptime(date_from.strip(), "%Y-%m-%d")
            start = d.astimezone().astimezone(timezone.utc)
        if date_to:
            d = datetime.strptime(date_to.strip(), "%Y-%m-%d")
            end = (d + timedelta(days=1)).astimezone().astimezone(timezone.utc)
    except ValueError:
        return None, None
    return start, end


def fmt_seconds(seconds: int) -> str:
    """秒 → "H:MM:SS"（前端计时展示）。"""
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return "%d:%02d:%02d" % (h, m, s)


def fmt_local(iso_str: Optional[str], fmt: str = "%Y-%m-%d %H:%M") -> str:
    """UTC ISO 字符串 → 本地时间字符串（展示层用）。"""
    dt = parse_iso(iso_str)
    if not dt:
        return ""
    return dt.astimezone().strftime(fmt)
