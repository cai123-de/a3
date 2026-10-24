"""预算管理：版本、执行、差异归因、滚动预测、编制草稿与审批。

一期以「读」为主（执行监控 + 差异归因），编制/审批的写接口已可用，
但只对 2026 年度草稿开放，避免误改历史预算。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from .. import db, permissions
from ..deps import require
from ..permissions import UserContext
from ..response import ApiError, ok
from ..services import common

router = APIRouter(prefix="/budget", tags=["预算管理"])

DRAFT_YEAR = 2026


def _versions() -> list[str]:
    rows = db.query(
        """SELECT DISTINCT "预算版本" AS v FROM "fact_budget"
           UNION SELECT DISTINCT "预算版本" FROM "fact_revenue_budget"
           ORDER BY 1""")
    return [r["v"] for r in rows if r["v"]]


@router.get("/versions")
def versions(user: UserContext = Depends(require("budget:view"))):
    rows = db.query(
        """SELECT "预算版本" AS version, COUNT(*)::int AS rows,
                  COUNT(DISTINCT "预算月份")::int AS months,
                  SUM("预算金额") AS amount
           FROM "fact_budget" GROUP BY 1 ORDER BY 1""")
    return ok([{"version": r["version"], "rows": r["rows"], "months": r["months"],
                "amount": round(float(r["amount"] or 0), 2)} for r in rows])


@router.get("/execution")
def execution(period: str | None = None, version: str | None = None,
              user: UserContext = Depends(require("budget:view"))):
    p = common.resolve_period(period)
    version = version or "年初预算"

    rev = db.query(
        """SELECT "收入类型" AS kind, SUM("预算收入") AS budget, SUM("实际收入") AS actual,
                  SUM("预算客户数")::int AS budget_customers, SUM("实际客户数")::int AS actual_customers
           FROM "V_收入预算执行" WHERE "月份" = %s AND "预算版本" = %s GROUP BY 1""", (p, version))
    cost = db.query(
        """SELECT "成本类型" AS kind, SUM("预算成本") AS budget, SUM("实际成本") AS actual
           FROM "V_成本预算执行" WHERE "月份" = %s AND "预算版本" = %s GROUP BY 1""", (p, version))
    exp = db.query_one(
        """SELECT COALESCE(SUM("预算金额"),0) AS budget, COALESCE(SUM("实际金额"),0) AS actual
           FROM "V_费用预算执行" WHERE "月份" = %s AND "预算版本" = %s""", (p, version))

    def line(name: str, budget: float, actual: float, kind: str, extra: dict | None = None):
        rate = round(actual / budget * 100, 2) if budget else None
        return {"name": name, "budget": round(budget, 2), "actual": round(actual, 2),
                "diff": round(actual - budget, 2), "rate": rate, "kind": kind,
                **(extra or {})}

    rev_total_b = sum(float(r["budget"] or 0) for r in rev)
    rev_total_a = sum(float(r["actual"] or 0) for r in rev)
    cost_total_b = sum(float(r["budget"] or 0) for r in cost)
    cost_total_a = sum(float(r["actual"] or 0) for r in cost)

    lines = [line("营业收入", rev_total_b, rev_total_a, "revenue")]
    for r in rev:
        lines.append(line(f"　{r['kind']}", float(r["budget"] or 0), float(r["actual"] or 0), "revenue",
                          {"customers": {"budget": r["budget_customers"], "actual": r["actual_customers"]}}))
    for r in cost:
        lines.append(line(f"营业成本 · {r['kind']}", float(r["budget"] or 0), float(r["actual"] or 0), "cost"))
    lines.append(line("期间费用", float(exp["budget"] or 0), float(exp["actual"] or 0), "expense"))

    # 在途占用（本期用 0 占位，接 OA 后取未审批申请单）
    for l in lines:
        l["transit"] = 0.0

    return ok({
        "period": p, "version": version,
        "versions": _versions(),
        "lines": lines,
        "totals": {
            "revenueBudget": round(rev_total_b, 2), "revenueActual": round(rev_total_a, 2),
            "costBudget": round(cost_total_b, 2), "costActual": round(cost_total_a, 2),
            "expenseBudget": round(float(exp["budget"] or 0), 2),
            "expenseActual": round(float(exp["actual"] or 0), 2),
        },
        "note": "三条预算线口径不同（收入按大区×产品、成本按产品、费用按科目），不叠加。",
    }, meta=common.meta(p))


@router.get("/variance")
def variance(period: str | None = None, version: str | None = None,
             user: UserContext = Depends(require("budget:view"))):
    """收入差异三因素分解：量差 + 价差 + 结构差 = 总差异。"""
    p = common.resolve_period(period)
    version = version or "年初预算"
    rows = db.query(
        """SELECT "产品名称" AS product, "产品线" AS line,
                  SUM("预算收入") AS budget, SUM("实际收入") AS actual,
                  SUM("预算客户数")::int AS bc, SUM("实际客户数")::int AS ac
           FROM "V_收入预算执行"
           WHERE "月份" = %s AND "预算版本" = %s
           GROUP BY 1,2 ORDER BY 3 DESC""", (p, version))

    items, vol_sum, price_sum, total_diff = [], 0.0, 0.0, 0.0
    for r in rows:
        b, a = float(r["budget"] or 0), float(r["actual"] or 0)
        bc, ac = int(r["bc"] or 0), int(r["ac"] or 0)
        arpa_b = b / bc if bc else 0
        vol = (ac - bc) * arpa_b
        price = a - ac * arpa_b
        items.append({"product": r["product"], "line": r["line"], "budget": round(b, 2),
                      "actual": round(a, 2), "diff": round(a - b, 2),
                      "volume": round(vol, 2), "price": round(price, 2),
                      "customers": {"budget": bc, "actual": ac},
                      "arpaBudget": round(arpa_b, 2)})
        vol_sum += vol
        price_sum += price
        total_diff += a - b

    structure = total_diff - vol_sum - price_sum

    exp = db.query(
        """SELECT "科目类别" AS category, SUM("预算金额") AS budget, SUM("实际金额") AS actual
           FROM "V_费用预算执行" WHERE "月份" = %s AND "预算版本" = %s
           GROUP BY 1 ORDER BY 2 DESC""", (p, version))
    exp_items = [{"category": r["category"], "budget": round(float(r["budget"] or 0), 2),
                  "actual": round(float(r["actual"] or 0), 2),
                  "diff": round(float(r["actual"] or 0) - float(r["budget"] or 0), 2),
                  "rate": round(float(r["actual"] or 0) / float(r["budget"] or 1) * 100, 2)}
                 for r in exp]

    return ok({
        "period": p, "version": version,
        "revenue": {
            "items": items,
            "total": {"budget": round(sum(i["budget"] for i in items), 2),
                      "actual": round(sum(i["actual"] for i in items), 2),
                      "diff": round(total_diff, 2),
                      "volume": round(vol_sum, 2),
                      "price": round(price_sum, 2),
                      "structure": round(structure, 2)},
            "check": round(vol_sum + price_sum + structure, 2),
        },
        "expense": {
            "items": exp_items,
            "total": {"budget": round(sum(i["budget"] for i in exp_items), 2),
                      "actual": round(sum(i["actual"] for i in exp_items), 2),
                      "diff": round(sum(i["diff"] for i in exp_items), 2)},
            "note": "费用缺少「人头 × 人均」的预算明细，暂只做金额差异；量价拆分需要编制侧补驱动因子。",
        },
    }, meta=common.meta(p))


@router.get("/forecast")
def forecast(period: str | None = None, version: str | None = None,
             factor: float | None = None,
             user: UserContext = Depends(require("budget:view"))):
    """滚动预测：全年 = YTD 实际 + 剩余月预算 × 修正系数（默认取近 3 个月执行偏差）。"""
    p = common.resolve_period(period)
    version = version or "年初预算"
    year = p[:4]

    monthly = db.query(
        """SELECT "月份" AS month, SUM("预算金额") AS budget, SUM("实际金额") AS actual
           FROM "V_费用预算执行" WHERE "预算版本" = %s AND "月份" LIKE %s
           GROUP BY 1 ORDER BY 1""", (version, year + "-%"))
    if not monthly:
        raise ApiError(40401, f"{year} 年没有{version}的费用预算数据")

    ytd_actual = sum(float(r["actual"] or 0) for r in monthly if r["month"] <= p)
    last3 = [r for r in monthly if r["month"] <= p][-3:]
    ratios = [float(r["actual"] or 0) / float(r["budget"] or 1) for r in last3 if float(r["budget"] or 0)]
    auto_factor = round(sum(ratios) / len(ratios), 4) if ratios else 1.0
    f = factor if factor is not None else auto_factor

    remaining = [r for r in monthly if r["month"] > p]
    remaining_budget = sum(float(r["budget"] or 0) for r in remaining)
    forecast_total = ytd_actual + remaining_budget * f
    year_budget = sum(float(r["budget"] or 0) for r in monthly)

    return ok({
        "period": p, "version": version, "year": year,
        "factor": round(f, 4), "autoFactor": auto_factor,
        "ytdActual": round(ytd_actual, 2),
        "remainingBudget": round(remaining_budget, 2),
        "forecast": round(forecast_total, 2),
        "yearBudget": round(year_budget, 2),
        "gap": round(forecast_total - year_budget, 2),
        "gapRate": round((forecast_total - year_budget) / year_budget * 100, 2) if year_budget else None,
        "monthly": [{"month": r["month"], "budget": round(float(r["budget"] or 0), 2),
                     "actual": round(float(r["actual"] or 0), 2)} for r in monthly],
        "note": "预测超预算 5% 或较上月下修 10% 时触发预警。",
    }, meta=common.meta(p))


# ----------------------------- 编制（写） -----------------------------
@router.get("/draft")
def get_draft(year: int = DRAFT_YEAR, unit_type: str = "dept", unit_code: str | None = None,
              version: str = "2026年度预算",
              user: UserContext = Depends(require("budget:edit"))):
    unit_code = unit_code or user.dept_code or "FIN"
    header = db.query_one(
        """SELECT * FROM app.bud_header
           WHERE period_year = %s AND unit_type = %s AND unit_code = %s AND version = %s""",
        (year, unit_type, unit_code, version))
    if not header:
        return ok({"header": None, "lines": [], "unit": {"type": unit_type, "code": unit_code}})
    lines = db.query(
        """SELECT subject, subject_name, month, draft_amount, approved_amount, adjust_amount, note
           FROM app.bud_line WHERE header_id = %s ORDER BY subject, month""", (header["id"],))
    return ok({
        "header": {**header, "submitted_at": header["submitted_at"].isoformat() if header["submitted_at"] else None},
        "lines": [{"subject": r["subject"], "subjectName": r["subject_name"], "month": r["month"],
                   "draft": round(float(r["draft_amount"] or 0), 2),
                   "approved": round(float(r["approved_amount"] or 0), 2) if r["approved_amount"] is not None else None,
                   "adjust": round(float(r["adjust_amount"] or 0), 2), "note": r["note"]} for r in lines],
    })


class DraftLine(BaseModel):
    subject: str
    subjectName: str | None = None
    month: str
    amount: float


class DraftBody(BaseModel):
    year: int = DRAFT_YEAR
    unitType: str = "dept"
    unitCode: str | None = None
    version: str = "2026年度预算"
    lines: list[DraftLine]


@router.put("/draft")
def save_draft(body: DraftBody, user: UserContext = Depends(require("budget:edit"))):
    unit_code = body.unitCode or user.dept_code or "FIN"
    header = db.query_one(
        """SELECT id, status FROM app.bud_header
           WHERE period_year=%s AND unit_type=%s AND unit_code=%s AND version=%s""",
        (body.year, body.unitType, unit_code, body.version))
    if header and header["status"] in ("issued", "approved"):
        raise ApiError(40001, "预算已下达/审批通过，请走调整单流程")

    if not header:
        rec = db.execute_returning(
            """INSERT INTO app.bud_header(version, period_year, unit_type, unit_code, status)
               VALUES (%s,%s,%s,%s,'draft') RETURNING id""",
            (body.version, body.year, body.unitType, unit_code))
        header_id = rec["id"]
    else:
        header_id = header["id"]
        db.execute("DELETE FROM app.bud_line WHERE header_id = %s", (header_id,))

    db.execute_many(
        """INSERT INTO app.bud_line(header_id, subject, subject_name, month, draft_amount)
           VALUES (%s,%s,%s,%s,%s)""",
        [(header_id, l.subject, l.subjectName, l.month, l.amount) for l in body.lines])
    total = sum(l.amount for l in body.lines)
    db.execute("UPDATE app.bud_header SET total_amount=%s, status='draft', round_no=round_no+1 WHERE id=%s",
               (total, header_id))
    permissions.audit(user, "update", "budget/draft", {"header": header_id, "lines": len(body.lines)})
    return ok({"headerId": header_id, "lines": len(body.lines), "total": round(total, 2)})


class SubmitBody(BaseModel):
    headerId: int
    comment: str | None = None


@router.post("/submit")
def submit(body: SubmitBody, user: UserContext = Depends(require("budget:edit"))):
    header = db.query_one("SELECT * FROM app.bud_header WHERE id = %s", (body.headerId,))
    if not header:
        raise ApiError(40401, "编制单不存在")
    if header["status"] not in ("draft", "returned"):
        raise ApiError(40001, f"当前状态 {header['status']} 不能提交")
    db.execute("""UPDATE app.bud_header SET status='submitted', submitted_by=%s, submitted_at=now()
                  WHERE id=%s""", (user.id, body.headerId))
    db.execute(
        """INSERT INTO app.wf_task(flow_code, doc_type, doc_id, node, approver_id, action, comment)
           VALUES ('WF_BUDGET','bud_header',%s,'部门提交',%s,'approve',%s)""",
        (body.headerId, user.id, body.comment))
    permissions.audit(user, "update", "budget/submit", {"header": body.headerId})
    return ok({"headerId": body.headerId, "status": "submitted"})


class ApproveBody(BaseModel):
    headerId: int
    action: str = "approve"
    comment: str | None = None


@router.post("/approve")
def approve(body: ApproveBody, user: UserContext = Depends(require("budget:approve"))):
    if body.action not in ("approve", "reject"):
        raise ApiError(40001, "action 只能是 approve / reject")
    header = db.query_one("SELECT * FROM app.bud_header WHERE id = %s", (body.headerId,))
    if not header:
        raise ApiError(40401, "编制单不存在")
    new_status = "approved" if body.action == "approve" else "returned"
    db.execute("UPDATE app.bud_header SET status=%s WHERE id=%s", (new_status, body.headerId))
    db.execute(
        """INSERT INTO app.wf_task(flow_code, doc_type, doc_id, node, approver_id, action, comment, acted_at)
           VALUES ('WF_BUDGET','bud_header',%s,'CFO 审批',%s,%s,%s,now())""",
        (body.headerId, user.id, body.action, body.comment))
    if body.action == "approve":
        db.execute("UPDATE app.bud_line SET approved_amount=draft_amount+adjust_amount WHERE header_id=%s",
                   (body.headerId,))
    permissions.audit(user, "update", "budget/approve",
                      {"header": body.headerId, "action": body.action})
    return ok({"headerId": body.headerId, "status": new_status})


class AdjustBody(BaseModel):
    headerId: int
    kind: str
    amount: float
    fromSubject: str | None = None
    toSubject: str | None = None
    reason: str


@router.post("/adjust")
def adjust(body: AdjustBody, user: UserContext = Depends(require("budget:edit"))):
    if body.kind not in ("increase", "decrease", "transfer"):
        raise ApiError(40001, "kind 取值 increase/decrease/transfer")
    doc_no = f"ADJ{common.latest_period().replace('-', '')}{db.scalar('SELECT count(*)+1 FROM app.bud_adjust')}"
    rec = db.execute_returning(
        """INSERT INTO app.bud_adjust(doc_no, header_id, kind, from_subject, to_subject, amount, reason, created_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (doc_no, body.headerId, body.kind, body.fromSubject, body.toSubject, body.amount,
         body.reason, user.id))
    db.execute(
        """INSERT INTO app.wf_task(flow_code, doc_type, doc_id, node, action)
           VALUES ('WF_ADJUST','bud_adjust',%s,'财务BP 复核','pending')""", (rec["id"],))
    permissions.audit(user, "update", "budget/adjust", {"doc": doc_no, "amount": body.amount})
    return ok({"id": rec["id"], "docNo": doc_no, "status": "pending"})
