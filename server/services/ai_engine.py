"""AI 分析：语义层 + 规则引擎（可插 LLM），六道闸门全部在服务端强制执行。

设计原则（开发文档 6.1 / 6.3）：
- 不做裸 Text-to-SQL：先把问题落到指标字典（meta_metric），只有命中的指标才允许生成 SQL；
- SQL 由服务端模板拼装，字段名来自白名单，用户输入只作为「值」进参数，从根本上避免注入；
- 每道闸门的结果随回答返回，前端可以把「拦了什么」展示出来；
- 未接入大模型时也能用（规则引擎），接入后仅替换 answer 的措辞，安全链路不变。
"""
from __future__ import annotations

import json
import re
from typing import Any

from .. import db
from ..config import settings
from ..permissions import UserContext
from ..response import ApiError
from . import common, llm

# 维度关键词 → 语义层计划（视图、分组列、金额表达式）
DIM_PLANS: dict[str, dict] = {
    "product_line": {"kw": ["产品线"], "view": '"V_产品月度收入毛利"', "col": '"产品线"'},
    "product": {"kw": ["产品", "哪个产品"], "view": '"V_产品月度收入毛利"', "col": '"产品名称"'},
    "region": {"kw": ["大区", "区域", "华东", "华南", "华北"], "view": '"V_大区月度收入"', "col": '"所在大区"'},
    "customer": {"kw": ["客户", "大客户"], "view": '"V_客户月度毛利"', "col": '"客户名称"'},
    "account_category": {"kw": ["科目类别", "费用类别"], "view": '"V_期间费用结构"', "col": '"科目类别"'},
    "account": {"kw": ["科目", "一级科目"], "view": '"V_期间费用结构"', "col": '"一级科目名称"'},
    "aging": {"kw": ["账龄"], "view": '"V_应收账龄结构"', "col": '"账龄桶"'},
    "cost_type": {"kw": ["成本类型", "托管成本", "客户成功成本", "技术支持成本"], "view": '"fact_cogs"', "col": '"成本类型"'},
    "service_type": {"kw": ["服务类型", "增值服务"], "view": '"fact_addon_service"', "col": '"服务类型"'},
    "dept": {"kw": ["部门"], "view": '"V_部门人力成本"', "col": '"部门"'},
    "month": {"kw": ["趋势", "每月", "各月", "按月"], "view": '"V_月度经营总览"', "col": '"月份"'},
}

_HAS_AGG = re.compile(r"\b(sum|avg|count|min|max)\s*\(", re.I)

# 预计算比率/均值列：视图里每行已是最终值（毛利率%、DSO、赢单率等），
# 分组时不能 SUM，只能把该列一并 GROUP BY（同组内值唯一时等价于取组内值）
_PRECOMPUTED = {"gross_margin", "customer_gm", "budget_exec", "collection_rate",
                "dso", "service_utilization", "sla_days", "win_rate",
                "health_score", "customer_ar"}

