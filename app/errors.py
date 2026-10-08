# -*- coding: utf-8 -*-
"""统一响应包裹与错误码（技术设计文档 §5）。

所有接口返回 {"code": 0, "data": ..., "msg": ""}；
错误码分段：4xxx 客户端（如 4101 未登录、4202 弹窗超时）、5xxx 服务端。
"""


class ApiError(Exception):
    def __init__(self, code: int, msg: str, http_status: int = 400):
        super().__init__(msg)
        self.code = code
        self.msg = msg
        self.http_status = http_status


# ---- 错误码表（4xxx 客户端 / 5xxx 服务端） ----
ERR_PARAM = (4001, "参数错误", 400)
ERR_NOT_FOUND = (4041, "资源不存在", 404)
ERR_UNAUTHORIZED = (4101, "未登录或会话已失效", 401)
ERR_SESSION_GONE = (4201, "学习会话不存在或已结束，请重新开始学习", 404)
ERR_CHALLENGE = (4202, "防挂机确认失败：令牌无效或已使用", 409)
ERR_COURSE_FILE = (4203, "课程文件缺失，请联系管理员", 404)
ERR_BAD_CREDENTIAL = (4301, "工号或密码错误", 401)
ERR_USER_DISABLED = (4302, "账号已停用", 403)
ERR_MUST_CHANGE_PWD = (4304, "请先修改初始密码后再学习", 403)
ERR_LOCKED = (4401, "登录失败次数过多，账号已临时锁定", 423)
ERR_ADMIN_ONLY = (4501, "需要管理员权限", 403)
ERR_SERVER = (5001, "服务端内部错误", 500)


def err(spec, msg: str = None) -> ApiError:
    code, default, http_status = spec
    return ApiError(code, msg or default, http_status)


def ok(data=None, msg: str = "") -> dict:
    """统一成功包裹。"""
    return {"code": 0, "data": data, "msg": msg}
