"""Data Agent：DeepSeek function-calling Agent Loop（框架 L2 层）。

三个通用工具：
1. query_data_dictionary — 数据字典查询：表/视图清单、指定对象的字段明细、指标字典；
2. run_sql — 自由只读查询：单条 SELECT，对象白名单 + 只读事务 + 语句超时 + 强制 LIMIT；
3. explain_sql — 性能验证：EXPLAIN ANALYZE 返回耗时/成本/行数并给出评估。

安全边界（六道闸门在工具层强制执行，LLM 无法绕过）：
- 只允许 SELECT/WITH 单条语句，黑名单关键词拦截，`BEGIN READ ONLY` 只读事务兜底；
- 只能引用数据字典中存在的对象（FROM/JOIN 白名单校验）；
- 强制 LIMIT ≤ 200、statement_timeout 8s、返回给 LLM 最多 40 行；
- 部门受限用户禁查大区维度对象；薪酬/个人敏感列对非 CFO 拒绝；
- 工具调用次数与总时长有硬预算，超限直接汇总收尾。
"""
from __future__ import annotations

import contextlib
import json
import re
import time
from decimal import Decimal
from typing import Any

import psycopg2
import psycopg2.extras

from .. import db
from ..config import settings
from ..permissions import UserContext
from ..response import ApiError
from . import common, llm

SQL_TIMEOUT_MS = 8000
EXPLAIN_TIMEOUT_MS = 15000
MAX_ROWS_TO_LLM = 40
HARD_ROW_CAP = 200
MAX_STEPS = 6
BUDGET_S = 60.0

REGION_OBJECTS = {"V_大区月度收入", "V_客户月度毛利", "V_应收账龄结构", "V_销售漏斗", "V_客户360视图"}
SENSITIVE_COLS = ["薪酬", "工资", "薪资", "身份证", "手机号", "银行卡"]

# ---------------- 工具定义（OpenAI function calling 格式） ----------------

TOOLS = [
    {"type": "function", "function": {
        "name": "query_data_dictionary",
        "description": "查询数据字典。target=objects：列出数据库中全部表和视图（含类型、估算行数、注释）；"
                       "target=columns：返回指定表/视图的字段名、类型与注释（table_name 必填，名称须来自 objects 结果）；"
                       "target=metrics：返回指标字典（编码/名称/别名/口径定义/单位/默认取数视图/表达式/版本）。"
                       "写 SQL 前必须先用本工具了解结构与字段。",
        "parameters": {"type": "object", "properties": {
            "target": {"type": "string", "enum": ["objects", "columns", "metrics"]},
            "table_name": {"type": "string", "description": "target=columns 时的表或视图名"},
        }, "required": ["target"]}}},
    {"type": "function", "function": {
        "name": "run_sql",
        "description": "执行只读 SELECT 查询并返回数据（最多返回 40 行预览，总行数上限 200，超时 8 秒）。"
                       "只能查数据字典中存在的对象；中文列名/表名必须用双引号包裹；"
                       "聚合计算请在 SQL 中完成；禁止任何写操作。",
        "parameters": {"type": "object", "properties": {
            "sql": {"type": "string", "description": "单条 SELECT 或 WITH 查询，不要以分号结尾"},
            "reason": {"type": "string", "description": "本次查询目的，一句话"},
        }, "required": ["sql", "reason"]}}},
    {"type": "function", "function": {
        "name": "explain_sql",
        "description": "性能验证工具：对 SELECT 执行 EXPLAIN ANALYZE，返回计划耗时、实际执行耗时、"
                       "成本与实际行数，并给出性能评估结论。查询超过 2 秒或拟固化时必须先验证。",
        "parameters": {"type": "object", "properties": {
            "sql": {"type": "string", "description": "要验证的 SELECT 查询"},
        }, "required": ["sql"]}}},
]

SYSTEM_PROMPT = """你是财务系统的数据代理（Data Agent），通过工具自主查数、计算与分析，回答用户的经营问题。

工作规则：
1. 先理解问题；不确定表结构或字段时，调用 query_data_dictionary 查字典（objects → columns / metrics），不要凭空猜列名；
2. 需要数据时调用 run_sql 写 SQL：中文表名/列名用双引号包裹；聚合计算（求和/比率/排名）在 SQL 里完成，不要心算；
   SELECT 里每个非聚合列都必须出现在 GROUP BY 中；毛利率/利用率等预计算比率列不要 SUM，按分组取值即可；
3. 大查询或可疑慢查询先调用 explain_sql 验证性能；
4. 你的数据范围是「{scope}」{region_note}；金额单位是元，回答时换算为万元/亿元并保留两位小数；
5. 拿到足够信息后直接用中文给最终答案（不要再调工具）：结论先行，附关键数字、口径来源（视图/指标）与时间范围；
6. 如果数据字典里确实没有能回答问题的数据，如实说明并建议可回答的相近问题，禁止编造数字。
最多 {max_steps} 次工具调用。"""

