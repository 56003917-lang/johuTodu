# -*- coding: utf-8 -*-
"""配置加载（技术设计文档 §8：学时规则与运行参数唯一定义点）。

所有"法规会变、口径会调"的参数一律进 config.yaml，启动加载、改动重启生效。
缺失键回退到默认值，保证最小配置也能启动。
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


@dataclass
class StudyParams:
    """学时有效性核心参数（§6）。"""
    heartbeat_interval_s: int = 15
    max_gap_s: int = 60
    challenge_min_s: int = 90
    challenge_max_s: int = 180
    challenge_timeout_s: int = 120
    daily_cap_hours: float = 8
    # 学时换算口径：每 N 分钟 = 1 学时（台账/界面显示口径，达标判定仍按秒级）
    minutes_per_credit: int = 30

    @property
    def daily_cap_s(self) -> int:
        return int(self.daily_cap_hours * 3600)

    @property
    def credit_seconds(self) -> int:
        """1 学时对应的秒数（换算基准）。"""
        return int(self.minutes_per_credit * 60)


@dataclass
class Settings:
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    data_dir: str = "data"
    secret_key: str = ""
    study: StudyParams = field(default_factory=StudyParams)
    # 名册（§3.1 / §9）：初始密码=工号，首登强制改密
    initial_password: str = "employee_no"
    force_change_password: bool = True
    # 引导管理员：首次启动自动创建（解决"先有管理员才能导入名册"的鸡生蛋问题）
    admin_employee_no: str = "admin"
    admin_name: str = "系统管理员"
    admin_password: str = "admin@2026"
    # 课程库（§7）
    allowed_ext: tuple = ("pdf",)
    max_file_mb: int = 100
    scan_interval_min: int = 5
    default_required_minutes: int = 60
    course_registry: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # 备份（§10）
    backup_daily_at: str = "02:30"
    backup_retain_days: int = 30

    _base_dir: str = "."

    # ---------- 派生路径 ----------
    @property
    def base_dir(self) -> Path:
        return Path(self._base_dir)

    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir)
        return p if p.is_absolute() else (self.base_dir / p)

    @property
    def db_path(self) -> Path:
        return self.data_path / "app.db"

    @property
    def courses_dir(self) -> Path:
        return self.data_path / "courses"

    @property
    def backups_dir(self) -> Path:
        return self.data_path / "backups"

    @property
    def logs_dir(self) -> Path:
        return self.data_path / "logs"

    @property
    def secret_key_path(self) -> Path:
        return self.data_path / "secret.key"

    def ensure_dirs(self) -> None:
        for p in (self.data_path, self.courses_dir, self.backups_dir, self.logs_dir):
            p.mkdir(parents=True, exist_ok=True)

    # ---------- 加载 ----------
    @classmethod
    def from_dict(cls, d: Dict[str, Any], base_dir: str = ".") -> "Settings":
        study = StudyParams(**{k: v for k, v in (d.get("study") or {}).items()
                               if k in StudyParams.__dataclass_fields__})
        roster = d.get("roster") or {}
        admin = d.get("admin") or {}
        courses = d.get("courses") or {}
        backup = d.get("backup") or {}
        server = d.get("server") or {}
        allowed = courses.get("allowed_ext") or ["pdf"]
        return cls(
            server_host=str(server.get("host", "0.0.0.0")),
            server_port=int(server.get("port", 8000)),
            data_dir=str(d.get("data_dir", "data")),
            secret_key=str(d.get("secret_key", "")),
            study=study,
            initial_password=str(roster.get("initial_password", "employee_no")),
            force_change_password=bool(roster.get("force_change_password", True)),
            admin_employee_no=str(admin.get("employee_no", "admin")),
            admin_name=str(admin.get("name", "系统管理员")),
            admin_password=str(admin.get("password", "admin@2026")),
            allowed_ext=tuple(str(e).lower().lstrip(".") for e in allowed),
            max_file_mb=int(courses.get("max_file_mb", 100)),
            scan_interval_min=int(courses.get("scan_interval_min", 5)),
            default_required_minutes=int(courses.get("default_required_minutes", 60)),
            course_registry=dict(courses.get("registry") or {}),
            backup_daily_at=str(backup.get("daily_at", "02:30")),
            backup_retain_days=int(backup.get("retain_days", 30)),
            _base_dir=str(base_dir),
        )

    @classmethod
    def load(cls, path) -> "Settings":
        """从 config.yaml 加载；文件不存在时使用全默认值。"""
        path = Path(path)
        base_dir = str(path.parent.resolve()) if str(path) != "." else "."
        data: Dict[str, Any] = {}
        if path.is_file():
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        return cls.from_dict(data, base_dir=base_dir)

    def registry_lookup(self, rel_name: str, stem: str) -> Dict[str, Any]:
        """按"相对路径名 → 文件名"两级查找课程登记项。"""
        for key in (rel_name, stem):
            if key in self.course_registry:
                v = self.course_registry[key] or {}
                return dict(v)
        return {}

    def initial_password_for(self, employee_no: str) -> str:
        """初始密码策略：employee_no=工号，否则为固定字符串（§3.1）。"""
        return employee_no if self.initial_password == "employee_no" else self.initial_password


def load_secret_key(settings: Settings) -> str:
    """会话签名密钥：优先配置；否则自动生成并持久化到 data/secret.key。"""
    if settings.secret_key:
        return settings.secret_key
    path = settings.secret_key_path
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    import secrets as _secrets
    key = _secrets.token_hex(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key, encoding="utf-8")
    return key


def env_settings() -> Settings:
    """run.py 入口：默认读取工作目录下 config.yaml。"""
    cfg = os.environ.get("TP_CONFIG", "config.yaml")
    return Settings.load(cfg)