# 指标在某维度下的取数计划覆盖（默认用指标自身的视图与表达式）
METRIC_DIM_OVERRIDE: dict[tuple[str, str], tuple[str, str]] = {    ("revenue", "product"): ('"V_产品月度收入毛利"', 'SUM("订阅收入")'),
    ("revenue", "product_line"): ('"V_产品月度收入毛利"', 'SUM("订阅收入")'),
    ("subscription_revenue", "product"): ('"V_产品月度收入毛利"', 'SUM("订阅收入")'),
    ("subscription_revenue", "product_line"): ('"V_产品月度收入毛利"', 'SUM("订阅收入")'),
    ("gross_margin", "product"): ('"V_产品月度收入毛利"', 'ROUND(SUM("毛利")/NULLIF(SUM("订阅收入"),0)*100,2)'),
    ("gross_margin", "product_line"): ('"V_产品月度收入毛利"', 'ROUND(SUM("毛利")/NULLIF(SUM("订阅收入"),0)*100,2)'),
    ("revenue", "region"): ('"V_大区月度收入"', 'SUM("收入合计")'),
    ("subscription_revenue", "region"): ('"V_大区月度收入"', 'SUM("订阅收入")'),
    ("service_revenue", "region"): ('"V_大区月度收入"', 'SUM("服务收入")'),
    ("cogs", "cost_type"): ('"fact_cogs"', 'SUM("成本金额")'),
    ("revenue", "customer"): ('"V_客户月度毛利"', 'SUM("收入")'),
    ("ar_balance", "customer"): ('"V_客户月度毛利"', 'SUM("收入")'),
    ("customer_revenue", "customer"): ('"V_客户360视图"', 'SUM("累计确认收入")'),
    ("opex", "account_category"): ('"V_期间费用结构"', 'SUM("费用金额")'),
    ("opex", "account"): ('"V_期间费用结构"', 'SUM("费用金额")'),
    ("ar_balance", "aging"): ('"V_应收账龄结构"', 'SUM("应收余额")'),
    ("payroll", "dept"): ('"V_部门人力成本"', 'SUM("薪酬合计")'),
    ("pipeline", "region"): ('"V_销售漏斗"', 'SUM("成交金额合计")'),
    ("cloud_cost", "month"): ('"V_云资源成本"', 'SUM("账单金额")'),
}

PERIOD_SQL = {
    '"V_月度经营总览"': '"月份"',
    '"V_产品月度收入毛利"': '"月份"',
    '"V_大区月度收入"': '"月份"',
    '"V_客户月度毛利"': '"月份"',
    '"V_期间费用结构"': '"月份"',
    '"V_应收账龄结构"': '"月份"',
    '"fact_cogs"': '"成本月份"',
    '"fact_addon_service"': '"订单月份"',
    '"V_部门人力成本"': '"月份"',
    '"V_销售漏斗"': '"月份"',
    '"V_云资源成本"': '"月份"',
    '"V_客户360视图"': None,
}

SENSITIVE_KW = ["薪酬", "工资", "薪资", "个人", "身份证", "手机号", "全部客户", "所有客户", "导出"]

GATES = [
    ("G1", "身份与数据范围", "按角色 × 部门 × 职级注入范围谓词"),
    ("G2", "指标白名单", "问题必须命中指标字典中的指标"),
    ("G3", "时间范围", "单次查询不超过 36 个月"),
    ("G4", "行数与明细", "明细最多 200 行，按金额倒序"),
    ("G5", "敏感字段", "薪酬、个人信息、全量导出需更高权限"),
    ("G6", "只读与注入防护", "仅允许 SELECT，值走参数化"),
]


def _metrics() -> list[dict]:
    return db.query("SELECT * FROM app.meta_metric WHERE is_active")


def llm_intent(question: str) -> dict | None:
    """DeepSeek 意图解析（Data Agent L1）：只识别「指标 + 维度 + 期间」，不做任何计算。

    返回值经过严格白名单校验：metric_code 必须在指标字典内、dim 必须在维度计划内，
    任何异常（含 LLM 调用失败/返回不合法 JSON）一律返回 None，由规则引擎兜底。
    """
    if not llm.available():
        return None
    metrics = [{"code": m["code"], "name": m["name"],
                "alias": m["alias"] or "", "unit": m["unit"]} for m in _metrics()]
    sys_prompt = (
        "你是财务系统的语义解析器。从用户问题中识别意图并只输出 JSON 对象，"
        "禁止输出任何解释、禁止计算、禁止编造字典之外的编码。\n"
        f"指标字典（metric_code 只能从中选择）：{json.dumps(metrics, ensure_ascii=False)}\n"
        f"可用维度（dim 只能从中选择，问题未涉及维度时填 null）："
        f"{json.dumps(sorted(DIM_PLANS.keys()), ensure_ascii=False)}\n"
        f"当前期间：{common.latest_period()}\n"
        '输出格式：{"metric_code":"字典中的code或null","dim":"维度key或null",'
        '"period":"问题明确提到的 YYYY-MM 或 YYYY，未提到填 null",'
        '"grain":"month或year"}\n'
        "注意：问「率」类指标（毛利率/回款率等）时不要选成对应的金额类指标。"
    )
    try:
        raw = llm.chat(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": question}],
            temperature=0.1, json_mode=True)
        obj = json.loads(raw)
        code = obj.get("metric_code")
        valid_codes = {m["code"] for m in metrics}
        if not code or code not in valid_codes:
            return None
        dim = obj.get("dim")
        if dim not in DIM_PLANS:
            dim = None
        period = obj.get("period")
        if not (isinstance(period, str) and re.fullmatch(r"20\d{2}(-\d{2})?", period)):
            period = None
        grain = obj.get("grain") if obj.get("grain") in ("month", "year") else "month"
        return {"metric_code": code, "dim": dim, "period": period, "grain": grain}
    except Exception as e:  # noqa: BLE001  LLM 任何失败都降级到规则引擎（原因写入日志）
        print(f"[llm] 意图解析失败，回落规则引擎：{e}", flush=True)
        return None


