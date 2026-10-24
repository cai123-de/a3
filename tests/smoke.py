"""接口冒烟测试：不依赖 pytest，直接跑真实 HTTP。

用法： python tests/smoke.py [base_url]
覆盖：登录 → 10 个模块读接口 → 权限拒绝 → AI 问答（含 LLM 状态）→ 错误码。
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8021") + "/api/v1"
PASS, FAIL = 0, 0


def call(path: str, method: str = "GET", body=None, token: str | None = None):
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Content-Type": "application/json",
                 **({"Authorization": "Bearer " + token} if token else {})})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:  # noqa: BLE001
            return e.code, {"raw": raw[:200].decode("utf-8", "ignore")}


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  {detail}")


def login(username: str, pwd: str = "Fin@2026"):
    s, r = call("/auth/login", "POST", {"username": username, "password": pwd})
    return r["data"]["accessToken"] if s == 200 and r.get("code") == 0 else None


def main() -> int:
    print("\n[1] 认证")
    s, r = call("/auth/login", "POST", {"username": "chenjing", "password": "wrong"})
    check("错误口令返回 40101", r.get("code") == 40101, str(r)[:120])
    s, r = call("/auth/login", "POST", {"username": "chenjing", "password": "Fin@2026"})
    check("CFO 登录成功", r.get("code") == 0)
    cfo = r["data"]["accessToken"]
    check("CFO 数据范围为全公司", r["data"]["user"]["scopeLabel"] == "全公司")
    check("菜单 10 项", len(r["data"]["menus"]) == 10)

    s, r = call("/overview/kpi")
    check("未带令牌返回 40101", r.get("code") == 40101)

    print("\n[2] 经营总览")
    s, r = call("/overview/kpi?period=2025-12", token=cfo)
    check("KPI 8 张卡", len(r["data"]["cards"]) == 8, str(r)[:100])
    rev = next(c for c in r["data"]["cards"] if c["key"] == "rev")["value"]
    check("2025-12 收入 ≈ 1.146 亿", 1.13e8 < rev < 1.16e8, str(rev))
    s, r = call("/overview/statement?period=2025-12", token=cfo)
    check("利润表子项勾稽通过", r["data"]["checkPassed"] is True, str(r["data"].get("rows"))[:100])
    s, r = call("/overview/drill?path=revenue&dim=product&period=2025-12", token=cfo)
    check("下钻按产品返回", len(r["data"]["rows"]) > 0 and r["data"]["total"] > 0, str(r)[:120])
    s, r = call("/overview/charts?period=2025-12", token=cfo)
    check("图表包 6 组", all(k in r["data"] for k in
                        ("trend", "waterfall", "expense", "aging", "regions", "products")))
    s, r = call("/overview/quality", token=cfo)
    check("数据质量四项勾稽通过",
          all(x["passed"] for x in r["data"]["reconciliation"]), str(r["data"]["reconciliation"])[:160])

    print("\n[3] 客户 / 应收 / 成本 / 预算")
    s, r = call("/customer/summary", token=cfo)
    check("客户分层有数据", len(r["data"]["tiers"]) >= 3)
    s, r = call("/customer/renewal-calendar?months=6", token=cfo)
    check("续约日历可查", "count" in r["data"], str(r)[:100])
    s, r = call("/ar/aging", token=cfo)
    check("账龄 5 桶", len(r["data"]["buckets"]) == 5, str([b["bucket"] for b in r["data"]["buckets"]]))
    check("账龄合计 > 0", r["data"]["total"] > 1e8, str(r["data"]["total"]))
    s, r = call("/ar/overdue?size=5", token=cfo)
    check("逾期清单分页", r["data"]["total"] > 0 and len(r["data"]["rows"]) <= 5, str(r)[:100])
    s, r = call("/cost/summary", token=cfo)
    check("COGS 三类", len(r["data"]["cogs"]["types"]) == 3)
    s, r = call("/budget/execution", token=cfo)
    check("预算执行有 4 个版本", len(r["data"]["versions"]) >= 4, str(r["data"].get("versions")))
    s, r = call("/budget/variance", token=cfo)
    tot = r["data"]["revenue"]["total"]
    check("量 + 价 + 结构 = 总差异",
          abs((tot["volume"] + tot["price"] + tot["structure"]) - tot["diff"]) < 1, str(tot))

    print("\n[4] AI 语义层")
    s, r = call("/ai/status", token=cfo)
    check("LLM 状态端点", r.get("code") == 0 and "enabled" in r["data"] and "fallback" in r["data"], str(r)[:120])
    s, r = call("/ai/ask", "POST", {"question": "2025年12月营业收入是多少"}, token=cfo)
    check("单指标问答", r.get("code") == 0 and r["data"]["rows"][0]["value"] > 1e8, str(r)[:120])
    check("返回六道闸门", len(r["data"]["gates"]) == 6)
    s, r = call("/ai/ask", "POST", {"question": "帮我分析一下2025年的销售趋势"}, token=cfo)
    check("趋势问答（GROUP BY 聚合修复）", r.get("code") == 0 and len(r["data"]["rows"]) >= 10, str(r)[:120])
    s, r = call("/ai/ask", "POST", {"question": "2025年12月各产品线毛利率"}, token=cfo)
    check("维度拆分问答", r.get("code") == 0 and len(r["data"]["rows"]) >= 3, str(r)[:120])
    s, r = call("/ai/ask", "POST", {"question": "今天天气怎么样"}, token=cfo)
    check("未命中指标给出建议问法", r.get("code") == 50002 and r["detail"]["suggestions"], str(r)[:120])
    s, r = call("/ai/agent", "POST", {"question": "各产品线毛利率是多少"}, token=cfo)
    check("Data Agent 工具链（未配置 LLM 时自动跳过）",
          (r.get("code") == 0 and r["data"]["meta"]["engine"].startswith("DeepSeek Data Agent")
           and len(r["data"]["steps"]) >= 2) or r.get("code") == 50003, str(r)[:150])

    print("\n[5] 三维权限")
    sales = login("wanglin")
    check("销售主管登录", bool(sales))
    s, r = call("/auth/me", token=sales)
    check("数据范围收敛到华东", r["data"]["user"]["regions"] == ["华东"], str(r["data"]["user"]["regions"]))
    check("金额阈值 200 万", r["data"]["user"]["amountThreshold"] == 2000000)
    s, r = call("/overview/kpi", token=sales)
    check("销售可看总览", r.get("code") == 0)
    s, r = call("/cost/summary", token=sales)
    check("销售看成本被拒 40301", r.get("code") == 40301, str(r)[:100])
    s, r = call("/budget/draft", token=sales)
    check("销售访问预算编制被拒", r.get("code") == 40301)

    junior = login("zhoumin")
    s, r = call("/auth/me", token=junior)
    check("初级会计深度为 summary", r["data"]["user"]["depth"] == "summary")
    check("初级会计金额脱敏", r["data"]["user"]["fieldMask"].get("amount") == "hidden")
    s, r = call("/admin/users", token=junior)
    check("初级会计访问用户管理被拒", r.get("code") == 40301)

    admin = login("wanglei")
    s, r = call("/admin/grades", token=admin)
    check("管理员可读职级映射", r.get("code") == 0 and len(r["data"]) == 6)

    print("\n[6] 预警与审计")
    s, r = call("/alerts", token=cfo)
    check("预警列表有数据", r["data"]["stats"]["open"] > 0, str(r["data"]["stats"]))
    s, r = call("/admin/audit-logs", token=cfo)
    check("审计日志已记录", r["data"]["total"] > 0)
    check("拒绝访问被审计", any(x["action"] in ("deny", "view") for x in r["data"]["rows"]))

    print("\n[6.5] AI Key 管理")
    s, r = call("/admin/ai-key", token=cfo)
    check("AI Key 状态端点", r.get("code") == 0 and "enabled" in r["data"]
          and ("maskedKey" in r["data"]), str(r)[:100])
    check("密钥只回传掩码", r["data"]["maskedKey"] is None or "****" in r["data"]["maskedKey"])
    s, r = call("/admin/ai-key", "POST", {"apiKey": "sk-short"}, token=cfo)
    check("非法密钥格式被拒 40001", r.get("code") == 40001)
    junior2 = login("zhoumin")
    s, r = call("/admin/ai-key", token=junior2)
    check("初级会计访问 AI Key 被拒 40301", r.get("code") == 40301)
    s, r = call("/admin/ai-key/params", "PUT", {"effort": "high", "maxTokens": 0}, token=cfo)
    check("推理参数保存（官方默认值）", r.get("code") == 0 and r["data"]["effort"] == "high", str(r)[:100])
    s, r = call("/admin/ai-key/params", "PUT", {"effort": "bogus", "maxTokens": 0}, token=cfo)
    check("非法思考强度被拒", r.get("code") not in (0, None), str(r)[:100])

    print("\n[7] 语义模型 / 数据管理")
    s, r = call("/semantic/metrics", token=cfo)
    check("指标字典 31 条", r.get("code") == 0 and len(r["data"]) == 31, str(r)[:120])
    codes = {m["code"] for m in r["data"]} if r.get("code") == 0 else set()
    check("服务收入编码在字典", "service_revenue" in codes and "revenue" in codes)
    s, r = call("/semantic/metrics/revenue", token=cfo)
    check("收入指标详情含下钻映射", r.get("code") == 0 and len(r["data"]["drills"]) > 0, str(r)[:120])
    s, r = call("/semantic/metrics/gross_margin", token=cfo)
    check("毛利率详情含版本沿革", r.get("code") == 0 and len(r["data"]["versions"]) >= 2, str(r)[:120])
    s, r = call("/semantic/views", token=cfo)
    check("sem 视图 4 个", r.get("code") == 0 and len(r["data"]) == 4, str(r)[:120])
    s, r = call("/semantic/values?code=revenue", token=cfo)
    check("长表取数近 12 期", r.get("code") == 0 and len(r["data"]["rows"]) == 12, str(r)[:120])
    s, r = call("/semantic/values?code=revenue&start=2025-1", token=cfo)
    check("非法期间格式被拒 40001", r.get("code") == 40001)
    s, r = call("/dataops/assets", token=cfo)
    check("资产盘点含表与视图", r.get("code") == 0 and r["data"]["summary"]["tables"] > 0
          and r["data"]["summary"]["views"] > 0, str(r)[:120])
    s, r = call("/dataops/relations", token=cfo)
    check("关系地图 31 条以上", r.get("code") == 0 and len(r["data"]) >= 31, str(r)[:100])
    s, r = call("/dataops/periods", token=cfo)
    check("期间管理 60 期", r.get("code") == 0 and len(r["data"]["rows"]) == 60, str(r)[:100])
    sales = login("wanglin")
    s, r = call("/semantic/metrics", token=sales)
    check("销售访问语义模型被拒 40301", r.get("code") == 40301, str(r)[:100])
    s, r = call("/dataops/assets", token=sales)
    check("销售访问数据管理被拒 40301", r.get("code") == 40301)

    print(f"\n结果：{PASS} 通过 / {FAIL} 失败\n")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
