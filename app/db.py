# -*- coding: utf-8 -*-
"""数据层：SQLite（WAL 模式）引擎与会话工厂（技术设计文档 §2/§4）。

SQLite 为单写者模型，WAL 模式实测可承受每秒百次级写入，
对 8 QPS 心跳峰值有十倍以上余量（§1 容量测算结论）。
"""
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def _set_pragma(dbapi_connection, connection_record):
    """每个连接生效的 PRAGMA：WAL / 外键 / 写锁等待。"""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


class Database:
    """封装 engine + sessionmaker；expire_on_commit=False 便于跨会话读值。"""

    def __init__(self, db_path):
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(
            "sqlite:///%s" % db_path.as_posix(),
            connect_args={"check_same_thread": False},
        )
        event.listen(self.engine, "connect", _set_pragma)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)

    def create_all(self):
        from app import models  # noqa: F401  确保模型已注册
        from app.models import Base
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Session:
        s = self.Session()
        try:
            yield s
        finally:
            s.close()

    def ping(self) -> bool:
        try:
            with self.session() as s:
                s.execute(__import__("sqlalchemy").text("SELECT 1"))
            return True
        except Exception:
            return False

    def dispose(self):
        self.engine.dispose()