def find_metric(question: str) -> dict | None:
    q = question.replace(" ", "")
    best: tuple[int, dict] | None = None
    for m in _metrics():
        names = [m["name"]] + [a for a in (m["alias"] or "").split(",") if a]
        for n in names:
            n = n.strip()
            if n and n in q:
                score = len(n)
                if best is None or score > best[0]:
                    best = (score, m)
    # 「毛利」会命中「毛利率」与「毛利额」，取更长者；若问句含「率」优先毛利率
    if best and "率" in q and best[1]["code"] == "gross_profit":
        gm = next((m for m in _metrics() if m["code"] == "gross_margin"), None)
        if gm:
            return gm
    return best[1] if best else None


def find_period(question: str) -> tuple[str, str] | None:
    m = re.search(r"(20\d{2})\s*[-年/]\s*(\d{1,2})", question)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}", "month"
    m = re.search(r"(20\d{2})\s*年", question)
    if m:
        return f"{int(m.group(1)):04d}", "year"
    if "上个月" in question or "上月" in question:
        return common.shift_period(common.latest_period(), -1), "month"
    if "去年" in question:
        p = common.shift_period(common.latest_period(), -12)
        return p[:4], "year"
    return None


def _dim_of(question: str) -> str | None:
    hits = []
    for key, plan in DIM_PLANS.items():
        for kw in plan["kw"]:
            if kw in question:
                hits.append((len(kw), key))
    if not hits:
        return None
    hits.sort(reverse=True)
    return hits[0][1]


def _period_clause(view: str, period: str, grain: str) -> tuple[str, list[Any]]:
    col = PERIOD_SQL.get(view)
    if not col:
        return "", []
    # 防御：LLM 偶发把「2025年各月趋势」解析成 期间=2025 + 月度粒度（不匹配会查出 0 行）。
    # 期间是纯 4 位年份时，无论声明粒度一律按年度前缀匹配。
    if grain == "year" or re.fullmatch(r"\d{4}", period or ""):
        return f"{col} LIKE %s", [period + "-%"]
    return f"{col} = %s", [period]


def _answer(metric: dict, period: str, rows: list[dict], dim: str | None, grain: str) -> str:
    unit = metric["unit"]
    if not rows:
        return f"{period} 期间没有查到「{metric['name']}」的数据，可能该期间尚未关账。"
    if len(rows) == 1 and "value" in rows[0]:
        v = rows[0]["value"]
        if unit == "%":
            return f"{period} 的{metric['name']}为 **{v:.2f}%**。口径：{metric['definition']}"
        return f"{period} 的{metric['name']}为 **{_cn_money(v)}**。口径：{metric['definition']}"
    top = rows[0]
    key = [k for k in top if k not in ("value", "pct")][0]
    desc = "、".join(
        f"{r[key]} {('%.2f%%' % r['value']) if unit == '%' else _cn_money(r['value'])}"
        for r in rows[:3]
    )
    return f"{period} 按{DIM_PLANS[dim]['col'].strip(chr(34)) if dim else '维度'}拆分，前三为：{desc}。"


