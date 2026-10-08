# -*- coding: utf-8 -*-
"""数据模型：v0.1 共 5 张表（技术设计文档 §4）。

设计主线：累计口径（study_records，供查询导出）与明细留痕（study_sessions，
供审计回放）分离——台账改不了，明细对得上，这是学时可信在数据层的落点。
"""
from typing import Optional

from sqlalchemy import (CheckConstraint, ForeignKey, Index, Integer,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.util import iso, utcnow


class Base(DeclarativeBase):
    pass


def _now() -> str:
    return iso(utcnow())


class User(Base):
    """员工名册与账号（§4.2）。软删除：status=0 离职停用，历史学时保留。"""
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin','learner')", name="ck_users_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    department: Mapped[str] = mapped_column(String(128), default="")
    role: Mapped[str] = mapped_column(String(16), default="learner")
    password_hash: Mapped[str] = mapped_column(String(128))
    must_change_pwd: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[int] = mapped_column(Integer, default=1)
    mobile: Mapped[Optional[str]] = mapped_column(String(32), default=None)       # 预留字段（R4）
    external_id: Mapped[Optional[str]] = mapped_column(String(64), default=None)  # 预留字段（R4）
    created_at: Mapped[str] = mapped_column(String(48), default=_now)
    updated_at: Mapped[str] = mapped_column(String(48), default=_now, onupdate=_now)

    def brief(self) -> dict:
        return {
            "employee_no": self.employee_no,
            "name": self.name,
            "department": self.department,
            "role": self.role,
            "must_change_pwd": bool(self.must_change_pwd),
        }


class Course(Base):
    """课程库（§4.2/§7）：扫描 data/courses/ 文件夹自动登记。

    file_name 存相对路径（如 "高处作业/登高作业安全要点.pdf"），保证子目录同名不冲突；
    文件指纹（size/mtime/hash）用于"文件被替换"检测，替换时更新指纹、学习记录保留。
    """
    __tablename__ = "courses"
    __table_args__ = (
        CheckConstraint("file_type IN ('pdf')", name="ck_courses_file_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_name: Mapped[str] = mapped_column(String(255), unique=True, index=True)  # 含扩展名的相对路径
    title: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(128), default="")                # 子目录名=课程分类（§7）
    file_type: Mapped[str] = mapped_column(String(16), default="pdf")
    required_minutes: Mapped[int] = mapped_column(Integer, default=60)            # 达标学时（分钟），配置登记
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    file_mtime: Mapped[str] = mapped_column(String(48), default="")
    file_hash: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[int] = mapped_column(Integer, default=1)                       # 1 上架 / 0 下架
    media_type: Mapped[Optional[str]] = mapped_column(String(16), default=None)   # 预留字段（R4：视频）
    media_path: Mapped[Optional[str]] = mapped_column(String(255), default=None)  # 预留字段（R4：视频）
    created_at: Mapped[str] = mapped_column(String(48), default=_now)


class StudyRecord(Base):
    """学习累计（台账口径）：每人每课一条（§4.2）。"""
    __tablename__ = "study_records"
    __table_args__ = (
        UniqueConstraint("user_id", "course_id", name="uq_record_user_course"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    total_seconds: Mapped[int] = mapped_column(Integer, default=0)
    last_position: Mapped[Optional[str]] = mapped_column(Text, default=None)      # 断点位置 JSON
    challenge_miss: Mapped[int] = mapped_column(Integer, default=0)               # 累计防挂机超时次数
    status: Mapped[str] = mapped_column(String(16), default="in_progress")       # in_progress/completed
    completed_at: Mapped[Optional[str]] = mapped_column(String(48), default=None)
    first_started_at: Mapped[str] = mapped_column(String(48), default=_now)
    last_study_at: Mapped[Optional[str]] = mapped_column(String(48), default=None)


class StudySession(Base):
    """学习明细（审计口径，只增不改 append-only）：每次学习一段一行（§4.2）。

    心跳本身不落库（量大且无审计必要），落库的是"学习段"级汇总明细。
    end_reason 为空表示进行中；closed 后不可修改（数据修正原则见 §4.3）。
    """
    __tablename__ = "study_sessions"
    __table_args__ = (
        CheckConstraint("end_reason IN ('normal','timeout','logout','offline')",
                        name="ck_sessions_end_reason"),
        Index("ix_sessions_user_started", "user_id", "started_at"),
        Index("ix_sessions_record", "record_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer)   # 冗余存储，不依赖 join 即可审计
    course_id: Mapped[int] = mapped_column(Integer)
    record_id: Mapped[int] = mapped_column(Integer, index=True)
    started_at: Mapped[str] = mapped_column(String(48))
    ended_at: Mapped[Optional[str]] = mapped_column(String(48), default=None)
    gained_seconds: Mapped[int] = mapped_column(Integer, default=0)
    heartbeat_count: Mapped[int] = mapped_column(Integer, default=0)
    confirm_ok: Mapped[int] = mapped_column(Integer, default=0)
    confirm_miss: Mapped[int] = mapped_column(Integer, default=0)
    client_ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(256), default="")
    end_reason: Mapped[Optional[str]] = mapped_column(String(16), default=None)


class ExportLog(Base):
    """台账导出留痕（§4.2）：谁导的、导了什么、多少行。"""
    __tablename__ = "export_logs"
    __table_args__ = (
        CheckConstraint("export_type IN ('personal','summary')", name="ck_export_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    operator_id: Mapped[int] = mapped_column(Integer)
    export_type: Mapped[str] = mapped_column(String(16))
    scope: Mapped[str] = mapped_column(String(255), default="")
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(48), default=_now)
