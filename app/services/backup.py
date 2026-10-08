# -*- coding: utf-8 -*-
"""每日备份（技术设计文档 §10）：SQLite 在线备份 API（VACUUM INTO）+ 保留期清理。"""
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from app.config import Settings

log = logging.getLogger("app.backup")


def run_backup_now(settings: Settings) -> str:
    """导出数据库快照到 data/backups，并按保留天数清理旧备份。"""
    settings.backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = settings.backups_dir / ("app-backup-%s.db" % stamp)
    seq = 1
    while dest.exists():  # 同秒内重复备份时加序号，避免 VACUUM INTO 目标已存在报错
        dest = settings.backups_dir / ("app-backup-%s-%d.db" % (stamp, seq))
        seq += 1
    conn = sqlite3.connect(str(settings.db_path))
    try:
        conn.execute("VACUUM INTO ?", (dest.as_posix(),))
    finally:
        conn.close()
    _prune_old(settings)
    log.info("数据库备份完成: %s", dest.name)
    return str(dest)


def _prune_old(settings: Settings) -> int:
    cutoff = datetime.now() - timedelta(days=settings.backup_retain_days)
    removed = 0
    for f in settings.backups_dir.glob("app-backup-*.db"):
        try:
            if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def seconds_until_daily(settings: Settings) -> float:
    """距下一次 daily_at（本地时间）的秒数。"""
    try:
        hh, mm = (int(x) for x in settings.backup_daily_at.split(":")[:2])
    except ValueError:
        hh, mm = 2, 30
    now = datetime.now()
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()
