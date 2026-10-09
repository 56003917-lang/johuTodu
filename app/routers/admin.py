# -*- coding: utf-8 -*-
"""管理端路由（/api/v1/admin/*）——技术设计文档 §5，统一 role=admin 校验。"""
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import Response

from app.deps import get_db, require_admin
from app.errors import err, ok
from app.errors import ERR_PARAM
from app.models import Course, ExportLog, User
from app.services import exporter, roster, scanner

log = logging.getLogger("app.admin")
router = APIRouter()

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _file_response(filename: str, content: bytes, mime: str) -> Response:
    return Response(
        content=content, media_type=mime,
        headers={"Content-Disposition": "attachment; filename*=UTF-8''%s" % quote(filename)},
    )


# ======================================================================
# 名册
# ======================================================================
@router.post("/roster/import")
def roster_import(file: UploadFile = File(...), request: Request = None,
                  admin: User = Depends(require_admin)):
    """Excel 名册导入（新增+更新，返回导入统计）。"""
    st = request.app.state
    if (file.filename or "").lower().rsplit(".", 1)[-1] not in ("xlsx", "xlsm"):
        raise err(ERR_PARAM, "请上传 .xlsx 格式的名册文件")
    data = file.file.read()
    if not data:
        raise err(ERR_PARAM, "文件为空")
    try:
        stats = roster.import_roster(st.db, st.settings, data)
    except ValueError as e:
        raise err(ERR_PARAM, str(e))
    return ok(stats, msg="导入完成：新增 %d，更新 %d，跳过 %d" %
              (stats["created"], stats["updated"], stats["skipped"]))


@router.get("/roster/template")
def roster_template(admin: User = Depends(require_admin)):
    """下载名册 Excel 模板。"""
    content = roster.generate_template()
    return _file_response("员工名册模板.xlsx", content, XLSX_MIME)


# ======================================================================
# 课程库
# ======================================================================
@router.get("/courses")
def admin_courses(request: Request, admin: User = Depends(require_admin), db=Depends(get_db)):
    """课程库总览（含文件指纹、上下架状态、达标学时）。"""
    mpc = request.app.state.settings.study.minutes_per_credit
    courses = db.query(Course).order_by(Course.status.desc(), Course.category, Course.title).all()
    return ok([{
        "id": c.id, "file_name": c.file_name, "title": c.title, "category": c.category or "通用",
        "required_minutes": c.required_minutes,
        "required_credits": round(c.required_minutes / mpc, 1),
        "file_type": c.file_type,
        "file_size_mb": round(c.file_size / (1024.0 * 1024.0), 2),
        "file_hash": c.file_hash[:12], "status": c.status,
        "status_text": "上架" if c.status == 1 else "下架",
        "created_at": c.created_at,
    } for c in courses])


@router.post("/courses/scan")
def courses_scan(request: Request, admin: User = Depends(require_admin)):
    """手动触发课程文件夹扫描（平时自动，每 5 分钟）。"""
    st = request.app.state
    stats = scanner.scan_courses(st.db, st.settings)
    return ok(stats, msg="扫描完成：新上架 %d，更新 %d，下架 %d" %
              (stats["added"], stats["updated"], stats["removed"]))


# ======================================================================
# 学时台账导出
# ======================================================================
@router.get("/export/personal")
def export_personal(request: Request, department: str = "", date_from: str = "",
                    date_to: str = "", format: str = "xlsx",
                    admin: User = Depends(require_admin)):
    """导出个人学时明细（xlsx 三表 / csv 明细），可按部门/时间段过滤。"""
    st = request.app.state
    fmt = "csv" if format == "csv" else "xlsx"
    try:
        filename, content, _rows = exporter.export_personal(
            st.db, st.settings, admin.id, department or None, date_from or None,
            date_to or None, fmt)
    except ValueError as e:
        raise err(ERR_PARAM, str(e))
    mime = "text/csv" if fmt == "csv" else XLSX_MIME
    return _file_response(filename, content, mime)


@router.get("/export/summary")
def export_summary(request: Request, department: str = "", date_from: str = "",
                   date_to: str = "", format: str = "xlsx",
                   admin: User = Depends(require_admin)):
    """导出部门/班组学时汇总 xlsx。"""
    st = request.app.state
    fmt = "csv" if format == "csv" else "xlsx"
    try:
        filename, content, _rows = exporter.export_summary(
            st.db, st.settings, admin.id, department or None, date_from or None,
            date_to or None, fmt)
    except ValueError as e:
        raise err(ERR_PARAM, str(e))
    mime = "text/csv" if fmt == "csv" else XLSX_MIME
    return _file_response(filename, content, mime)


@router.get("/overview")
def admin_overview(request: Request, department: str = "",
                   admin: User = Depends(require_admin)):
    """学时总览表数据（管理端首页表格）。"""
    st = request.app.state
    return ok(exporter.overview(st.db, st.settings, department))


@router.get("/export/logs")
def export_logs(admin: User = Depends(require_admin), db=Depends(get_db)):
    """导出留痕记录（谁导的、导了什么）。"""
    logs = (db.query(ExportLog, User)
            .join(User, ExportLog.operator_id == User.id, isouter=True)
            .order_by(ExportLog.id.desc()).limit(50).all())
    from app.util import fmt_local
    return ok([{
        "id": e.id, "operator": (u.name if u else "—"),
        "export_type": ("个人明细" if e.export_type == "personal" else "部门汇总"),
        "scope": e.scope, "row_count": e.row_count, "created_at": fmt_local(e.created_at),
    } for e, u in logs])
