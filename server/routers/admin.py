"""系统管理：用户、角色、职级映射、指标字典、审计日志。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from .. import db, permissions
from ..config import settings
from ..deps import require
from ..permissions import UserContext
from ..response import ApiError, ok
from ..security import gen_temp_password, hash_password

router = APIRouter(prefix="/admin", tags=["系统管理"])


@router.get("/users")
def users(q: str | None = None, role: str | None = None,
          user: UserContext = Depends(require("admin:user:view"))):
    rows = db.query(
        """SELECT u.id, u.username, u.name, u.title, u.email, u.status, u.grade,
                  u.last_login_at, r.code AS role, r.name AS role_name,
                  d.code AS dept_code, d.name AS dept_name, g.depth, g.amount_threshold
           FROM app.sys_user u
           JOIN app.sys_role r ON r.code = u.role_code
           JOIN app.sys_grade_scope g ON g.grade = u.grade
           LEFT JOIN app.sys_dept d ON d.code = u.dept_code
           WHERE (%s IS NULL OR u.name ILIKE '%%'||%s||'%%' OR u.username ILIKE '%%'||%s||'%%')
             AND (%s IS NULL OR r.code = %s)
           ORDER BY r.level, u.id""", (q, q, q, role, role))
    for r in rows:
        r["last_login_at"] = r["last_login_at"].isoformat(timespec="minutes") if r["last_login_at"] else None
    return ok(rows)


class UserBody(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    name: str
    role: str
    dept: str | None = None
    grade: str
    title: str | None = None
    email: str | None = None
    password: str | None = None


@router.post("/users")
def create_user(body: UserBody, user: UserContext = Depends(require("admin:user:edit"))):
    pwd = body.password or gen_temp_password()
    pwd_hash, salt = hash_password(pwd)
    try:
        rec = db.execute_returning(
            """INSERT INTO app.sys_user(username, name, title, password_hash, password_salt,
                                        role_code, dept_code, grade, email, must_change_pwd)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE) RETURNING id""",
            (body.username, body.name, body.title, pwd_hash, salt, body.role, body.dept,
             body.grade, body.email))
    except Exception as exc:  # 唯一键冲突
        raise ApiError(40001, f"账号已存在或不合法：{exc}") from exc
    permissions.audit(user, "create", "admin/users", {"username": body.username, "role": body.role})
    return ok({"id": rec["id"], "username": body.username, "tempPassword": pwd,
               "mustChangePwd": True})


class UserPatch(BaseModel):
    name: str | None = None
    role: str | None = None
    dept: str | None = None
    grade: str | None = None
    status: str | None = None
    title: str | None = None


@router.put("/users/{user_id}")
def update_user(user_id: int, body: UserPatch,
                user: UserContext = Depends(require("admin:user:edit"))):
    fields, params = [], []
    for col, val in (("name", body.name), ("role_code", body.role), ("dept_code", body.dept),
                     ("grade", body.grade), ("status", body.status), ("title", body.title)):
        if val is not None:
            fields.append(f"{col} = %s")
            params.append(val)
    if not fields:
        raise ApiError(40001, "没有需要更新的字段")
    params.append(user_id)
    db.execute(f"UPDATE app.sys_user SET {', '.join(fields)} WHERE id = %s", params)
    permissions.audit(user, "update", "admin/users",
                      {"user": user_id, "changes": body.model_dump(exclude_none=True)})
    return ok({"id": user_id, "updated": True})


@router.get("/roles")
def roles(user: UserContext = Depends(require("admin:user:view"))):
    rows = db.query("""SELECT code, name, level, perms, note FROM app.sys_role ORDER BY level""")
    for r in rows:
        r["users"] = db.scalar("SELECT count(*) FROM app.sys_user WHERE role_code = %s", (r["code"],))
    return ok(rows)


@router.get("/grades")
def grades(user: UserContext = Depends(require("admin:user:view"))):
    rows = db.query("""SELECT grade, rank, depth, amount_threshold, field_mask, note
                       FROM app.sys_grade_scope ORDER BY rank""")
    for r in rows:
        r["users"] = db.scalar("SELECT count(*) FROM app.sys_user WHERE grade = %s", (r["grade"],))
        r["amount_threshold"] = float(r["amount_threshold"]) if r["amount_threshold"] is not None else None
    return ok(rows)


class GradePatch(BaseModel):
    depth: str | None = None
    amountThreshold: float | None = None
    fieldMask: dict | None = None
    note: str | None = None


@router.put("/grades/{grade}")
def update_grade(grade: str, body: GradePatch,
                 user: UserContext = Depends(require("admin:user:edit"))):
    if body.depth and body.depth not in ("summary", "detail", "doc"):
        raise ApiError(40001, "depth 只能是 summary / detail / doc")
    fields, params = [], []
    if body.depth is not None:
        fields.append("depth = %s")
        params.append(body.depth)
    if body.amountThreshold is not None:
        fields.append("amount_threshold = %s")
        params.append(body.amountThreshold)
    if body.fieldMask is not None:
        fields.append("field_mask = %s")
        params.append(db.psycopg2.extras.Json(body.fieldMask))
    if body.note is not None:
        fields.append("note = %s")
        params.append(body.note)
    if not fields:
        raise ApiError(40001, "没有需要更新的字段")
    params.append(grade)
    db.execute(f"UPDATE app.sys_grade_scope SET {', '.join(fields)} WHERE grade = %s", params)
    permissions.audit(user, "update", "admin/grades", {"grade": grade,
                                                       "changes": body.model_dump(exclude_none=True)})
    return ok({"grade": grade, "updated": True})


@router.get("/metrics")
def metrics(user: UserContext = Depends(require("overview:view"))):
    rows = db.query("""SELECT code, name, alias, definition, unit, view_name, expr,
                              default_dim, version, owner, is_active
                       FROM app.meta_metric ORDER BY code""")
    return ok(rows)


@router.get("/audit-logs")
def audit_logs(page: int = 1, size: int = 30, action: str | None = None,
               username: str | None = None,
               user: UserContext = Depends(require("admin:audit:view"))):
    page, size = max(1, page), min(max(1, size), 200)
    where, params = [], []
    if action:
        where.append("action = %s")
        params.append(action)
    if username:
        where.append("username ILIKE %s")
        params.append(f"%{username}%")
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = db.scalar(f"SELECT count(*) FROM app.ops_audit_log{clause}", params)
    rows = db.query(
        f"""SELECT id, username, action, object, detail, ip, created_at
            FROM app.ops_audit_log{clause} ORDER BY id DESC LIMIT %s OFFSET %s""",
        params + [size, (page - 1) * size])
    return ok({
        "page": page, "size": size, "total": total,
        "rows": [{**r, "created_at": r["created_at"].isoformat(timespec="seconds")} for r in rows],
    })


@router.get("/data-scopes")
def data_scopes(user: UserContext = Depends(require("admin:user:view"))):
    rows = db.query(
        """SELECT s.id, u.username, u.name, s.scope_type, s.scope_value, s.effect,
                  s.expire_at, s.reason
           FROM app.sys_data_scope s JOIN app.sys_user u ON u.id = s.user_id
           ORDER BY s.id DESC LIMIT 200""")
    return ok([{**r, "expire_at": r["expire_at"].isoformat() if r["expire_at"] else None} for r in rows])


# ---------------- AI Key 管理（DeepSeek） ----------------

def _persist_env(key: str, value: str | None) -> None:
    """把 KEY=VALUE 持久化到项目根目录 .env（value=None 表示删除该行）。"""
    from ..config import BASE_DIR
    p = BASE_DIR / ".env"
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    out, found = [], False
    for ln in lines:
        if ln.strip().startswith(key + "="):
            found = True
            if value is not None:
                out.append(f"{key}={value}")
        else:
            out.append(ln)
    if not found and value is not None:
        out.append(f"{key}={value}")
    p.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8")


def _mask(key: str) -> str:
    return f"{key[:5]}****{key[-4:]}" if len(key) >= 12 else "****"


@router.get("/ai-key")
def ai_key_status(user: UserContext = Depends(require("admin:ai:config"))):
    """AI 接口配置状态：完整密钥永不出服务端，只回传掩码。"""

    from ..services import llm
    return ok({
        "enabled": llm.available(),
        "model": settings.llm_model,
        "baseUrl": settings.llm_base_url,
        "maskedKey": _mask(settings.llm_api_key) if settings.llm_api_key else None,
        "timeoutS": settings.llm_timeout_s,
        "effort": settings.llm_effort if settings.llm_effort in ("none", "low", "high", "max") else "high",
        "maxTokens": settings.llm_max_tokens if settings.llm_max_tokens and settings.llm_max_tokens > 0 else 0,
        "maxTokensLimit": 393216,
        "boundary": "LLM 仅做意图解析，取数与六道闸门全部在服务端语义层；密钥保存到服务端 .env，立即生效",
    })


class AiKeyBody(BaseModel):
    apiKey: str = Field(min_length=8, max_length=200)


@router.post("/ai-key")
def ai_key_save(body: AiKeyBody, user: UserContext = Depends(require("admin:ai:config"))):
    key = body.apiKey.strip()
    if not key.startswith("sk-") or len(key) < 20 or any(ch.isspace() for ch in key):
        raise ApiError(40001, "密钥格式不正确：应以 sk- 开头、长度 ≥ 20 且不含空格"
                              "（在 platform.deepseek.com/api_keys 获取）")
    settings.llm_api_key = key          # 运行时立即生效
    _persist_env("DEEPSEEK_API_KEY", key)  # 重启后仍生效
    permissions.audit(user, "update", "admin/ai-key", {"masked": _mask(key)})
    return ok({"enabled": True, "maskedKey": _mask(key)})


@router.delete("/ai-key")
def ai_key_clear(user: UserContext = Depends(require("admin:ai:config"))):
    settings.llm_api_key = ""
    _persist_env("DEEPSEEK_API_KEY", None)
    permissions.audit(user, "update", "admin/ai-key", {"masked": None})
    return ok({"enabled": False})


class AiParamsBody(BaseModel):
    effort: str = Field(pattern="^(none|low|high|max)$")
    maxTokens: int = Field(ge=0, le=393216, default=0)


@router.put("/ai-key/params")
def ai_params_save(body: AiParamsBody, user: UserContext = Depends(require("admin:ai:config"))):
    """思考模式与输出上限：effort=none 关闭思考；maxTokens=0 走官方默认（思考 64K）。"""
    settings.llm_effort = body.effort
    settings.llm_max_tokens = body.maxTokens
    _persist_env("DEEPSEEK_REASONING_EFFORT", body.effort)
    _persist_env("DEEPSEEK_MAX_TOKENS", str(body.maxTokens) if body.maxTokens else None)
    permissions.audit(user, "update", "admin/ai-key-params",
                      {"effort": body.effort, "maxTokens": body.maxTokens})
    return ok({"effort": body.effort, "maxTokens": body.maxTokens})