def _cn_money(v: float) -> str:
    v = float(v)
    if abs(v) >= 1e8:
        return f"{v / 1e8:,.2f} 亿元"
    if abs(v) >= 1e4:
        return f"{v / 1e4:,.2f} 万元"
    return f"{v:,.2f} 元"


def ask(question: str, user: UserContext, session_id: str | None = None,
        period: str | None = None) -> dict:
    question = (question or "").strip()
    if len(question) < 2:
        raise ApiError(40001, "问题太短")

    gates = [{"code": c, "name": n, "note": d, "passed": True, "detail": ""} for c, n, d in GATES]

    # G5 敏感：薪酬与全量导出
    if any(k in question for k in SENSITIVE_KW):
        if "薪酬" in question or "工资" in question or "薪资" in question:
            if user.role not in ("cfo", "admin") or user.grade == "初级":
                gates[4].update(passed=False, detail=f"当前角色 {user.role_name} 无权访问薪酬明细")
                raise ApiError(40301, "无权限访问薪酬明细：该字段仅 CFO / 管理员可见")
        if ("全部客户" in question or "所有客户" in question) and user.regions is not None:
            gates[4].update(passed=False, detail="超出数据范围，已按大区收敛")
            gates[0].update(passed=True, detail=f"范围：{user.scope_label}")

    # 意图解析：优先 DeepSeek（只识别 指标/维度/期间，输出经白名单严格校验），
    # 失败或未配置时回落规则引擎——安全链路（六道闸门）完全不变。
    intent = llm_intent(question)
    if intent:
        metric = next((m for m in _metrics() if m["code"] == intent["metric_code"]), None)
        p = (intent["period"], intent["grain"]) if intent["period"] else None
        dim = intent["dim"]
        engine_label = f"DeepSeek {settings.llm_model} 意图解析 + 语义层取数"
        gates[1]["detail"] = f"LLM 命中指标 {intent['metric_code']}（白名单校验通过）"
        if dim is None:  # 维度关键词兜底（同样受白名单约束）
            dim = _dim_of(question)
    else:
        metric = find_metric(question)
        p = find_period(question)
        dim = _dim_of(question)
        engine_label = ("语义层规则引擎（DeepSeek 未命中，规则兜底）" if llm.available()
                        else "语义层规则引擎（未配置 DEEPSEEK_API_KEY）")
    if not metric:
        gates[1].update(passed=False, detail="未命中指标字典")
        raise ApiError(50002, "没听懂：这个问题没有对应到指标字典，请换个问法",
                       detail={"suggestions": ["2025年12月营业收入是多少", "各产品线毛利率",
                                               "2025年12月账龄分布", "期间费用按科目类别"]})

    grain = "month"
    if p:
        period, grain = p
    else:
        period, grain = common.resolve_period(period), "month"
    if grain == "year":
        check = period + "-12"
    else:
        check = period

    dim = _dim_of(question)
    view = metric["view_name"]
    amount_expr = metric["expr"]

    if dim:
        override = METRIC_DIM_OVERRIDE.get((metric["code"], dim))
        if override:
            view, amount_expr = override
        else:
            plan = DIM_PLANS[dim]
            # 维度与指标不在同一视图时，回退到指标默认视图（并在 meta 里说明）
            if plan["view"].strip('"') != metric["view_name"].strip('"'):
                dim = None

    where_sql, params = _period_clause(view, period, grain)
    where_parts = []
    if where_sql:
        where_parts.append(where_sql)
    # G1 数据范围
    if user.regions is not None:
        col = '"所在大区"' if view in ('"V_大区月度收入"', '"V_客户月度毛利"', '"V_应收账龄结构"',
                                     '"V_销售漏斗"', '"V_客户360视图"') else None
        if col:
            where_parts.append(f"{col} = ANY(%s)")
            params.append(user.regions)
            gates[0]["detail"] = f"按 {user.scope_label} 收敛"
    where = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    if dim:
        col = DIM_PLANS[dim]["col"]
        # 表达式三分类：已含聚合 → 原样；预计算比率/均值列 → 一并 GROUP BY（求和会失真）；
        # 普通加性度量 → 包 SUM（否则 GROUP BY 时 PostgreSQL 报"必须出现在 GROUP BY 中"）
        if _HAS_AGG.search(amount_expr):
            value_expr, group_extra = amount_expr, ""
        elif metric["code"] in _PRECOMPUTED:
            value_expr, group_extra = amount_expr, f", {amount_expr}"
        else:
            value_expr, group_extra = f"SUM({amount_expr})", ""
        sql = (f'SELECT {col} AS "维度", {value_expr} AS "值" FROM {view}{where} '
               f'GROUP BY {col}{group_extra} ORDER BY 2 DESC NULLS LAST LIMIT 50')
        rows = db.query(sql, params)
        out = [{"维度": r["维度"], "value": round(float(r["值"] or 0), 2)} for r in rows]
        total = sum(abs(r["value"]) for r in out) or 1
        for r in out:
            r["pct"] = round(abs(r["value"]) / total * 100, 2)
        data_rows = out
    else:
        sql = f"SELECT {amount_expr} AS value FROM {view}{where}"
        row = db.query_one(sql, params)
        val = float(row["value"] or 0) if row else 0.0
        data_rows = [{"value": round(val, 2)}]

    # G3 时间范围：年度查询跨度 12 个月，符合 ≤36
    gates[2]["detail"] = "12 个月" if grain == "year" else "1 个月"
    gates[3]["detail"] = f"{len(data_rows)} 行"
    if len(data_rows) > 200:
        data_rows = data_rows[:200]
        gates[3]["detail"] = "已截断至 200 行"

    metric_scope = "全公司" if user.regions is None else user.scope_label
    answer = _answer(metric, period if grain == "month" else period + " 年", data_rows, dim, grain)

    meta_out = {
        "metric": metric["name"],
        "metricCode": metric["code"],
        "metricVersion": metric["version"],
        "definition": metric["definition"],
        "source": view.strip('"'),
        "rowCount": len(data_rows),
        "scope": metric_scope,
        "grain": grain,
        "engine": engine_label,
    }

    # 会话留痕
    sid = session_id or f"s_{user.id}_{common.data_version().replace('-', '')}"
    db.execute(
        """INSERT INTO app.ai_session(id, user_id, title) VALUES (%s,%s,%s)
           ON CONFLICT (id) DO NOTHING""",
        (sid, user.id, question[:60]),
    )
    db.execute(
        """INSERT INTO app.ai_message(session_id, role, content, meta)
           VALUES (%s,'user',%s,%s)""",
        (sid, question, db.psycopg2.extras.Json({})),
    )
    saved = db.execute_returning(
        """INSERT INTO app.ai_message(session_id, role, content, meta)
           VALUES (%s,'assistant',%s,%s) RETURNING id""",
        (sid, answer, db.psycopg2.extras.Json({"sql": sql, "meta": meta_out, "gates": gates})),
    )

    return {
        "sessionId": sid,
        "question": question,
        "thinking": f"意图解析：{'DeepSeek' if intent else '规则引擎'}；"
                    f"识别指标：{metric['name']}；维度：{DIM_PLANS[dim]['col'].strip(chr(34)) if dim else '无'}；"
                    f"期间：{period}（{('年度' if grain == 'year' else '月度')}）",
        "sql": sql,
        "answer": answer,
        "rows": data_rows,
        "chart": {"type": "bar" if len(data_rows) > 1 else "kpi",
                  "dim": DIM_PLANS[dim]["col"].strip('"') if dim else None},
        "gates": gates,
        "meta": meta_out,
        "messageId": saved["id"] if saved else None,
    }


def eval_cases() -> list[dict]:
    return db.query("SELECT * FROM app.ai_eval_case ORDER BY id")


def history(session_id: str, user: UserContext) -> list[dict]:
    rows = db.query(
        """SELECT role, content, meta, created_at, feedback FROM app.ai_message
           WHERE session_id = %s ORDER BY id""", (session_id,))
    return rows
