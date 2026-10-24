"""报表中心与订阅推送。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import db, permissions
from ..deps import require
from ..permissions import UserContext
from ..response import ApiError, ok
from ..services import common

router = APIRouter(prefix="/reports", tags=["报表中心"])


@router.get("/definitions")
def definitions(user: UserContext = Depends(require("report:view"))):
    rows = db.query("""SELECT code, name, category, owner, cron, formats, note
                       FROM app.rpt_definition ORDER BY category, code""")
    last = db.query(
        """SELECT DISTINCT ON (report_code) report_code, status, row_count, cost_ms, created_at
           FROM app.rpt_run ORDER BY report_code, created_at DESC""")
    last_map = {r["report_code"]: r for r in last}
    subs = db.query("""SELECT report_code, cron, channel, enabled FROM app.rpt_subscription
                       WHERE user_id = %s""", (user.id,))
    sub_map = {r["report_code"]: r for r in subs}

    out = []
    for r in rows:
        l = last_map.get(r["code"])
        s = sub_map.get(r["code"])
        out.append({
            **r,
            "lastRun": l["created_at"].isoformat(timespec="minutes") if l else None,
            "lastStatus": l["status"] if l else None,
            "lastRows": l["row_count"] if l else None,
            "lastCostMs": l["cost_ms"] if l else None,
            "subscribed": bool(s and s["enabled"]),
            "channel": s["channel"] if s else None,
        })
    return ok(out)


@router.get("/runs")
def runs(limit: int = 20, user: UserContext = Depends(require("report:view"))):
    rows = db.query(
        """SELECT r.id, r.report_code, d.name, r.period, r.status, r.row_count,
                  r.cost_ms, r.file_name, r.created_at
           FROM app.rpt_run r JOIN app.rpt_definition d ON d.code = r.report_code
           ORDER BY r.created_at DESC LIMIT %s""", (min(limit, 100),))
    return ok([{**r, "created_at": r["created_at"].isoformat(timespec="minutes")} for r in rows])


class SubscribeBody(BaseModel):
    reportCode: str
    enabled: bool = True
    channel: str = "邮件"
    cron: str | None = None


@router.post("/subscribe")
def subscribe(body: SubscribeBody, user: UserContext = Depends(require("report:view"))):
    d = db.query_one("SELECT code, cron FROM app.rpt_definition WHERE code = %s", (body.reportCode,))
    if not d:
        raise ApiError(40401, "报表不存在")
    db.execute(
        """INSERT INTO app.rpt_subscription(user_id, report_code, cron, channel, enabled)
           VALUES (%s,%s,%s,%s,%s)
           ON CONFLICT (user_id, report_code)
           DO UPDATE SET enabled = EXCLUDED.enabled, channel = EXCLUDED.channel""",
        (user.id, body.reportCode, body.cron or d["cron"] or "每月 5 日 09:00",
         body.channel, body.enabled))
    permissions.audit(user, "update", "reports/subscribe",
                      {"report": body.reportCode, "enabled": body.enabled})
    return ok({"reportCode": body.reportCode, "enabled": body.enabled, "channel": body.channel})


@router.post("/{code}/run")
def run(code: str, user: UserContext = Depends(require("report:view"))):
    d = db.query_one("SELECT code FROM app.rpt_definition WHERE code = %s", (code,))
    if not d:
        raise ApiError(40401, "报表不存在")
    rec = db.execute_returning(
        """INSERT INTO app.rpt_run(report_code, period, status, row_count, cost_ms, file_name)
           VALUES (%s,%s,'success',%s,%s,%s) RETURNING id""",
        (code, common.latest_period(), 1200, 860, f"{code}_{common.latest_period()}.xlsx"))
    permissions.audit(user, "export", "reports/run", {"report": code})
    return ok({"id": rec["id"], "status": "success", "fileName": f"{code}_{common.latest_period()}.xlsx",
               "note": "原型阶段为异步任务占位，接入 Celery 后返回 taskId"})
