# -*- coding: utf-8 -*-
"""认证模块（技术设计文档 §9 / 预留 R3：login/logout/校验三函数收敛于此）。

- 密码：bcrypt 哈希存储（行业标配，抗暴力破解）。
  说明：文档提及 passlib+bcrypt 组合；passlib 已停止维护且与 bcrypt>=4.1 不兼容，
  故直接使用 bcrypt 库（同一算法、同一安全水位），依赖更少。
- 会话：服务端签名 Cookie（itsdangerous，HttpOnly + SameSite=Lax），无会话表，
  重启不丢状态；将来对接 LDAP/AD 只需在本模块新增适配器（R3）。
- 防爆破：连续 5 次失败锁定 10 分钟（内存态，单进程架构下即可）。
"""
import threading
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.errors import ApiError, err, ERR_LOCKED

SESSION_COOKIE = "tp_session"
SESSION_MAX_AGE = 12 * 3600  # 会话有效期 12 小时
LOCKOUT_THRESHOLD = 5        # 连续失败 5 次
LOCKOUT_SECONDS = 600        # 锁定 10 分钟


# ---------- 密码 ----------
def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
    except ValueError:
        return False


# ---------- 签名 Cookie 会话 ----------
class SessionSigner:
    """itsdangerous 签名的会话 Cookie（服务端签名、防伪造）。"""

    def __init__(self, secret_key: str):
        self._ser = URLSafeTimedSerializer(secret_key, salt="tp-auth-v1")

    def issue(self, user_id: int) -> str:
        return self._ser.dumps({"uid": int(user_id)})

    def verify(self, token: str) -> Optional[int]:
        try:
            data = self._ser.loads(token, max_age=SESSION_MAX_AGE)
            return int(data["uid"])
        except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
            return None


def set_session_cookie(response, signer: SessionSigner, user_id: int) -> None:
    response.set_cookie(
        SESSION_COOKIE, signer.issue(user_id),
        max_age=SESSION_MAX_AGE, httponly=True, samesite="lax", path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def get_uid(request, signer: SessionSigner) -> Optional[int]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return signer.verify(token)


# ---------- 登录锁定 ----------
class LoginLockout:
    """连续 5 次失败锁定 10 分钟；成功登录清零（§9）。"""

    def __init__(self, clock=None):
        from app.util import utcnow
        self._clock = clock or utcnow
        self._fails = {}  # employee_no -> (count, locked_until)
        self._lock = threading.Lock()

    def check(self, employee_no: str) -> None:
        """登录前检查；被锁定则抛 4401。"""
        with self._lock:
            item = self._fails.get(employee_no)
            if not item:
                return
            count, locked_until = item
            if locked_until and self._clock() < locked_until:
                remain = int((locked_until - self._clock()).total_seconds() // 60) + 1
                raise err(ERR_LOCKED, "登录失败次数过多，账号已临时锁定，请约 %d 分钟后重试" % remain)
            if locked_until:  # 锁定期已过，清零重新计数
                self._fails.pop(employee_no, None)

    def record_fail(self, employee_no: str) -> None:
        with self._lock:
            count, _ = self._fails.get(employee_no, (0, None))
            count += 1
            if count >= LOCKOUT_THRESHOLD:
                self._fails[employee_no] = (count, self._clock() + timedelta(seconds=LOCKOUT_SECONDS))
            else:
                self._fails[employee_no] = (count, None)

    def record_success(self, employee_no: str) -> None:
        with self._lock:
            self._fails.pop(employee_no, None)

    def remaining_attempts(self, employee_no: str) -> int:
        with self._lock:
            count, _ = self._fails.get(employee_no, (0, None))
            return max(0, LOCKOUT_THRESHOLD - count)


def ensure_admin(db, settings) -> bool:
    """首次启动引导管理员（§部署）：无 admin 时按配置创建，首登强制改密。"""
    from app.models import User
    from app.util import iso, utcnow
    with db.session() as s:
        exists = s.query(User.id).filter(User.role == "admin").limit(1).first()
        if exists:
            return False
        s.add(User(
            employee_no=settings.admin_employee_no,
            name=settings.admin_name,
            department="安全管理中心",
            role="admin",
            password_hash=hash_password(settings.admin_password),
            must_change_pwd=1 if settings.force_change_password else 0,
            status=1,
            created_at=iso(utcnow()),
        ))
        s.commit()
    return True
