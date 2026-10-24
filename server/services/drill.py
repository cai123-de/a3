"""下钻服务：完全由 meta_drill_map 配置驱动，新增层级不需要改代码。"""
from __future__ import annotations

import re
from typing import Any

from .. import db
from ..permissions import UserContext
from ..response import ApiError
from . import common

_REGION_VIEWS: dict[str, set[str]] = {}


def _view_columns(view: str) -> set[str]:
    if view not in _REGION_VIEWS:
        rows = db.query(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema = current_schema() AND table_name = %s""",
            (view.strip('"'),),
        )
        if not rows:
            rows = db.query(
                """SELECT column_name FROM information_schema.columns
                   WHERE table_schema = %s AND table_name = %s""",
                (db.settings.data_schema, view.strip('"')),
            )
        _REGION_VIEWS[view] = {r["column_name"] for r in rows}
    return _REGION_VIEWS[view]


def mappings() -> list[dict]:
    return db.query("SELECT * FROM app.meta_drill_map ORDER BY parent_path, sort_no")


def dims_for(path: str) -> list[dict]:
    return db.query(
        "SELECT dim, label, parent_path FROM app.meta_drill_map WHERE parent_path = %s ORDER BY sort_no",
        (path,),
    )


def drill(path: str, dim: str | None, period: str, filters: dict[str, Any] | None,
          page: int, size: int, user: UserContext) -> dict:
    period = common.resolve_period(period)
    if not dim:
        rows = dims_for(path)
        if not rows:
            raise ApiError(40001, f"节点 {path} 没有配置下钻维度")
        dim = rows[0]["dim"]

    mapping = db.query_one(
        "SELECT * FROM app.meta_drill_map WHERE parent_path = %s AND dim = %s", (path, dim)
    )
    if not mapping:
        raise ApiError(40001, f"未配置下钻：{path} / {dim}")

    view = mapping["view_name"]
    group_names = [c.strip().strip('"') for c in mapping["group_cols"].split(",")]
    group_cols = [f'"{c}"' for c in group_names]
    amount_expr = mapping["amount_expr"].strip()
    if not re.match(r"(?i)(sum|count|avg|min|max|round)\s*\(", amount_expr):
        amount_expr = f"SUM({amount_expr})"

    where_parts: list[str] = []
    params: list[Any] = []

    if mapping["extra_where"]:
        clause = mapping["extra_where"].replace(":period", "%s")
        where_parts.append(clause)
        params.append(period)

    # 数据权限：只在视图确有该列时注入，避免 SQL 报错
    cols = _view_columns(view)
    if user.regions is not None and "所在大区" in cols:
        where_parts.append('"所在大区" = ANY(%s)')
        params.append(user.regions)
    if user.deny_customers and "客户ID" in cols:
        where_parts.append('"客户ID"::text <> ALL(%s)')
        params.append(user.deny_customers)

    for k, v in (filters or {}).items():
        if k not in cols:
            raise ApiError(40001, f"不支持的过滤字段：{k}")
        where_parts.append(f'"{k}" = %s')
        params.append(v)

    where = (" WHERE " + " AND ".join(f"({w})" for w in where_parts)) if where_parts else ""
    order_col = "amount"
    base = f'FROM {view}{where} GROUP BY {", ".join(group_cols)}'

    total_row = db.query_one(f"SELECT COUNT(*) AS n, COALESCE(SUM(amt),0) AS total FROM (SELECT {amount_expr} AS amt {base}) t", params)
    total = int(total_row["n"]) if total_row else 0
    subtotal = float(total_row["total"]) if total_row else 0.0

    rows = db.query(
        f"""SELECT {', '.join(group_cols)}, {amount_expr} AS amount {base}
            ORDER BY amount DESC NULLS LAST LIMIT %s OFFSET %s""",
        params + [size, (page - 1) * size],
    )

    columns: list[str] = list(group_names)
    columns += ["金额", "占比"]

    out_rows = []
    visible_sum = 0.0
    folded: list[dict] = []
    for r in rows:
        amt = float(r["amount"] or 0)
        item = {k: r[k] for k in group_names}
        if "客户名称" in item:
            item["客户名称"] = user.mask_customer_name(item["客户名称"])
        if not user.can_see_amount(amt):
            folded.append({"客户": item.get("客户名称") or item.get("客户ID"), "金额": amt})
            continue
        visible_sum += amt
        item["金额"] = round(amt, 2)
        item["占比"] = round(amt / subtotal * 100, 2) if subtotal else None
        item["hasChild"] = path.count(".") < 1
        out_rows.append(item)

    return {
        "node": {"path": path, "dim": dim, "label": mapping["label"], "view": view},
        "columns": columns,
        "rows": out_rows,
        "page": page,
        "size": size,
        "total": total,
        "subtotal": round(visible_sum, 2),
        "parentTotal": round(subtotal, 2),
        "folded": {
            "count": len(folded),
            "amount": round(sum(f["金额"] for f in folded), 2),
            "hint": f"{len(folded)} 笔超过职级阈值（{user.amount_threshold:,.0f} 元）已折叠，申请后可查看明细",
        } if folded else None,
        "checkPassed": abs(subtotal - visible_sum) < max(1.0, subtotal * 0.001) or bool(folded),
        "scope": user.scope_label,
    }


def statement_node_value(path: str, period: str, user: UserContext) -> float | None:
    """取某个节点在期间内的合计值（供下钻校验父项）。"""
    mapping = db.query_one(
        """SELECT view_name, amount_expr, extra_where FROM app.meta_drill_map
           WHERE parent_path = %s ORDER BY sort_no LIMIT 1""", (path,))
    if not mapping:
        return None
    where = ""
    params: list[Any] = []
    if mapping["extra_where"]:
        where = " WHERE " + mapping["extra_where"].replace(":period", "%s")
        params.append(period)
    row = db.query_one(
        f"SELECT COALESCE(SUM(amt),0) AS v FROM (SELECT {mapping['amount_expr']} AS amt FROM {mapping['view_name']}{where}) t",
        params)
    return float(row["v"]) if row else None
