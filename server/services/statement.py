"""利润表（管理会计口径）树形结构。

数据全部来自 19 个视图与 25 张明细表，不含任何硬编码金额；
每一级都做「子项合计 = 父项」校验，校验结果随接口返回（checkPassed）。
"""
from __future__ import annotations

from typing import Any

from .. import db
from . import common


def _money(v: Any) -> float:
    return round(float(v or 0), 2)


def _month_row(period: str) -> dict:
    row = db.query_one(
        """SELECT "订阅收入","服务订单金额","营业收入合计","营业成本合计",
                  "托管成本","客户成功成本","技术支持成本","毛利","毛利率%",
                  "期间费用","经营利润(估)","开票金额","收款金额",
                  "期末应收余额","逾期应收余额","DSO天数(按30天)","新签合同数"
           FROM "V_月度经营总览" WHERE "月份" = %s""",
        (period,),
    )
    return row or {}


def _node(key: str, label: str, value: float, level: int, *, note: str = "",
          drill: dict | None = None, children: list | None = None,
          sign: int = 1) -> dict:
    return {
        "key": key,
        "label": label,
        "value": round(value, 2) if sign > 0 else round(-value, 2),
        "level": level,
        "note": note,
        "drill": drill,
        "children": children or [],
        "hasChild": bool(children),
    }


def statement(period: str, level: int = 4) -> dict:
    cur = _month_row(period)
    revenue = _money(cur.get("营业收入合计"))
    cogs = _money(cur.get("营业成本合计"))
    gross = _money(cur.get("毛利"))
    opex = _money(cur.get("期间费用"))
    op = _money(cur.get("经营利润(估)"))

    # ---- 订阅收入 → 产品 ----
    products = db.query(
        """SELECT "产品ID","产品名称","产品线", SUM("订阅收入") AS amt
           FROM "V_产品月度收入毛利" WHERE "月份" = %s
           GROUP BY 1,2,3 HAVING SUM("订阅收入") <> 0 ORDER BY 4 DESC""",
        (period,),
    )
    product_children = [
        _node(f"rev.sub.{r['产品ID']}", r["产品名称"], _money(r["amt"]), 3,
              note=r["产品线"], drill={"path": "revenue.subscription", "dim": "customer",
                                      "filters": {"产品ID": r["产品ID"]}})
        for r in products
    ]

    # ---- 服务收入 → 服务类型 ----
    services = db.query(
        """SELECT p."产品名称" AS name, SUM(s."订单金额") AS amt
           FROM "fact_addon_service" s JOIN "dim_product" p ON p."产品ID" = s."产品ID"
           WHERE to_char(s."订单日期",'YYYY-MM') = %s
           GROUP BY 1 ORDER BY 2 DESC""",
        (period,),
    )
    service_children = [
        _node(f"rev.svc.{r['name']}", r["name"], _money(r["amt"]), 3,
              note="增值服务订单", drill={"path": "revenue.service", "dim": "product"})
        for r in services
    ]

    sub_total = _money(cur.get("订阅收入"))
    svc_total = _money(cur.get("服务订单金额"))
    if level >= 3:
        rev_children = [
            _node("revenue.subscription", "订阅收入", sub_total, 2,
                  note="按服务期直线摊销", drill={"path": "revenue.subscription", "dim": "product"},
                  children=product_children),
            _node("revenue.service", "服务订单收入", svc_total, 2,
                  note="下单口径，未按周期分摊", drill={"path": "revenue.service", "dim": "product"},
                  children=service_children),
        ]
    else:
        rev_children = []

    # ---- 营业成本 → 三类 ----
    cost_types = db.query(
        """SELECT "成本类型", SUM("成本金额") AS amt FROM "fact_cogs"
           WHERE "成本月份" = %s GROUP BY 1 ORDER BY 2 DESC""",
        (period,),
    )
    cost_children = [
        _node(f"cogs.{r['成本类型']}", r["成本类型"], _money(r["amt"]), 3,
              drill={"path": "cogs", "dim": "product"})
        for r in cost_types
    ]

    # ---- 期间费用 → 科目类别 → 一级科目 ----
    cats = db.query(
        """SELECT "科目类别", SUM("费用金额") AS amt FROM "V_期间费用结构"
           WHERE "月份" = %s GROUP BY 1 ORDER BY 2 DESC""",
        (period,),
    )
    cat_nodes = []
    for c in cats:
        subs = db.query(
            """SELECT "一级科目名称", SUM("费用金额") AS amt FROM "V_期间费用结构"
               WHERE "月份" = %s AND "科目类别" = %s GROUP BY 1 ORDER BY 2 DESC""",
            (period, c["科目类别"]),
        )
        cat_nodes.append(
            _node(f"opex.{c['科目类别']}", c["科目类别"], _money(c["amt"]), 3,
                  drill={"path": "expense", "dim": "account", "filters": {"科目类别": c["科目类别"]}},
                  children=[
                      _node(f"opex.{c['科目类别']}.{s['一级科目名称']}", s["一级科目名称"],
                            _money(s["amt"]), 4, drill={"path": "expense", "dim": "account"})
                      for s in subs
                  ])
        )

    roots = [
        _node("revenue", "营业收入", revenue, 1,
              note="订阅摊销 + 服务订单", drill={"path": "revenue", "dim": "month"},
              children=rev_children),
        _node("cogs", "营业成本", cogs, 2, note="仅订阅 COGS，不含期间费用",
              drill={"path": "cogs", "dim": "cost_type"}, children=cost_children),
        _node("gross", "毛利", gross, 2, note="营业收入 − 营业成本"),
        _node("opex", "期间费用", opex, 2, note="与 COGS 是两套体系，不可相加",
              drill={"path": "expense", "dim": "account_category"}, children=cat_nodes),
        _node("op", "经营利润(估)", op, 2, note="毛利 − 期间费用，仅供趋势观察"),
    ]

    def check(node: dict) -> tuple[bool, float]:
        kids = node["children"]
        if not kids:
            return True, node["value"]
        ok = True
        total = 0.0
        for k in kids:
            k_ok, k_sum = check(k)
            ok = ok and k_ok
            total += k_sum
        if abs(total - node["value"]) > max(1.0, abs(node["value"]) * 0.005):
            ok = False
            node["checkDiff"] = round(node["value"] - total, 2)
        return ok, node["value"]

    checks = [check(r)[0] for r in roots]
    return {
        "period": period,
        "rows": roots,
        "currency": "元",
        "summary": {
            "revenue": revenue,
            "grossProfit": gross,
            "grossMargin": _money(cur.get("毛利率%")),
            "opex": opex,
            "opProfit": op,
            "cogs": cogs,
            "billing": _money(cur.get("开票金额")),
            "collection": _money(cur.get("收款金额")),
            "arBalance": _money(cur.get("期末应收余额")),
            "arOverdue": _money(cur.get("逾期应收余额")),
            "dso": _money(cur.get("DSO天数(按30天)")),
        },
        "checkPassed": all(checks),
        "level": level,
    }


