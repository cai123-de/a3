"""统一响应封装与错误码（对应开发文档 9.1）。"""
from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

ERRORS = {
    40001: ("参数错误", 400),
    40101: ("未登录或登录已过期", 401),
    40301: ("无功能权限", 403),
    40302: ("超出数据范围", 403),
    40303: ("字段已脱敏", 403),
    40401: ("资源不存在", 404),
    42901: ("请求过于频繁", 429),
    50001: ("查询超时，请缩小筛选范围", 504),
    50002: ("AI 无法理解该问题", 422),
    50000: ("服务内部错误", 500),
}


class ApiError(Exception):
    def __init__(self, code: int, message: str | None = None, detail: Any = None):
        self.code = code
        self.message = message or ERRORS.get(code, ("错误", 400))[0]
        self.detail = detail
        super().__init__(self.message)

    @property
    def http_status(self) -> int:
        return ERRORS.get(self.code, ("错误", 400))[1]


def ok(data: Any, meta: dict | None = None, request_id: str | None = None) -> dict:
    return {
        "code": 0,
        "message": "ok",
        "data": data,
        "meta": meta or {},
        "requestId": request_id,
    }


def error_response(code: int, message: str | None = None, detail: Any = None,
                   request_id: str | None = None) -> JSONResponse:
    status = ERRORS.get(code, ("错误", 400))[1]
    return JSONResponse(
        status_code=status,
        content={
            "code": code,
            "message": message or ERRORS.get(code, ("错误",))[0],
            "detail": detail,
            "data": None,
            "requestId": request_id,
        },
    )
