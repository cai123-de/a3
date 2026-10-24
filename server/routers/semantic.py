"""语义模型：指标字典、下钻映射、语义视图清单、长表取数。"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Query

from .. import db
from ..deps import require
from ..permissions import UserContext
from ..response import ApiError, ok

router = APIRouter(prefix="/semantic", tags=["语义模型"])


@router.get("/metrics")
def metrics(user: UserContext = Depends(require("semantic:view"))):
    """指标字典：31 条指标 + 最新口径版本信息。"""
    rows = db.query(
        """SELECT m.code, m.name, m.alias AS aliases, m.definition, m.unit,
                  m.view_name AS source_view, m.expr, m.default_dim,
                  m.version AS caliber_version, m.owner, m.is_active,
                  lv.effective_from AS caliber_effective_from,
                  lv.change_reason  AS last_change_reason,
                  lv.approved_by    AS last_approved_by
           FROM app.meta_metric m
           LEFT JOIN LATERAL (
                SELECT mv.effective_from, mv.change_reason, mv.approved_by
                FROM   app.meta_metric_version mv
                WHERE  mv.metric_code = m.code
                ORDER  BY mv.effective_from DESC NULLS LAST
                LIMIT  1
           ) lv ON TRUE
           ORDER BY m.code""")
    for r in rows:
        r["caliber_effective_from"] = (r["caliber_effective_from"].isoformat()
                                       if r["caliber_effective_from"] else None)
    return ok(rows)


@router.get("/metrics/{code}")
def metric_detail(code: str, user: UserContext = Depends(require("semantic:view"))):
    """单指标详情：口径定义 + 版本沿革 + 下钻映射。"""
    m = db.query_one(
        """SELECT code, name, alias AS aliases, definition, unit,
                  view_name AS source_view, expr, default_dim,
                  version AS caliber_version, owner, is_active
           FROM app.meta_metric WHERE code = %s""", (code,))
    if not m:
        raise ApiError(50001, f"指标不存在：{code}")
    m["versions"] = db.query(
        """SELECT version, definition, effective_from, effective_to,
                  change_reason, approved_by
           FROM app.meta_metric_version WHERE metric_code = %s
           ORDER BY effective_from DESC NULLS LAST""", (code,))
    for v in m["versions"]:
        v["effective_from"] = v["effective_from"].isoformat() if v["effective_from"] else None
        v["effective_to"] = v["effective_to"].isoformat() if v["effective_to"] else None
    m["drills"] = db.query(
        """SELECT parent_path, dim, label, view_name, group_cols, amount_expr
           FROM app.meta_drill_map
           WHERE parent_path = %s OR parent_path LIKE %s
           ORDER BY parent_path, sort_no""", (code, code + ".%"))
    return ok(m)


@router.get("/drills")
def drills(user: UserContext = Depends(require("semantic:view"))):
    """下钻映射全表：parent_path 树。"""
    rows = db.query(
        """SELECT parent_path, dim, label, view_name, group_cols,
                  amount_expr, extra_where, sort_no
           FROM app.meta_drill_map
           ORDER BY parent_path, sort_no""")
    return ok(rows)


@router.get("/views")
def semantic_views(user: UserContext = Depends(require("semantic:view"))):
    """sem_* 语义视图清单：用途说明 + 实时行数。"""
    metas = [
        {"name": "sem_relation",    "layer": "关系层", "desc": "表关系 JOIN 地图：31 条 ER 外键 + 4 条业务链路（含多态外键警示）"},
        {"name": "sem_metric_dict", "layer": "字典层", "desc": "指标字典：编码/别名/口径/表达式/版本/责任人，AI 白名单元数据源"},
        {"name": "sem_metric_wide", "layer": "指标层", "desc": "月度指标宽表：22 指标列 + 3 环比列，1 行 = 1 月，人工对数与报表直连"},
        {"name": "sem_metric_long", "layer": "指标层", "desc": "月度指标长表（EAV）：18 指标 × 60 月，AI/BI 统一取数模板"},
    ]
    for v in metas:
        try:
            v["rows"] = db.query_one(f'SELECT count(*) AS c FROM "文件夹".{v["name"]} ')["c"]
        except Exception:  # noqa: BLE001
            v["rows"] = None
    return ok(metas)


@router.get("/values")
def values(code: str, start: str | None = None, end: str | None = None,
           user: UserContext = Depends(require("semantic:view"))):
    """长表取数：指定指标 + 期间段的序列（默认近 12 期）。"""
    if not db.query_one("SELECT code FROM app.meta_metric WHERE code = %s", (code,)):
        raise ApiError(50001, f"指标不存在：{code}")
    pat = re.compile(r"^\d{4}-\d{2}$")
    if (start and not pat.match(start)) or (end and not pat.match(end)):
        raise ApiError(40001, "期间格式应为 YYYY-MM")
    if not end:
        end = db.query_one('SELECT max("年月")::TEXT AS p FROM "文件夹"."dim_date"')["p"]
    if not start:
        start = db.query_one(
            """SELECT min(period)::TEXT AS p FROM (
                   SELECT DISTINCT period FROM "文件夹".sem_metric_long
                   WHERE period <= %s ORDER BY period DESC LIMIT 12) t""", (end,))["p"]
    rows = db.query(
        """SELECT period, metric_code, metric_name, unit, value
           FROM "文件夹".sem_metric_long
           WHERE metric_code = %s AND period BETWEEN %s AND %s
           ORDER BY period""", (code, start, end))
    return ok({"code": code, "start": start, "end": end, "rows": rows})
