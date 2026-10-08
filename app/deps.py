# -*- coding: utf-8 -*-
"""FastAPI 依赖：请求级 DB 会话 / 当前用户 / 管理员校验（技术设计文档 §9）。"""
from fastapi import Depends, Request

from app.db import Database
from app.errors import ApiError, err
from app.errors import ERR_UNAUTHORIZED, ERR_ADMIN_ONLY
from app.models import User
from app.security import SessionSigner, get_uid


def get_settings(request: Request):
    return request.app.state.settings


def get_db(request: Request):
    db: Database = request.app.state.db
    with db.session() as s:
        yield s


def get_current_user(request: Request, db=Depends(get_db)) -> User:
    signer: SessionSigner = request.app.state.signer
    uid = get_uid(request, signer)
    if uid is None:
        raise err(ERR_UNAUTHORIZED)
    user = db.get(User, uid)
    if not user or user.status != 1:
        raise err(ERR_UNAUTHORIZED, "会话已失效，请重新登录")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise err(ERR_ADMIN_ONLY)
    return user