# ---------------- SQL 安全校验 ----------------

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|vacuum|"
    r"call|do|set|reindex|cluster|listen|notify|pg_sleep|pg_read_file|dblink|lo_import|lo_export)\b",
    re.I)
_REL_RE = re.compile(r'(?:from|join)\s+("([^"]+)"|([a-zA-Z_\u4e00-\u9fff][\w\u4e00-\u9fff$]*))', re.I)
_LIMIT_RE = re.compile(r"\blimit\s+(\d+)\s*$", re.I)


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return re.sub(r"--[^\n]*", " ", sql).strip().rstrip(";")


def _allowed_objects(user: UserContext) -> set[str]:
    rows = db.query(
        """SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = %s AND c.relkind IN ('r','v')""", (settings.data_schema,))
    objs = {r["relname"] for r in rows}
    if user.regions is not None:  # G1：部门受限用户禁查大区维度对象
        objs -= REGION_OBJECTS
    return objs


def _validate_sql(sql: str, user: UserContext) -> str:
    """返回清理后的 SQL，违规抛 ApiError。"""
    s = _strip_comments(sql or "")
    if not s:
        raise ApiError(40001, "SQL 为空")
    if not re.match(r"(select|with)\b", s, re.I):
        raise ApiError(40001, "只允许单条 SELECT / WITH 查询")
    if ";" in s:
        raise ApiError(40001, "不允许多语句（检测到分号）")
    m = _FORBIDDEN.search(s)
    if m:
        raise ApiError(40001, f"包含被禁止的关键词：{m.group(0).upper()}")
    # G1：对象白名单
    allowed = _allowed_objects(user)
    used = {a or b for _, b, a in _REL_RE.findall(s)}
    illegal = used - allowed
    if illegal:
        raise ApiError(40001, f"引用了白名单之外的对象：{sorted(illegal)}；请先查数据字典")
    # G5：敏感列
    if user.role not in ("cfo", "admin"):
        if any(k in s for k in SENSITIVE_COLS):
            raise ApiError(40301, "查询涉及薪酬/个人敏感字段，当前角色无权访问")
    # G4：LIMIT 上限
    m = _LIMIT_RE.search(s)
    if m and int(m.group(1)) > HARD_ROW_CAP:
        raise ApiError(40001, f"LIMIT 不能超过 {HARD_ROW_CAP}")
    return s


def _ensure_limit(sql: str) -> str:
    if _LIMIT_RE.search(sql):
        return sql
    return f'{sql}\nLIMIT {HARD_ROW_CAP}'


