"""三维权限引擎：角色（能做什么）× 部门（能看多宽）× 职级（能看多深）。

设计要点（对应开发文档 5.5）：
1. 权限过滤在 SQL 生成阶段注入，不在应用层过滤结果——否则总数泄露、分页错位；
2. deny（黑名单）优先级最高，其次显式授权，最后才是部门宽度；
3. 超过职级金额阈值的行不隐藏而是折叠，保证列合计仍然对得上；
4. 每一次拒绝都要写审计日志，让「为什么看不到」可追溯。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from . import db

# 角色可越过职级深度的例外（CFO / 管理员需要看单据）
ROLE_DEPTH_OVERRIDE = {"cfo": "doc", "admin": "doc", "fin_bp": None}


@dataclass
class UserContext:
    id: int
    username: str
    name: str
    title: str
    role: str
    role_name: str
    role_level: int
    perms: list[str]
    dept_code: str | None
    dept_name: str | None
    grade: str
    depth: str                    # summary / detail / doc
    amount_threshold: float | None
    field_mask: dict[str, str]
    regions: list[str] | None     # None = 不限大区
    allow_customers: list[str] = field(default_factory=list)
    deny_customers: list[str] = field(default_factory=list)

    # ---------- 功能权限 ----------
    def has_perm(self, code: str) -> bool:
        for p in self.perms:
            if p == "*" or p == code:
                return True
            if p.endswith(":*") and code.startswith(p[:-1]):
                return True
        return False

    # ---------- 数据范围 ----------
    @property
    def scope_label(self) -> str:
        if self.regions is None:
            return "全公司"
        return "、".join(self.regions)

    def region_sql(self, column: str) -> tuple[str, list[Any]]:
        """返回 (sql 片段, 参数)。regions 为 None 表示不限。"""
        if self.regions is None:
            return "TRUE", []
        if not self.regions:
            return "FALSE", []
        return f"{column} = ANY(%s)", [self.regions]

    def deny_sql(self, column: str) -> tuple[str, list[Any]]:
        if not self.deny_customers:
            return "TRUE", []
        return f"COALESCE({column}::text, '') <> ALL(%s)", [self.deny_customers]

    def can_see_amount(self, amount: float | None) -> bool:
        if self.field_mask.get("amount") == "hidden":
            return False
        if self.amount_threshold is None or amount is None:
            return True
        return abs(float(amount)) <= self.amount_threshold

    # ---------- 脱敏 ----------
    def mask_customer_name(self, name: str | None) -> str | None:
        if not name:
            return name
        if self.field_mask.get("customer_name") == "mask":
            return name[:2] + "*" * max(2, len(name) - 2)
        return name

    def mask_money(self, value: Any) -> Any:
        if self.field_mask.get("amount") == "hidden":
            return None
        return value

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "name": self.name,
            "title": self.title,
            "role": self.role,
            "roleName": self.role_name,
            "grade": self.grade,
            "depth": self.depth,
            "amountThreshold": self.amount_threshold,
            "fieldMask": self.field_mask,
            "dept": {"code": self.dept_code, "name": self.dept_name},
            "regions": self.regions,
            "scopeLabel": self.scope_label,
            "perms": self.perms,
            "canExport": self.has_perm("report:export") or self.has_perm("*"),
        }


USER_SQL = """
SELECT u.id, u.username, u.name, u.title, u.role_code, u.dept_code, u.grade, u.status,
       r.name AS role_name, r.level AS role_level, r.perms,
       d.name AS dept_name, d.region AS dept_region,
       g.depth, g.amount_threshold, g.field_mask
