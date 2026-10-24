"""认证：登录、刷新、登出、当前用户与菜单。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from .. import db, permissions
from ..config import settings
from ..deps import current_user
from ..response import ApiError, ok
from ..security import hash_password, issue_token, verify_password

router = APIRouter(prefix="/auth", tags=["认证"])

MENUS = [
    {"id": "overview", "name": "经营驾驶舱", "perm": "overview:view"},
    {"id": "customers", "name": "客户分析", "perm": "customer:view"},
    {"id": "ar", "name": "应收与回款", "perm": "ar:view"},
    {"id": "budget", "name": "预算管理", "perm": "budget:view"},
    {"id": "semantic", "name": "语义模型", "perm": "semantic:view"},
    {"id": "ai", "name": "AI 分析", "perm": "ai:ask"},
    {"id": "reports", "name": "报表中心", "perm": "report:view"},
    {"id": "alerts", "name": "预警中心", "perm": "alert:view"},
    {"id": "dataops", "name": "数据管理", "perm": "dataops:view"},
    {"id": "admin", "name": "系统管理", "perm": "admin:user:view"},
]


class LoginBody(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    password: str = Field(min_length=4, max_length=64)


def _log(username: str, ok_flag: bool, request: Request, reason: str = "") -> None:
    db.execute(
        """INSERT INTO app.sys_login_log(username, ok, ip, ua, reason)
           VALUES (%s,%s,%s,%s,%s)""",
        (username, ok_flag, (request.client.host if request.client else "unknown"),
         (request.headers.get("user-agent") or "")[:200], reason[:64]),
    )


@router.post("/login")
def login(body: LoginBody, request: Request):
    row = db.query_one(
        """SELECT u.*, r.name AS role_name FROM app.sys_user u
           JOIN app.sys_role r ON r.code = u.role_code WHERE u.username = %s""",
        (body.username,),
    )
    if not row or row["status"] != "active":
        _log(body.username, False, request, "账号不存在或已停用")
        raise ApiError(40101, "账号不存在或已停用")
    if not verify_password(body.password, row["password_hash"], row["password_salt"]):
        _log(body.username, False, request, "口令错误")
        raise ApiError(40101, "账号或密码错误")

    db.execute("UPDATE app.sys_user SET last_login_at = now() WHERE id = %s", (row["id"],))
    _log(body.username, True, request)

    access = issue_token({
        "sub": row["username"], "uid": row["id"], "role": row["role_code"],
        "grade": row["grade"], "typ": "access",
    })
    refresh = issue_token({
        "sub": row["username"], "uid": row["id"], "typ": "refresh",
    }, ttl_seconds=settings.refresh_ttl_days * 86400)

    ctx = permissions.load_user(row["username"])
    permissions.audit(ctx, "login", "auth/login", {"role": row["role_code"]},
                      request.client.host if request.client else None)
    return ok({
        "accessToken": access,
        "refreshToken": refresh,
        "expiresIn": settings.token_ttl_minutes * 60,
        "user": ctx.as_dict() if ctx else None,
        "menus": [m for m in MENUS if ctx and ctx.has_perm(m["perm"])],
        "mustChangePwd": row["must_change_pwd"],
    })


class RefreshBody(BaseModel):
    refreshToken: str


@router.post("/refresh")
def refresh_token(body: RefreshBody):
    from ..security import TokenError, decode_token
    try:
        claims = decode_token(body.refreshToken)
    except TokenError as exc:
        raise ApiError(40101, str(exc)) from exc
    if claims.get("typ") != "refresh":
        raise ApiError(40101, "刷新令牌无效")
    ctx = permissions.load_user(claims["sub"])
    if not ctx:
        raise ApiError(40101, "账号已停用")
    access = issue_token({"sub": ctx.username, "uid": ctx.id, "role": ctx.role,
                          "grade": ctx.grade, "typ": "access"})
    return ok({"accessToken": access, "expiresIn": settings.token_ttl_minutes * 60,
               "user": ctx.as_dict()})


@router.post("/logout")
def logout(user: permissions.UserContext = Depends(current_user)):
    permissions.audit(user, "logout", "auth/logout")
    return ok({"ok": True, "at": datetime.now().isoformat(timespec="seconds")})


@router.get("/me")
def me(user: permissions.UserContext = Depends(current_user)):
    return ok({
        "user": user.as_dict(),
        "menus": [m for m in MENUS if user.has_perm(m["perm"])],
        "serverTime": datetime.now().isoformat(timespec="seconds"),
    })


@router.get("/demo-accounts")
def demo_accounts():
    """演示用：列出内置身份（不含口令），前端登录页可直接点选。"""
    rows = db.query(
        """SELECT u.username, u.name, u.title, u.grade, r.name AS role_name,
                  d.name AS dept_name, g.depth, g.amount_threshold
           FROM app.sys_user u
           JOIN app.sys_role r ON r.code = u.role_code
           JOIN app.sys_grade_scope g ON g.grade = u.grade
           LEFT JOIN app.sys_dept d ON d.code = u.dept_code
           WHERE u.status = 'active' ORDER BY r.level, u.id"""
    )
    return ok([dict(r) for r in rows])
