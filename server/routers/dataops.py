"""数据管理：数据资产盘点、表关系地图、期间管理。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import db
from ..deps import require
from ..permissions import UserContext
from ..response import ok

router = APIRouter(prefix="/dataops", tags=["数据管理"])


@router.get("/assets")
def assets(user: UserContext = Depends(require("dataops:view"))):
    """数据资产：schema 内全部表与视图，含精确行数与注释。"""
    rows = db.query(
        """SELECT c.relname              AS name,
                  CASE c.relkind WHEN 'r' THEN 'table' WHEN 'v' THEN 'view' END AS kind,
                  obj_description(c.oid)  AS comment
           FROM   pg_class c
           JOIN   pg_namespace n ON n.oid = c.relnamespace
           WHERE  n.nspname = %s AND c.relkind IN ('r','v')
           ORDER  BY c.relkind, c.relname""", (db.settings.data_schema,))
    for r in rows:
        try:
            r["rows"] = db.query_one(f'SELECT count(*) AS c FROM "{db.settings.data_schema}"."{r["name"]}"')["c"]
        except Exception:  # noqa: BLE001
            r["rows"] = None
    tables = [r for r in rows if r["kind"] == "table"]
    views = [r for r in rows if r["kind"] == "view"]
    return ok({"tables": tables, "views": views,
               "summary": {"tables": len(tables), "views": len(views),
                           "rows_total": sum(r["rows"] or 0 for r in tables)}})


@router.get("/relations")
def relations(user: UserContext = Depends(require("dataops:view"))):
    """表关系地图：sem_relation 全量。"""
    return ok(db.query(
        """SELECT from_table, from_col, to_table, to_col, cardinality, note
           FROM "文件夹".sem_relation
           ORDER BY from_table, to_table"""))


@router.get("/periods")
def periods(user: UserContext = Depends(require("dataops:view"))):
    """期间管理：60 期间与关账状态。"""
    rows = db.query(
        """SELECT period, status,
                  to_char(closed_at, 'YYYY-MM-DD HH24:MI') AS closed_at, closed_by, note
           FROM app.fin_period ORDER BY period DESC""")
    return ok({"latest": rows[0]["period"] if rows else None, "rows": rows})
