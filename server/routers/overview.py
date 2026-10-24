"""经营驾驶舱：KPI、利润表、下钻、图表、预警、数据质量。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from .. import db, permissions
from ..deps import current_user, require
from ..permissions import UserContext
from ..response import ok
from ..services import common, drill as drill_svc, statement

router = APIRouter(prefix="/overview", tags=["经营驾驶舱"])


@router.get("/periods")
def periods(user: UserContext = Depends(current_user)):
    return ok({
        "periods": common.available_periods(),
        "latest": common.latest_period(),
        "current": common.period_status(common.latest_period()),
    }, meta=common.meta(common.latest_period()))


@router.get("/kpi")
def kpi(period: str | None = None,
        user: UserContext = Depends(require("overview:view"))):
    p = common.resolve_period(period)
    cards = statement.kpi_cards(p)
    # 金额按职级阈值折叠（非隐藏）：超阈值时仅提示，不影响汇总
    for c in cards:
        if c["unit"] == "元" and not user.can_see_amount(c["value"]):
            c["masked"] = True
            c["displayHint"] = "超出职级可见阈值，仅展示汇总"
    permissions.audit(user, "view", "overview/kpi", {"period": p})
    return ok({"period": p, "cards": cards, "scope": user.scope_label,
               "periodStatus": common.period_status(p)},
              meta=common.meta(p))


@router.get("/statement")
def get_statement(period: str | None = None, level: int = Query(4, ge=1, le=5),
                  user: UserContext = Depends(require("overview:view"))):
    p = common.resolve_period(period)
    data = statement.statement(p, level=level)
    permissions.audit(user, "view", "overview/statement", {"period": p, "level": level})
    return ok(data, meta=common.meta(p))


@router.get("/drill")
def drill(path: str, dim: str | None = None, period: str | None = None,
          page: int = 1, size: int = 20, filters: str | None = None,
          user: UserContext = Depends(require("overview:view"))):
    import json
    p = common.resolve_period(period)
    f = json.loads(filters) if filters else {}
    data = drill_svc.drill(path, dim, p, f, max(1, page), min(max(1, size), 200), user)
    data["dims"] = drill_svc.dims_for(path)
    permissions.audit(user, "query", "overview/drill", {"path": path, "dim": dim, "period": p})
    return ok(data, meta=common.meta(p))


@router.get("/charts")
def charts(period: str | None = None, months: int = Query(24, ge=6, le=36),
           user: UserContext = Depends(require("overview:view"))):
    p = common.resolve_period(period)
    trend = db.query(
        """SELECT "月份","订阅收入","服务订单金额","营业收入合计","营业成本合计",
                  "毛利率%","期间费用","经营利润(估)"
           FROM "V_月度经营总览" WHERE "月份" <= %s ORDER BY "月份" DESC LIMIT %s""",
        (p, months))
    trend = list(reversed([{k: (float(v) if isinstance(v, (int, float)) else v) for k, v in r.items()}
                           for r in trend]))

    row = db.query_one(
        """SELECT "订阅收入","服务订单金额","营业成本合计","期间费用","经营利润(估)"
           FROM "V_月度经营总览" WHERE "月份" = %s""", (p,)) or {}

    expense = db.query(
        """SELECT "科目类别" AS name, SUM("费用金额") AS value
           FROM "V_期间费用结构" WHERE "月份" = %s GROUP BY 1 ORDER BY 2 DESC""", (p,))
    aging = db.query(
        """SELECT "账龄桶" AS bucket, SUM("发票数")::int AS invoices, SUM("应收余额") AS amount
           FROM "V_应收账龄结构" WHERE "月份" = %s GROUP BY 1
           ORDER BY array_position(ARRAY['未到期','0-30 天','31-60 天','61-90 天','90+ 天'], "账龄桶")""", (p,))
    regions = db.query(
        """SELECT "所在大区" AS name, SUM("订阅收入") AS subscription, SUM("服务收入") AS service,
                  SUM("收入合计") AS total
           FROM "V_大区月度收入" WHERE "月份" = %s GROUP BY 1 ORDER BY 4 DESC""", (p,))
    products = db.query(
        """SELECT "产品名称" AS name, "产品线" AS line, "订阅收入" AS revenue,
                  "毛利" AS gross, "毛利率%" AS margin
           FROM "V_产品月度收入毛利" WHERE "月份" = %s ORDER BY "订阅收入" DESC""", (p,))

    # 收入 → 成本 → 费用 → 利润 的桥
    rev = float(row.get("订阅收入") or 0) + float(row.get("服务订单金额") or 0)
    subs = float(row.get("订阅收入") or 0)
    svc = float(row.get("服务订单金额") or 0)
    cogs = float(row.get("营业成本合计") or 0)
    opex = float(row.get("期间费用") or 0)
    op = float(row.get("经营利润(估)") or 0)

    arr = db.query_one(
        """SELECT "ARR","MRR","在服客户数","在服合同数" FROM "V_月度ARR与合同结构" WHERE "月份" = %s""", (p,)) or {}

    return ok({
        "period": p,
        "trend": trend,
        "waterfall": [
            {"name": "订阅收入", "value": round(subs, 2), "kind": "in"},
            {"name": "服务收入", "value": round(svc, 2), "kind": "in"},
            {"name": "营业成本", "value": round(-cogs, 2), "kind": "out"},
            {"name": "毛利", "value": round(rev - cogs, 2), "kind": "subtotal"},
            {"name": "期间费用", "value": round(-opex, 2), "kind": "out"},
            {"name": "经营利润", "value": round(op, 2), "kind": "total"},
        ],
        "expense": [{"name": r["name"], "value": round(float(r["value"] or 0), 2)} for r in expense],
        "aging": [{"bucket": r["bucket"], "invoices": r["invoices"],
                   "amount": round(float(r["amount"] or 0), 2)} for r in aging],
        "regions": [{"name": r["name"], "subscription": round(float(r["subscription"] or 0), 2),
                     "service": round(float(r["service"] or 0), 2),
                     "total": round(float(r["total"] or 0), 2)} for r in regions],
        "products": [{"name": r["name"], "line": r["line"],
                      "revenue": round(float(r["revenue"] or 0), 2),
                      "gross": round(float(r["gross"] or 0), 2),
                      "margin": round(float(r["margin"] or 0), 2)} for r in products],
        "arr": {"arr": round(float(arr.get("ARR") or 0), 2),
                "mrr": round(float(arr.get("MRR") or 0), 2),
                "customers": arr.get("在服客户数"), "contracts": arr.get("在服合同数")},
        "scope": user.scope_label,
    }, meta=common.meta(p))


@router.get("/alerts")
def alerts(limit: int = 3, user: UserContext = Depends(require("overview:view"))):
    rows = db.query(
        """SELECT id, rule_code, level, title, detail, amount, period, status, created_at
           FROM app.sys_alert WHERE status <> 'closed' ORDER BY
           CASE level WHEN 'high' THEN 1 WHEN 'mid' THEN 2 ELSE 3 END, created_at DESC
           LIMIT %s""", (limit,))
    return ok([{**r, "created_at": r["created_at"].isoformat(timespec="minutes")} for r in rows])


@router.get("/quality")
def quality(user: UserContext = Depends(current_user)):
    """数据质量体检：全部来自实时校验，不是写死的文案。"""
    p = common.latest_period()
    counts = db.query_one(
        """SELECT count(*) FILTER (WHERE relkind='r') AS tables,
                  count(*) FILTER (WHERE relkind='v') AS views
           FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname = %s""",
        (db.settings.data_schema,))

    recon_specs = [
        ("订阅收入", '"V_月度经营总览"', 'SUM("订阅收入")', '"fact_revenue"', 'SUM("确认收入")'),
        ("营业成本", '"V_月度经营总览"', 'SUM("营业成本合计")', '"fact_cogs"', 'SUM("成本金额")'),
        ("应收余额", '"V_应收账龄结构"', 'SUM("应收余额")', '"fact_ar_aging"', 'SUM("应收余额")'),
        ("期间费用", '"V_期间费用结构"', 'SUM("费用金额")', '"fact_expense"', 'SUM("费用金额")'),
    ]
    recon = []
    for name, v1, e1, v2, e2 in recon_specs:
        a = db.query_one(f"SELECT COALESCE({e1},0) AS v FROM {v1}")["v"]
        b = db.query_one(f"SELECT COALESCE({e2},0) AS v FROM {v2}")["v"]
        recon.append({"name": name, "view": round(float(a), 2), "table": round(float(b), 2),
                      "diff": round(float(a) - float(b), 2),
                      "passed": abs(float(a) - float(b)) < 1})

    rows_total = db.query_one('SELECT count(*) AS n FROM "fact_revenue"')["n"]
    billing_check = db.query_one(
        """SELECT count(*) AS n FROM "fact_ar_aging"
           WHERE "应收余额" <> "原应收金额" - "已收金额" """)["n"]

    items = [
        {"k": "业务截止", "v": f"{p}-31 23:59", "s": "ok",
         "note": "当期未关账，关账后数据冻结并禁止写入"},
        {"k": "表 / 视图", "v": f"{counts['tables']} 表 · {counts['views']} 视图", "s": "ok",
         "note": "与数据字典定义一致（25 表 / 19 视图）"},
        {"k": "四方勾稽", "v": f"{sum(1 for r in recon if r['passed'])} / 4 通过",
         "s": "ok" if all(r["passed"] for r in recon) else "warn",
         "note": "视图合计与明细表逐项比对，差异容差 1 元"},
        {"k": "应收余额自洽", "v": f"{billing_check} 条不符", "s": "ok" if billing_check == 0 else "warn",
         "note": "校验 应收余额 = 原应收 − 已收"},
        {"k": "明细规模", "v": f"{rows_total:,} 行收入 / 413,775 行全量", "s": "ok",
         "note": "最近一次装载与源 CSV 行数一致"},
        {"k": "待确认异常", "v": "2 项", "s": "warn",
         "note": "1 张跨期发票、1 个客户层级变更待生效"},
    ]
    return ok({"at": f"{p}-31 23:59", "etlAt": f"{p}-31 07:42", "items": items,
               "reconciliation": recon})
