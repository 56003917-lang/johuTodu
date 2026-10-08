# -*- coding: utf-8 -*-
"""认证路由（/api/v1/auth、/api/v1/me）——技术设计文档 §5 学员端接口。"""
import logging

from fastapi import APIRouter, Depends, Request, Response

from app.deps import get_current_user
from app.errors import err, ok
from app.errors import (ERR_BAD_CREDENTIAL, ERR_USER_DISABLED, ERR_PARAM,
                        ERR_UNAUTHORIZED)
from app.models import User
from app.schemas import LoginIn, PasswordChangeIn
from app.security import (clear_session_cookie, get_uid, hash_password,
                          set_session_cookie, verify_password)
from app.util import iso, utcnow

log = logging.getLogger("app.auth")
router = APIRouter()


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response):
    """工号+密码登录；连续 5 次失败锁定 10 分钟（防爆破）。"""
    st = request.app.state
    employee_no = body.employee_no.strip()
    st.lockout.check(employee_no)
    with st.db.session() as s:
        user = s.query(User).filter(User.employee_no == employee_no).one_or_none()
        if user and user.status != 1:
            raise err(ERR_USER_DISABLED)
        if not user or not verify_password(body.password, user.password_hash):
            st.lockout.record_fail(employee_no)
            remaining = st.lockout.remaining_attempts(employee_no)
            msg = "工号或密码错误" if remaining > 0 else "登录失败次数过多，账号已临时锁定 10 分钟"
            raise err(ERR_BAD_CREDENTIAL, msg)
        st.lockout.record_success(employee_no)
        set_session_cookie(response, st.signer, user.id)
        log.info("登录成功: %s(%s)", user.name, user.employee_no)
        return ok(user.brief())


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    """登出：结束当前学习会话并清除 Cookie。"""
    st = request.app.state
    uid = get_uid(request, st.signer)
    if uid:
        st.engine.stop_all_for_user(uid, reason="logout")
    clear_session_cookie(response)
    return ok(msg="已退出登录")


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    """当前用户信息与首登改密标记。"""
    return ok(user.brief())


@router.post("/me/password")
def change_password(body: PasswordChangeIn, request: Request,
                    user: User = Depends(get_current_user)):
    """修改本人密码（首登强制改密的落地）。"""
    st = request.app.state
    if not verify_password(body.old_password, user.password_hash):
        raise err(ERR_BAD_CREDENTIAL, "原密码不正确")
    if body.new_password == body.old_password:
        raise err(ERR_PARAM, "新密码不能与原密码相同")
    with st.db.session() as s:
        u = s.get(User, user.id)
        u.password_hash = hash_password(body.new_password)
        u.must_change_pwd = 0
        u.updated_at = iso(utcnow())
        s.commit()
    return ok({"must_change_pwd": False}, msg="密码修改成功")
