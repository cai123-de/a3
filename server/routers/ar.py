"""应收与回款：账龄、逾期清单、催收任务。"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from .. import db, permissions
from ..deps import require
from ..permissions import UserContext
from ..response import ApiError, ok
from ..services import common

router = APIRouter(prefix="/ar", tags=["应收与回款"])

BUCKETS = ["未到期", "0-30 天", "31-60 天", "61-90 天", "90+ 天"]


def _period_end(period: str) -> date:
    y, m = int(period[:4]), int(period[5:7])
    nxt = date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)
    return nxt - timedelta(days=1)


@router.get("/aging")
def aging(period: str | None = None,
          user: UserContext = Depends(require("ar:view"))):
    p = common.resolve_period(period)
    rc, rp = user.region_sql('a."所在大区"')

    buckets = db.query(
        f"""SELECT a."账龄桶" AS bucket, SUM(a."发票数")::int AS invoices,
                   SUM(a."原应收金额") AS original, SUM(a."已收金额") AS received,
                   SUM(a."应收余额") AS balance, SUM(a."坏账金额") AS bad
            FROM "V_应收账龄结构" a
            WHERE a."月份" = %s AND {rc}
            GROUP BY 1""", [p, *rp])
    order = {b: i for i, b in enumerate(BUCKETS)}
    buckets.sort(key=lambda r: order.get(r["bucket"], 99))
    total = sum(float(b["balance"] or 0) for b in buckets)
    for b in buckets:
        for k in ("original", "received", "balance", "bad"):
            b[k] = round(float(b[k] or 0), 2)
        b["ratio"] = round(b["balance"] / total * 100, 2) if total else 0

    regions = db.query(
        f"""SELECT a."所在大区" AS region,
                   SUM(a."应收余额") AS balance,
                   SUM(a."应收余额") FILTER (WHERE a."账龄桶" = '90+ 天') AS over90,
                   SUM(a."应收余额") FILTER (WHERE a."账龄桶" <> '未到期') AS overdue
            FROM "V_应收账龄结构" a WHERE a."月份" = %s AND {rc}
            GROUP BY 1 ORDER BY 2 DESC""", [p, *rp])
    tiers = db.query(
        f"""SELECT a."客户分层" AS tier, SUM(a."应收余额") AS balance
            FROM "V_应收账龄结构" a WHERE a."月份" = %s AND {rc}
            GROUP BY 1 ORDER BY 2 DESC""", [p, *rp])

    overdue_total = sum(b["balance"] for b in buckets if b["bucket"] != "未到期")
    row = db.query_one(
        """SELECT "逾期应收余额","期末应收余额","开票金额","收款金额"
           FROM "V_月度经营总览" WHERE "月份" = %s""", (p,)) or {}

    return ok({
        "period": p,
        "buckets": buckets,
        "regions": [{"region": r["region"], "balance": round(float(r["balance"] or 0), 2),
                     "over90": round(float(r["over90"] or 0), 2),
                     "overdue": round(float(r["overdue"] or 0), 2)} for r in regions],
        "tiers": [{"tier": r["tier"], "balance": round(float(r["balance"] or 0), 2)} for r in tiers],
        "total": round(total, 2),
        "overdueTotal": round(overdue_total, 2),
        "over90": round(sum(b["balance"] for b in buckets if b["bucket"] == "90+ 天"), 2),
        "billing": round(float(row.get("开票金额") or 0), 2),
        "collection": round(float(row.get("收款金额") or 0), 2),
        "collectionRate": round(float(row.get("收款金额") or 0) /
                                float(row.get("开票金额") or 1) * 100, 2),
        "scope": user.scope_label,
        "note": f"账龄桶口径逾期 {overdue_total / 1e8:.2f} 亿；"
                f"总览「逾期应收」{(float(row.get('逾期应收余额') or 0)) / 1e8:.2f} 亿为已过应收日口径，差异来自月末重算。",
    }, meta=common.meta(p))


@router.get("/overdue")
def overdue(period: str | None = None, page: int = 1, size: int = 20,
            min_days: int = 0, only_unpaid: bool = True,
            user: UserContext = Depends(require("ar:view"))):
    p = common.resolve_period(period)
    end = _period_end(p)
    page, size = max(1, page), min(max(1, size), 200)
    rc, rp = user.region_sql('c."所在大区"')

    where = [
        'b."应收日" < %s',
        f"{rc}",
        'COALESCE(c."客户ID"::text, \'\') <> ALL(%s)',
    ]
    params: list[Any] = [end, *rp, user.deny_customers]
    if min_days:
        where.append("(%s - b.\"应收日\") >= %s")
        params += [end, min_days]

    base = f"""
        FROM "fact_billing" b
        JOIN "dim_customer" c ON c."客户ID" = b."客户ID"
        LEFT JOIN (SELECT "开票ID", SUM("收款金额") AS paid FROM "fact_payment" GROUP BY 1) pay
               ON pay."开票ID" = b."开票ID"
        WHERE {' AND '.join(f'({w})' for w in where)}
    """
    having = " HAVING b.\"开票金额\" - COALESCE(pay.paid,0) > 0.01 " if only_unpaid else ""

    cnt = db.query_one(f"SELECT COUNT(*) AS n FROM (SELECT b.\"开票ID\" {base} GROUP BY b.\"开票ID\", pay.paid {having}) t", params)
    total = int(cnt["n"]) if cnt else 0

    rows = db.query(
        f"""SELECT b."开票ID" AS invoice_id, b."开票类型" AS type, c."客户ID" AS customer_id,
                   c."客户名称" AS customer, c."客户分层" AS tier, c."所在大区" AS region,
                   b."开票日期" AS invoice_date, b."应收日" AS due_date, b."开票金额" AS amount,
                   COALESCE(pay.paid,0) AS paid,
                   b."开票金额" - COALESCE(pay.paid,0) AS unpaid,
                   (%s - b."应收日") AS overdue_days, b."收款状态" AS status
            {base} GROUP BY b."开票ID", b."开票类型", c."客户ID", c."客户名称", c."客户分层",
                     c."所在大区", b."开票日期", b."应收日", b."开票金额", pay.paid, b."收款状态"
            {having}
            ORDER BY unpaid DESC, overdue_days DESC
            LIMIT %s OFFSET %s""",
        [end, *params, size, (page - 1) * size])

    out = []
    for r in rows:
        r["customer"] = user.mask_customer_name(r["customer"])
        r["invoice_date"] = r["invoice_date"].isoformat()
        r["due_date"] = r["due_date"].isoformat()
        for k in ("amount", "paid", "unpaid"):
            r[k] = round(float(r[k] or 0), 2)
        if not user.can_see_amount(r["unpaid"]):
            r["masked"] = True
        out.append(r)

    sum_row = db.query_one(
        f"""SELECT COALESCE(SUM(u),0) AS s FROM (
              SELECT b."开票金额" - COALESCE(pay.paid,0) AS u {base} GROUP BY b."开票ID", pay.paid {having}) t""", params)

    permissions.audit(user, "view", "ar/overdue", {"period": p, "page": page})
    return ok({
        "period": p, "page": page, "size": size, "total": total,
        "rows": out,
        "unpaidTotal": round(float(sum_row["s"] or 0), 2),
        "folded": user.field_mask.get("amount") == "hidden",
    }, meta=common.meta(p))


class CollectionTask(BaseModel):
    invoiceIds: list[str]
    note: str | None = None
    owner: str | None = None


@router.post("/collection-task")
def create_collection_task(body: CollectionTask,
                           user: UserContext = Depends(require("ar:edit"))):
    if not body.invoiceIds:
        raise ApiError(40001, "请选择至少一张发票")
    rows = db.query(
        """SELECT b."开票ID" AS id, c."客户名称" AS customer, b."开票金额" AS amount
           FROM "fact_billing" b JOIN "dim_customer" c ON c."客户ID" = b."客户ID"
           WHERE b."开票ID" = ANY(%s)""", (body.invoiceIds,))
    created = []
    for r in rows:
        rec = db.execute_returning(
            """INSERT INTO app.sys_alert(rule_code, level, title, detail, metric_code,
                                         period, object_id, amount, status, owner)
               VALUES ('AR_TASK','mid',%s,%s,'ar_balance',%s,%s,%s,'open',%s) RETURNING id""",
            (f"催收任务：{r['customer']}", body.note or "批量派单生成",
             common.latest_period(), r["id"], r["amount"], body.owner or user.name))
        created.append(rec["id"] if rec else None)
    permissions.audit(user, "update", "ar/collection-task",
                      {"count": len(created), "invoices": body.invoiceIds[:20]})
    return ok({"created": len(created), "ids": created})


@router.get("/collection-tasks")
def collection_tasks(user: UserContext = Depends(require("ar:view"))):
    rows = db.query(
        """SELECT id, title, detail, amount, status, owner, created_at
           FROM app.sys_alert WHERE rule_code = 'AR_TASK'
           ORDER BY created_at DESC LIMIT 50""")
    return ok([{**r, "created_at": r["created_at"].isoformat(timespec="minutes"),
                "amount": round(float(r["amount"] or 0), 2)} for r in rows])


@router.get("/collection")
def collection(period: str | None = None,
               user: UserContext = Depends(require("ar:view"))):
    p = common.resolve_period(period)
    rc, rp = user.region_sql('c."所在大区"')
    rows = db.query(
        f"""SELECT to_char(pay."收款日期",'YYYY-MM') AS month, COUNT(*)::int AS count,
                   SUM(pay."收款金额") AS amount
            FROM "fact_payment" pay JOIN "dim_customer" c ON c."客户ID" = pay."客户ID"
            WHERE to_char(pay."收款日期",'YYYY-MM') >= %s AND {rc}
            GROUP BY 1 ORDER BY 1""",
        [common.shift_period(p, -11), *rp])
    by_month = [{"month": r["month"], "count": r["count"], "amount": round(float(r["amount"] or 0), 2)}
                for r in rows]
    methods = db.query(
        """SELECT "收款方式" AS method, COUNT(*)::int AS count, SUM("收款金额") AS amount
           FROM "fact_payment" WHERE to_char("收款日期",'YYYY-MM') = %s GROUP BY 1 ORDER BY 3 DESC""", (p,))
    return ok({
        "period": p,
        "byMonth": by_month,
        "methods": [{"method": r["method"], "count": r["count"],
                     "amount": round(float(r["amount"] or 0), 2)} for r in methods],
    }, meta=common.meta(p))
