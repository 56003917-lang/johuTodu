# -*- coding: utf-8 -*-
"""run.py —— 启动入口：加载 config.yaml → 配置日志 → Uvicorn 监听内网地址。

用法：python run.py [config.yaml]
"""
import logging
import logging.handlers
import sys
from pathlib import Path

import uvicorn

from app.config import Settings
from app.main import create_app


def setup_logging(settings: Settings) -> None:
    """应用日志按天滚动保留 90 天（§10）。"""
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    file_handler = logging.handlers.TimedRotatingFileHandler(
        str(settings.logs_dir / "app.log"), when="midnight",
        backupCount=90, encoding="utf-8")
    file_handler.setFormatter(fmt)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console)


def main() -> int:
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    settings = Settings.load(cfg_path)
    setup_logging(settings)
    app = create_app(settings)
    log = logging.getLogger("app")
    log.info("安全生产在线培训平台 v0.1 启动: http://%s:%d （数据目录 %s）",
             settings.server_host, settings.server_port, settings.data_path)
    uvicorn.run(app, host=settings.server_host, port=settings.server_port,
                log_config=None, access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
