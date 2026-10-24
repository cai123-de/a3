"""成本与费用：COGS 结构、云成本、期间费用结构、部门人力。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import db
from ..deps import require
from ..permissions import UserContext
from ..response import ok
from ..services import common

router = APIRouter(prefix="/cost", tags=["成本与费用"])


@router.get("/summary")
def summary(period: str | None = None, user: UserContext = Depends(require("cost:view"))):
    p = common.resolve_period(period)
    rc, rp = user.region_sql('"所在大区"')

    cogs_types = db.query(
        """SELECT "成本类型" AS name, SUM("成本金额") AS value FROM "fact_cogs"
           WHERE "成本月份" = %s GROUP BY 1 ORDER BY 2 DESC""", (p,))
    cogs_products = db.query(
        """SELECT "产品名称" AS name, "产品线" AS line, "营业成本" AS cost, "订阅收入" AS revenue,
                  "毛利率%" AS margin FROM "V_产品月度收入毛利"
           WHERE "月份" = %s ORDER BY "营业成本" DESC LIMIT 10""", (p,))
    expense_cats = db.query(
        """SELECT "科目类别" AS category, SUM("费用金额") AS amount, SUM("凭证数")::int AS vouchers
           FROM "V_期间费用结构" WHERE "月份" = %s GROUP BY 1 ORDER BY 2 DESC""", (p,))
    expense_accounts = db.query(
        """SELECT "一级科目名称" AS name, "科目类别" AS category, SUM("费用金额") AS amount
           FROM "V_期间费用结构" WHERE "月份" = %s GROUP BY 1,2 ORDER BY 3 DESC LIMIT 16""", (p,))
    cloud = db.query(
        """SELECT "服务类别" AS service, "云厂商" AS vendor, SUM("账单金额") AS amount
           FROM "V_云资源成本" WHERE "月份" = %s GROUP BY 1,2 ORDER BY 3 DESC""", (p,))
    dept = db.query(
        """SELECT "部门" AS dept, SUM("薪酬合计") AS payroll, SUM("发薪人数")::int AS heads
           FROM "V_部门人力成本" WHERE "月份" = %s GROUP BY 1 ORDER BY 2 DESC""", (p,))
    unpaid = db.query_one(
        """SELECT COALESCE(SUM("费用金额") FILTER (WHERE "付款状态" <> '已付款'),0) AS v
           FROM "V_期间费用结构" WHERE "月份" = %s""", (p,))

    total_cogs = sum(float(r["value"] or 0) for r in cogs_types)
    total_exp = sum(float(r["amount"] or 0) for r in expense_cats)

    return ok({
        "period": p,
        "cogs": {
            "total": round(total_cogs, 2),
            "types": [{"name": r["name"], "value": round(float(r["value"] or 0), 2),
                       "ratio": round(float(r["value"] or 0) / total_cogs * 100, 2) if total_cogs else 0}
                      for r in cogs_types],
            "products": [{"name": r["name"], "line": r["line"],
                          "cost": round(float(r["cost"] or 0), 2),
                          "revenue": round(float(r["revenue"] or 0), 2),
                          "margin": round(float(r["margin"] or 0), 2)} for r in cogs_products],
        },
        "expense": {
            "total": round(total_exp, 2),
            "categories": [{"category": r["category"], "amount": round(float(r["amount"] or 0), 2),
                            "vouchers": r["vouchers"],
                            "ratio": round(float(r["amount"] or 0) / total_exp * 100, 2) if total_exp else 0}
                           for r in expense_cats],
            "accounts": [{"name": r["name"], "category": r["category"],
                          "amount": round(float(r["amount"] or 0), 2)} for r in expense_accounts],
            "unpaid": round(float(unpaid["v"] or 0), 2),
        },
        "cloud": [{"service": r["service"], "vendor": r["vendor"],
                   "amount": round(float(r["amount"] or 0), 2)} for r in cloud],
        "payroll": [{"dept": r["dept"], "payroll": round(float(r["payroll"] or 0), 2),
                     "heads": r["heads"]} for r in dept],
        "note": "期间费用与订阅 COGS 是两套体系，本页分别展示，不做相加。",
        "scope": user.scope_label,
    }, meta=common.meta(p))


@router.get("/cloud-allocation")
def cloud_allocation(period: str | None = None,
                     user: UserContext = Depends(require("cost:view"))):
    p = common.resolve_period(period)
    rows = db.query(
        """SELECT "月份" AS month, "服务类别" AS service, "云厂商" AS vendor,
                  "账单金额" AS amount, "上月账单金额" AS prev,
                  "环比差额" AS delta, "云服务数"::int AS services
           FROM "V_云资源成本" WHERE "月份" = %s ORDER BY "账单金额" DESC""", (p,))
    total = sum(float(r["amount"] or 0) for r in rows)
    return ok({
        "period": p,
        "rows": [{"month": r["month"], "service": r["service"], "vendor": r["vendor"],
                  "amount": round(float(r["amount"] or 0), 2),
                  "prev": round(float(r["prev"] or 0), 2),
                  "delta": round(float(r["delta"] or 0), 2),
                  "services": r["services"],
                  "ratio": round(float(r["amount"] or 0) / total * 100, 2) if total else 0} for r in rows],
        "total": round(total, 2),
    }, meta=common.meta(p))
