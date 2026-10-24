"""FastAPI 依赖：当前用户、功能权限、请求上下文。"""
from __future__ import annotations

from fastapi import Depends, Header, Request

from . import permissions
from .config import settings
from .response import ApiError
from .security import TokenError, decode_token


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def current_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> permissions.UserContext:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError(40101)
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = decode_token(token)
    except TokenError as exc:
        raise ApiError(40101, str(exc)) from exc

    ctx = permissions.load_user(claims.get("sub", ""))
    if ctx is None:
        raise ApiError(40101, "账号不存在或已停用")

    request.state.user = ctx
    request.state.request_id = request.headers.get("x-request-id")
    return ctx


def require(perm: str):
    """功能权限校验依赖：require('ar:export') 用作路由依赖。"""
    async def _dep(user: permissions.UserContext = Depends(current_user)):
        if not user.has_perm(perm):
            permissions.audit(user, "deny", perm, {"reason": "no functional permission"})
            raise ApiError(40301, f"缺少权限：{perm}")
        return user
    return _dep


def page_args(page: int = 1, size: int = 20) -> tuple[int, int]:
    page = max(1, page)
    size = min(max(1, size), 200)
    return page, size


__all__ = ["current_user", "require", "page_args", "_client_ip", "settings"]