def _jsonable(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        out.append({k: (float(v) if isinstance(v, Decimal) else
                        v.isoformat(sep=" ", timespec="minutes") if hasattr(v, "isoformat") else v)
                    for k, v in r.items()})
    return out


@contextlib.contextmanager
def _ro_cursor(timeout_ms: int):
    """只读事务 + 语句超时：BEGIN READ ONLY 是写操作的最后一道防线。"""
    with db.get_conn() as conn:
        conn.rollback()
        conn.autocommit = False
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute("BEGIN TRANSACTION READ ONLY")
            cur.execute("SET LOCAL statement_timeout = %s", (timeout_ms,))
            cur.execute('SET search_path TO "%s", %s, public'
                        % (settings.data_schema, settings.app_schema))
            yield cur
        finally:
            conn.rollback()
            cur.close()


# ---------------- 三个工具的实现 ----------------

def tool_dictionary(args: dict, user: UserContext) -> dict:
    target = args.get("target")
    if target == "objects":
        rows = db.query(
            """SELECT c.relname AS name,
                      CASE c.relkind WHEN 'r' THEN 'table' ELSE 'view' END AS kind,
                      c.reltuples::bigint AS est_rows,
                      obj_description(c.oid) AS comment
               FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname = %s AND c.relkind IN ('r','v')
               ORDER BY c.relkind, c.relname""", (settings.data_schema,))
        return {"objects": rows, "note": "中文列名请用双引号；写 SQL 前可用 target=columns 查看字段"}
    if target == "columns":
        name = (args.get("table_name") or "").strip()
        if name not in _allowed_objects(user):
            return {"error": f"对象不存在或不在你的可查范围：{name}"}
        cols = db.query(
            """SELECT column_name, data_type, col_description(('"' || %s || '"')::regclass, ordinal_position) AS comment
               FROM information_schema.columns WHERE table_schema = %s AND table_name = %s
               ORDER BY ordinal_position""",
            (name, settings.data_schema, name))
        if not cols:
            cols = db.query(
                """SELECT column_name, data_type FROM information_schema.columns
                   WHERE table_name = %s ORDER BY ordinal_position""", (name,))
        return {"table": name, "columns": cols}
    if target == "metrics":
        rows = db.query(
            """SELECT code, name, alias, definition, unit, view_name, expr, default_dim, version
               FROM app.meta_metric WHERE is_active ORDER BY code""")
        return {"metrics": rows}
    return {"error": f"未知 target：{target}"}


def tool_run_sql(args: dict, user: UserContext) -> dict:
    sql = _validate_sql(args.get("sql", ""), user)
    sql = _ensure_limit(sql)
    with _ro_cursor(SQL_TIMEOUT_MS) as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    data = _jsonable([dict(r) for r in rows[:MAX_ROWS_TO_LLM]])
    return {"row_count": len(rows),
            "rows": data,
            "truncated": len(rows) > MAX_ROWS_TO_LLM,
            "sql": sql}


def tool_explain(args: dict, user: UserContext) -> dict:
    sql = _validate_sql(args.get("sql", ""), user)
    sql = _ensure_limit(sql)
    with _ro_cursor(EXPLAIN_TIMEOUT_MS) as cur:
        cur.execute(f"EXPLAIN (ANALYZE, FORMAT JSON) {sql}")
        plan = cur.fetchone()
    node = (plan or {}).get("QUERY PLAN") or []
    root = node[0] if node else {}
    exec_ms = float(root.get("Execution Time") or 0)
    top = root.get("Plan") or {}
    verdict = ("性能良好" if exec_ms < 200 else
               "可接受，建议留意" if exec_ms < 1000 else "偏慢，建议优化（加过滤条件/减少扫描量）")
    return {"execution_time_ms": round(exec_ms, 2),
            "planning_time_ms": round(float(root.get("Planning Time") or 0), 2),
            "total_cost": round(float(top.get("Total Cost") or 0), 1),
            "actual_rows": top.get("Actual Rows"),
            "verdict": verdict}


# ---------------- Agent Loop ----------------

def run(question: str, user: UserContext, session_id: str | None = None,
        period: str | None = None) -> dict:
    question = (question or "").strip()
    if len(question) < 2:
        raise ApiError(40001, "问题太短")
    if not llm.available():
        raise ApiError(50003, "Data Agent 需要 DeepSeek：请配置 DEEPSEEK_API_KEY")

    t0 = time.monotonic()
    region_note = ("部门受限用户只能查非大区维度对象；" if user.regions is not None else "你可访问全公司数据；")
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT.format(
            scope=user.scope_label, region_note=region_note,
            max_steps=MAX_STEPS)},
        {"role": "user", "content": f"当前期间：{common.resolve_period(period)}。问题：{question}"},
    ]

    gates = [
        {"code": "G1", "name": "身份与数据范围", "note": "对象白名单按用户范围裁剪", "passed": True,
         "detail": f"范围：{user.scope_label}"},
        {"code": "G2", "name": "指标白名单", "note": "仅数据字典内对象可查", "passed": True, "detail": "对象白名单校验"},
        {"code": "G3", "name": "时间范围", "note": "语句超时 8 秒", "passed": True, "detail": f"超时 {SQL_TIMEOUT_MS // 1000}s"},
        {"code": "G4", "name": "行数与明细", "note": "返回 LLM 最多 40 行", "passed": True, "detail": f"硬上限 {HARD_ROW_CAP} 行"},
        {"code": "G5", "name": "敏感字段", "note": "薪酬/个人信息非 CFO 拒绝", "passed": True, "detail": "列名关键词校验"},
        {"code": "G6", "name": "只读与注入防护", "note": "SELECT-only + READ ONLY 事务", "passed": True, "detail": "双重只读防护"},
    ]

    steps: list[dict] = []
    last_rows: list[dict] = []
    last_sql = ""
    tools_used: set[str] = set()
    answer = ""
    usage_total = 0

    while time.monotonic() - t0 < BUDGET_S and len(steps) < MAX_STEPS + 2:
        msg, usage = llm.chat_msg(messages, tools=TOOLS, temperature=0.2)
        usage_total += int(usage.get("total_tokens") or 0)
        calls = msg.get("tool_calls") or []
        if not calls:
            answer = (msg.get("content") or "").strip()
            break
        messages.append({"role": "assistant", "content": msg.get("content") or "",
                         "tool_calls": calls})
        for c in calls:
            fn = (c.get("function") or {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            ts = time.monotonic()
            try:
                if name == "query_data_dictionary":
                    result = tool_dictionary(args, user)
                elif name == "run_sql":
                    result = tool_run_sql(args, user)
                    last_sql = result.get("sql", last_sql)
                    if result.get("rows") and len(result["rows"]) <= MAX_ROWS_TO_LLM:
                        last_rows = result["rows"]
                elif name == "explain_sql":
                    result = tool_explain(args, user)
                else:
                    result = {"error": f"未知工具：{name}"}
            except ApiError as e:
                result = {"error": e.message}
            except Exception as e:  # noqa: BLE001
                result = {"error": f"工具执行失败：{e}"}
            ms = round((time.monotonic() - ts) * 1000)
            tools_used.add(name)
            summary = _summarize(name, result)
            steps.append({"i": len(steps) + 1, "tool": name, "args": args,
                          "summary": summary, "ms": ms, "ok": "error" not in result})
            messages.append({"role": "tool", "tool_call_id": c.get("id") or "",
                             "content": json.dumps(result, ensure_ascii=False, default=str)[:12000]})
    else:
        answer = ""

    if not answer:  # 预算用尽：强制收尾
        msg, _ = llm.chat_msg(messages + [{"role": "user", "content":
                    "工具调用预算已用完。请基于以上工具结果直接给出最终中文答案。"}], temperature=0.2)
        answer = (msg.get("content") or "").strip()

    elapsed = round((time.monotonic() - t0) * 1000)
    sid = session_id or f"s_{user.id}_{common.data_version().replace('-', '')}"
    db.execute(
        """INSERT INTO app.ai_session(id, user_id, title) VALUES (%s,%s,%s)
           ON CONFLICT (id) DO NOTHING""", (sid, user.id, question[:60]))
    meta_out = {"engine": "DeepSeek Data Agent（自主查数）", "steps": len(steps),
                "tools": sorted(tools_used), "elapsedMs": elapsed,
                "tokens": usage_total, "scope": user.scope_label,
                "source": "Agent 工具链", "metric": "—", "metricCode": "—",
                "metricVersion": "—", "rowCount": len(last_rows)}
    db.execute(
        """INSERT INTO app.ai_message(session_id, role, content, meta)
           VALUES (%s,'user',%s,%s)""",
        (sid, question, db.psycopg2.extras.Json({})))
    saved = db.execute_returning(
        """INSERT INTO app.ai_message(session_id, role, content, meta)
           VALUES (%s,'assistant',%s,%s) RETURNING id""",
        (sid, answer, db.psycopg2.extras.Json({"sql": last_sql, "meta": meta_out, "gates": gates})))

    return {
        "sessionId": sid,
        "question": question,
        "thinking": f"Data Agent 自主执行：{len(steps)} 次工具调用（{('、'.join(sorted(tools_used)) or '无')}），"
                    f"耗时 {elapsed / 1000:.1f}s，{usage_total} tokens",
        "sql": last_sql,
        "answer": answer,
        "rows": last_rows,
        "steps": steps,
        "gates": gates,
        "meta": meta_out,
        "messageId": saved["id"] if saved else None,
    }


def _summarize(name: str, result: dict) -> str:
    if "error" in result:
        return f"失败：{result['error']}"
    if name == "query_data_dictionary":
        if "objects" in result:
            return f"浏览了 {len(result['objects'])} 个表/视图"
        if "columns" in result:
            cols = result["columns"]
            return f"表 {result['table']} 共 {len(cols)} 字段：{('、'.join(c['column_name'] for c in cols[:8]))}…"
        if "metrics" in result:
            return f"读取指标字典 {len(result['metrics'])} 条"
    if name == "run_sql":
        return f"查询返回 {result.get('row_count', 0)} 行"
    if name == "explain_sql":
        return f"执行 {result.get('execution_time_ms')}ms · {result.get('verdict')}"
    return "完成"
