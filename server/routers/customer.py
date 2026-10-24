"""客户分析：分层、健康度、Top 客户、客户 360、续约日历。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from .. import db, permissions
from ..deps import require
from ..permissions import UserContext, fold_by_threshold
from ..response import ApiError, ok
from ..services import common

router = APIRouter(prefix="/customer", tags=["客户分析"])


def _region_clause(user: UserContext, alias: str = "") -> tuple[str, list]:
    col = f'{alias}"所在大区"' if alias else '"所在大区"'
    return user.region_sql(col)


@router.get("/summary")
def summary(period: str | None = None,
            user: UserContext = Depends(require("customer:view"))):
    p = common.resolve_period(period)
    rc, rp = _region_clause(user)

    tiers = db.query(
        f"""SELECT "客户分层" AS tier, COUNT(*)::int AS customers,
                   SUM("当前ARR") AS arr, SUM("累计确认收入") AS revenue
            FROM "V_客户360视图" WHERE {rc} GROUP BY 1 ORDER BY 3 DESC NULLS LAST""", rp)
    health = db.query(
        f"""SELECT "健康度等级" AS level, COUNT(DISTINCT "客户ID")::int AS customers
            FROM "V_客户健康度详情" WHERE "月份" = %s AND {rc} GROUP BY 1""", [p, *rp])
    industries = db.query(
        f"""SELECT "行业" AS name, COUNT(*)::int AS customers, SUM("当前ARR") AS arr
            FROM "V_客户360视图" WHERE {rc} GROUP BY 1 ORDER BY 3 DESC NULLS LAST LIMIT 8""", rp)
    channels = db.query(
        f"""SELECT "获客渠道" AS name, COUNT(*)::int AS customers
            FROM "V_客户360视图" WHERE {rc} GROUP BY 1 ORDER BY 2 DESC""", rp)

    top = db.query(
        f"""SELECT "客户ID","客户名称","客户分层" AS tier,"所在大区" AS region,"行业" AS industry,
                   "当前ARR","累计确认收入","累计毛利率%" AS margin,"最新应收余额" AS ar,
                   "健康度等级" AS health,"累计工单数" AS tickets
            FROM "V_客户360视图" WHERE {rc} ORDER BY "当前ARR" DESC NULLS LAST LIMIT 40""", rp)

    for r in top:
        r["客户名称"] = user.mask_customer_name(r["客户名称"])
        if not user.can_see_amount(r["当前ARR"]):
            r["masked"] = True
    rows, folded = fold_by_threshold(top, user, "当前ARR")

    total_arr = db.query_one(
        f"""SELECT COALESCE(SUM("当前ARR"),0) AS v FROM "V_客户360视图" WHERE {rc}""", rp)["v"]

    return ok({
        "period": p,
        "scope": user.scope_label,
        "totalArr": round(float(total_arr or 0), 2),
        "tiers": [{"tier": r["tier"], "customers": r["customers"],
                   "arr": round(float(r["arr"] or 0), 2),
                   "revenue": round(float(r["revenue"] or 0), 2)} for r in tiers],
        "health": [{"level": r["level"], "customers": r["customers"]} for r in health],
        "industries": [{"name": r["name"], "customers": r["customers"],
                        "arr": round(float(r["arr"] or 0), 2)} for r in industries],
        "channels": [{"name": r["name"], "customers": r["customers"]} for r in channels],
        "top": rows,
        "folded": folded,
    }, meta=common.meta(p))


@router.get("/renewal-calendar")
def renewal_calendar(months: int = Query(6, ge=1, le=12),
                     period: str | None = None,
                     user: UserContext = Depends(require("customer:view"))):
    """以数据期末（而非系统日期）为基准：演示数据停在 2025-12，用 CURRENT_DATE 会查不到。"""
    from datetime import date, timedelta
    p = common.resolve_period(period)
    y, m = int(p[:4]), int(p[5:7])
    base_y = y + (1 if m == 12 else 0)
    base = date(base_y, 1 if m == 12 else m + 1, 1)   # 数据期末次月 1 日
    rc, rp = _region_clause(user, "c.")
    rows = db.query(
        f"""SELECT s."订阅ID" AS contract_id, s."客户ID", c."客户名称", c."所在大区" AS region,
                   s."产品ID", s."订阅截止日期" AS end_date,
                   s."月经常性收入MRR" AS mrr, s."合同状态" AS status
            FROM "fact_subscription" s JOIN "dim_customer" c ON c."客户ID" = s."客户ID"
            WHERE s."合同状态" = '激活'
              AND s."订阅截止日期" BETWEEN %s AND (%s + (%s || ' month')::interval)::date
              AND {rc}
            ORDER BY s."订阅截止日期" LIMIT 300""", [base, base, months, *rp])
    out = []
    for r in rows:
        r["客户名称"] = user.mask_customer_name(r["客户名称"])
        r["end_date"] = r["end_date"].isoformat()
        r["mrr"] = round(float(r["mrr"] or 0), 2)
        r["arr"] = round(float(r["mrr"] or 0) * 12, 2)
        out.append(r)
    return ok({"months": months, "period": p, "count": len(out), "rows": out,
               "totalArr": round(sum(r["arr"] for r in out), 2)})


@router.get("/{customer_id}/360")
def customer_360(customer_id: str, user: UserContext = Depends(require("customer:view"))):
    row = db.query_one('SELECT * FROM "V_客户360视图" WHERE "客户ID" = %s', (customer_id,))
    if not row:
        raise ApiError(40401, "客户不存在")
    if user.regions is not None and row["所在大区"] not in user.regions:
        permissions.audit(user, "deny", "customer/360", {"customer": customer_id, "reason": "out of region"})
        raise ApiError(40302, f"该客户属于{row['所在大区']}，超出你的数据范围（{user.scope_label}）")
    if customer_id in user.deny_customers:
        raise ApiError(40302, "该客户在你的黑名单中")

    subs = db.query(
        """SELECT "订阅ID","产品ID","订阅起始日期","订阅截止日期","月经常性收入MRR","合同状态"
           FROM "fact_subscription" WHERE "客户ID" = %s ORDER BY "订阅起始日期" DESC LIMIT 10""",
        (customer_id,))
    tickets = db.query(
        """SELECT "工单ID","工单类型","紧急级别","创建日期","解决日期","状态"
           FROM "fact_support_ticket" WHERE "客户ID" = %s ORDER BY "创建日期" DESC LIMIT 10""",
        (customer_id,))
    monthly = db.query(
        """SELECT "月份","收入","成本","毛利率%" FROM "V_客户月度毛利"
           WHERE "客户ID" = %s ORDER BY "月份" DESC LIMIT 24""", (customer_id,))
    health = db.query(
        """SELECT "月份","健康度得分","健康度等级","NPS评分" FROM "V_客户健康度详情"
           WHERE "客户ID" = %s ORDER BY "月份" DESC LIMIT 12""", (customer_id,))

    row["客户名称"] = user.mask_customer_name(row["客户名称"])
    permissions.audit(user, "view", "customer/360", {"customer": customer_id})
    return ok({
        "customer": row,
        "contracts": [dict(r, 合同起始日期=r["订阅起始日期"].isoformat(),
                           订阅截止日期=r["订阅截止日期"].isoformat()) for r in subs],
        "tickets": [dict(r, 创建日期=r["创建日期"].isoformat(),
                         解决日期=r["解决日期"].isoformat() if r["解决日期"] else None) for r in tickets],
        "monthly": list(reversed(monthly)),
        "health": list(reversed(health)),
        "scope": user.scope_label,
        "amountMasked": user.field_mask.get("amount") == "hidden",
    }, meta=common.meta(common.latest_period()))