FROM app.sys_user u
JOIN app.sys_role r ON r.code = u.role_code
JOIN app.sys_grade_scope g ON g.grade = u.grade
LEFT JOIN app.sys_dept d ON d.code = u.dept_code
WHERE u.username = %s
"""


def _load_regions(dept_code: str | None) -> list[str] | None:
    """部门决定可见大区；沿组织树向上找最近的 region，找不到则不限（总部/财务）。"""
    if not dept_code:
        return None
    row = db.query_one(
        """
        WITH RECURSIVE up AS (
            SELECT code, parent_code, region, 1 AS lvl FROM app.sys_dept WHERE code = %s
            UNION ALL
            SELECT d.code, d.parent_code, d.region, up.lvl + 1
            FROM app.sys_dept d JOIN up ON d.code = up.parent_code
        )
        SELECT region FROM up WHERE region IS NOT NULL ORDER BY lvl LIMIT 1
        """,
        (dept_code,),
    )
    if not row:
        return None
    region = row["region"]
    # 大区节点：包含该大区及其下所有子部门；这里以 region 值直接过滤客户
    return [region]


def load_user(username: str) -> UserContext | None:
    row = db.query_one(USER_SQL, (username,))
    if not row or row["status"] != "active":
        return None

    role = row["role_code"]
    depth = ROLE_DEPTH_OVERRIDE.get(role) or row["depth"]
    threshold = None if role in ("cfo", "admin") else (
        float(row["amount_threshold"]) if row["amount_threshold"] is not None else None
    )

    scopes = db.query(
        """SELECT scope_type, scope_value, effect FROM app.sys_data_scope
           WHERE user_id = %s AND (expire_at IS NULL OR expire_at >= CURRENT_DATE)""",
        (row["id"],),
    )
    allow = [s["scope_value"] for s in scopes if s["scope_type"] == "customer" and s["effect"] == "allow"]
    deny = [s["scope_value"] for s in scopes if s["scope_type"] == "customer" and s["effect"] == "deny"]

    return UserContext(
        id=row["id"],
        username=row["username"],
        name=row["name"],
        title=row["title"] or "",
        role=role,
        role_name=row["role_name"],
        role_level=row["role_level"],
        perms=list(row["perms"] or []),
        dept_code=row["dept_code"],
        dept_name=row["dept_name"],
        grade=row["grade"],
        depth=depth,
        amount_threshold=threshold,
        field_mask=dict(row["field_mask"] or {}),
        regions=_load_regions(row["dept_code"]),
        allow_customers=allow,
        deny_customers=deny,
    )


def load_user_by_id(user_id: int) -> UserContext | None:
    row = db.query_one("SELECT username FROM app.sys_user WHERE id = %s", (user_id,))
    return load_user(row["username"]) if row else None


# ---------------------------- 审计 ----------------------------
def audit(ctx: UserContext | None, action: str, obj: str, detail: dict | None = None,
          ip: str | None = None, request_id: str | None = None) -> None:
    db.execute(
        """INSERT INTO app.ops_audit_log(user_id, username, action, object, detail, ip, request_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (
            ctx.id if ctx else None,
            ctx.username if ctx else None,
            action,
            obj[:96],
            db.psycopg2.extras.Json(detail or {}),
            ip,
            request_id,
        ),
    )


# ---------------------------- 行级处理 ----------------------------
def fold_by_threshold(rows: Iterable[dict], ctx: UserContext, amount_key: str,
                      id_key: str | None = None) -> tuple[list[dict], dict | None]:
    """超过职级单笔阈值的行折叠为一条「N 笔大额」，保证合计不变。"""
    rows = list(rows)
    if ctx.amount_threshold is None:
        return rows, None
    keep, folded = [], []
    for r in rows:
        amt = r.get(amount_key)
        if amt is None or abs(float(amt)) <= ctx.amount_threshold:
            keep.append(r)
        else:
            folded.append(r)
    if not folded:
        return rows, None
    summary = {
        "folded": True,
        "count": len(folded),
        "sum": round(sum(abs(float(r[amount_key])) for r in folded), 2),
        "hint": f"{len(folded)} 笔大额已折叠，需申请查看明细",
    }
    return keep, summary
