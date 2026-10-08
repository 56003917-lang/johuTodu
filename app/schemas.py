# -*- coding: utf-8 -*-
"""请求体模型（pydantic）。"""
from typing import Optional

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    employee_no: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class PasswordChangeIn(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class StudyStartIn(BaseModel):
    course_id: int


class HeartbeatIn(BaseModel):
    session_id: int
    last_position: Optional[dict] = None
    visible: bool = True


class ConfirmIn(BaseModel):
    session_id: int
    token: str = Field(min_length=1, max_length=64)


class StopIn(BaseModel):
    session_id: int
    last_position: Optional[dict] = None
    reason: str = "normal"
