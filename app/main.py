# -*- coding: utf-8 -*-
"""应用入口：create_app + 生命周期（数据库初始化/引导管理员/定时任务/静态页）。

进程模型（§2）：Uvicorn 单进程 + 异步 IO；课程扫描、定时备份、心跳超时清理
均以进程内 asyncio 定时器实现，省掉独立任务系统。
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import Settings, load_secret_key
from app.db import Database
from app.engine import StudyEngine
from app.errors import ApiError, err, ok
from app.errors import ERR_PARAM, ERR_SERVER
from app.routers import admin, auth, study
from app.security import LoginLockout, SessionSigner, ensure_admin
from app.services import backup as backup_service
from app.services import scanner

log = logging.getLogger("app")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
SWEEP_INTERVAL_S = 30  # 心跳超时清理周期


async def _run_in_thread(fn, *args):
    return await asyncio.to_thread(fn, *args)


def _task_loop(coro_fn, interval_s: float, name: str):
    """通用周期任务：先立即执行一次，再按间隔循环。"""
    async def loop():
        while True:
            try:
                await coro_fn()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("定时任务 %s 执行异常", name)
            await asyncio.sleep(interval_s)
    return loop()


def create_app(settings: Settings, clock: Optional[Callable] = None,
               start_tasks: bool = True) -> FastAPI:
    """构建 FastAPI 应用。

    :param clock: 可注入时钟（测试确定性计时口径用）；缺省为服务器 UTC 时间。
    :param start_tasks: 是否启动后台定时任务（测试可关闭）。
    """
    settings.ensure_dirs()
    db = Database(settings.db_path)
    engine = StudyEngine(db, settings, clock=clock)
    signer = SessionSigner(load_secret_key(settings))
    lockout = LoginLockout(clock=clock)
    tasks = []

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # ---- 启动：建表 → 封口遗留学习段 → 引导管理员 → 定时任务 ----
        db.create_all()
        stale = engine.close_stale_at_startup()
        if stale:
            log.info("启动清理：封口 %d 条遗留开放学习段(offline)", stale)
        if ensure_admin(db, settings):
            log.info("已创建引导管理员 %s（首登强制改密）", settings.admin_employee_no)
        if start_tasks:
            st = app.state

            async def do_scan():
                await _run_in_thread(scanner.scan_courses, st.db, st.settings)

            async def do_sweep():
                closed = await _run_in_thread(st.engine.sweep)
                if closed:
                    log.info("心跳超时清理：封口 %d 条学习段(timeout)", closed)

            async def backup_loop():
                while True:
                    delay = backup_service.seconds_until_daily(st.settings)
                    await asyncio.sleep(delay)
                    try:
                        await _run_in_thread(backup_service.run_backup_now, st.settings)
                    except Exception:
                        log.exception("每日备份执行异常")

            tasks.append(asyncio.create_task(_task_loop(do_scan, settings.scan_interval_min * 60, "课程扫描")))
            tasks.append(asyncio.create_task(_task_loop(do_sweep, SWEEP_INTERVAL_S, "心跳超时清理")))
            tasks.append(asyncio.create_task(backup_loop()))
            log.info("后台任务已启动：课程扫描(%d 分钟)/超时清理(%ds)/每日备份(%s)",
                     settings.scan_interval_min, SWEEP_INTERVAL_S, settings.backup_daily_at)
        yield
        # ---- 关闭：取消后台任务 ----
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        db.dispose()

    app = FastAPI(title="安全生产在线培训平台", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.db = db
    app.state.engine = engine
    app.state.signer = signer
    app.state.lockout = lockout
    app.state.clock = clock or __import__("app.util", fromlist=["utcnow"]).utcnow

    # ---- 统一包裹结构与错误处理（§5） ----
    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError):
        return JSONResponse(status_code=exc.http_status,
                            content={"code": exc.code, "data": None, "msg": exc.msg})

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=400,
                            content={"code": ERR_PARAM[0], "data": None,
                                     "msg": "参数错误：%s" % (exc.errors()[0].get("msg", "") if exc.errors() else "")})

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        log.exception("未处理异常: %s", exc)
        return JSONResponse(status_code=500,
                            content={"code": ERR_SERVER[0], "data": None, "msg": ERR_SERVER[1]})

    # ---- 健康检查（§10 监控：进程状态+数据库连通） ----
    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "db": db.ping(), "version": __version__}

    # ---- 两张 H5 页面（§2：静态与 API 同进程） ----
    @app.get("/", include_in_schema=False)
    def learner_page():
        return FileResponse(STATIC_DIR / "learner.html", media_type="text/html")

    @app.get("/admin", include_in_schema=False)
    def admin_page():
        return FileResponse(STATIC_DIR / "admin.html", media_type="text/html")

    # ---- API v1（R1：全部挂 /api/v1/ 前缀；管理端再挂 /admin） ----
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(study.router, prefix="/api/v1")
    app.include_router(admin.router, prefix="/api/v1/admin")

    return app