def kpi_cards(period: str) -> list[dict]:
    """8 个核心 KPI，含环比 / 同比 / 24 个月迷你走势。"""
    cur = _month_row(period)
    prev = _month_row(common.shift_period(period, -1))
    yoy = _month_row(common.shift_period(period, -12))

    arr_row = db.query_one(
        """SELECT "ARR","MRR","在服客户数","在服合同数" FROM "V_月度ARR与合同结构"
           WHERE "月份" = %s""", (period,))
    arr_prev = db.query_one(
        """SELECT "ARR" FROM "V_月度ARR与合同结构" WHERE "月份" = %s""",
        (common.shift_period(period, -12),))

    metrics = {r["code"]: r for r in db.query("SELECT * FROM app.meta_metric")}

    trend_rows = db.query(
        """SELECT "月份","订阅收入","毛利率%","经营利润(估)","期末应收余额","逾期应收余额",
                  "营业收入合计","收款金额","新签合同数"
           FROM "V_月度经营总览" WHERE "月份" <= %s ORDER BY "月份" DESC LIMIT 24""",
        (period,),
    )
    trend = list(reversed(trend_rows))

    def series(key: str) -> list[float]:
        return [_money(r.get(key)) for r in trend]

    def card(key: str, name: str, metric: str, value: float, unit: str,
             cur_v: float, prev_v: float, yoy_v: float, spark: list[float],
             note: str = "") -> dict:
        def delta(a: float, b: float):
            if b in (0, None):
                return None
            if a == 0 or b == 0:
                return None
            if (a > 0) != (b > 0):
                return None        # 扭亏 / 转亏：百分比无意义，由前端显示标签
            if abs(b) < abs(a) * 0.01:
                return None        # 基数过小（同比超百倍），百分比同样无意义
            return round((a - b) / abs(b) * 100, 2)
        m = metrics.get(metric, {})
        return {
            "key": key,
            "name": name,
            "value": round(value, 2),
            "unit": unit,
            "metric": metric,
            "definition": m.get("definition", note),
            "metricVersion": m.get("version", "v1.0"),
            "mom": delta(cur_v, prev_v),
            "yoy": delta(cur_v, yoy_v),
            "spark": spark,
            "note": note,
        }

    return [
        card("rev", "营业收入", "revenue", _money(cur.get("营业收入合计")), "元",
             _money(cur.get("营业收入合计")), _money(prev.get("营业收入合计")),
             _money(yoy.get("营业收入合计")), series("营业收入合计")),
        card("gm", "毛利率", "gross_margin", _money(cur.get("毛利率%")), "%",
             _money(cur.get("毛利率%")), _money(prev.get("毛利率%")),
             _money(yoy.get("毛利率%")), series("毛利率%"), "毛利 ÷ 营业收入"),
        card("op", "经营利润", "op_profit", _money(cur.get("经营利润(估)")), "元",
             _money(cur.get("经营利润(估)")), _money(prev.get("经营利润(估)")),
             _money(yoy.get("经营利润(估)")), series("经营利润(估)"), "毛利 − 期间费用（估算）"),
        card("arr", "ARR", "arr", _money(arr_row and arr_row.get("ARR")), "元",
             _money(arr_row and arr_row.get("ARR")), _money(arr_prev and arr_prev.get("ARR")),
             _money(arr_prev and arr_prev.get("ARR")), series("订阅收入"), "月末在服合同 MRR × 12"),
        card("ar", "期末应收", "ar_balance", _money(cur.get("期末应收余额")), "元",
             _money(cur.get("期末应收余额")), _money(prev.get("期末应收余额")),
             _money(yoy.get("期末应收余额")), series("期末应收余额")),
        card("od", "逾期应收", "ar_overdue", _money(cur.get("逾期应收余额")), "元",
             _money(cur.get("逾期应收余额")), _money(prev.get("逾期应收余额")),
             _money(yoy.get("逾期应收余额")), series("逾期应收余额"), "已过应收日仍未收回"),
        card("col", "本月回款", "collection", _money(cur.get("收款金额")), "元",
             _money(cur.get("收款金额")), _money(prev.get("收款金额")),
             _money(yoy.get("收款金额")), series("收款金额")),
        card("new", "新签合同", "new_contracts", _money(cur.get("新签合同数")), "个",
             _money(cur.get("新签合同数")), _money(prev.get("新签合同数")),
             _money(yoy.get("新签合同数")), series("新签合同数")),
    ]
