# -*- coding: utf-8 -*-
"""课程库扫描（技术设计文档 §7）：目录即课程库。

- 课程根目录 data/courses/，支持子目录按"项目部/主题"分一层（子目录名=分类，仅一层）；
- 以文件相对路径为唯一键：新文件登记上架；文件被修改（指纹变化）更新指纹并保留学习记录；
  文件消失则下架（不删课程行，历史学时保留）；
- 仅白名单扩展名入库；单文件超限跳过并记录日志。
"""
import hashlib
import logging
from pathlib import Path
from typing import Dict

from app.config import Settings
from app.db import Database
from app.util import iso, utcnow

log = logging.getLogger("app.scanner")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_courses(db: Database, settings: Settings) -> Dict[str, int]:
    root: Path = settings.courses_dir
    root.mkdir(parents=True, exist_ok=True)

    from app.models import Course
    found: Dict[str, Path] = {}
    skipped_ext = skipped_large = 0

    # ---- 收集文件（根目录 + 一层子目录） ----
    entries = sorted(root.iterdir(), key=lambda p: p.name)
    for entry in entries:
        if entry.is_dir():
            for f in sorted(entry.iterdir(), key=lambda p: p.name):
                if not f.is_file():
                    continue
                ext = f.suffix.lstrip(".").lower()
                if ext not in settings.allowed_ext:
                    skipped_ext += 1
                    log.info("跳过非白名单文件: %s", f.name)
                    continue
                found[f.relative_to(root).as_posix()] = f
        elif entry.is_file():
            ext = entry.suffix.lstrip(".").lower()
            if ext not in settings.allowed_ext:
                skipped_ext += 1
                log.info("跳过非白名单文件: %s", entry.name)
                continue
            found[entry.relative_to(root).as_posix()] = entry

    added = updated = removed = unchanged = 0
    now_iso = iso(utcnow())
    max_bytes = settings.max_file_mb * 1024 * 1024

    with db.session() as s:
        existing = {c.file_name: c for c in s.query(Course).all()}

        for rel, fpath in found.items():
            size = fpath.stat().st_size
            if size > max_bytes:
                skipped_large += 1
                log.warning("跳过超大文件(%d MB): %s", size // (1024 * 1024), rel)
                continue
            mtime = fpath.stat().st_mtime
            mtime_str = "%.6f" % mtime
            course = existing.get(rel)
            reg = settings.registry_lookup(rel, fpath.stem)
            if course is None:
                s.add(Course(
                    file_name=rel, title=str(reg.get("title") or fpath.stem),
                    category=rel.rsplit("/", 1)[0] if "/" in rel else "",
                    required_minutes=int(reg.get("required_minutes") or settings.default_required_minutes),
                    file_size=size, file_mtime=mtime_str, file_hash=_sha256(fpath),
                    status=1, created_at=now_iso,
                ))
                added += 1
            else:
                # 快速路径：大小与 mtime 未变 → 认为未变；否则重算指纹
                if course.file_size == size and course.file_mtime == mtime_str:
                    if course.status == 0:
                        course.status = 1  # 重新上架
                        updated += 1
                    else:
                        unchanged += 1
                    continue
                new_hash = _sha256(fpath)
                course.file_size = size
                course.file_mtime = mtime_str
                course.file_hash = new_hash
                if reg:
                    course.title = str(reg.get("title") or course.title)
                    course.required_minutes = int(reg.get("required_minutes") or course.required_minutes)
                if course.status == 0:
                    course.status = 1
                updated += 1

        # ---- 文件消失 → 下架（保留课程行与历史学时） ----
        for rel, course in existing.items():
            if rel not in found and course.status == 1:
                course.status = 0
                removed += 1
                log.info("课程下架(文件消失): %s", rel)

        s.commit()
        total_active = s.query(Course).filter(Course.status == 1).count()

    stats = {"added": added, "updated": updated, "removed": removed, "unchanged": unchanged,
             "skipped_ext": skipped_ext, "skipped_large": skipped_large, "active": total_active}
    log.info("课程扫描完成: %s", stats)
    return stats
