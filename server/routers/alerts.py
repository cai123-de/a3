"""预警中心：规则、预警列表、确认与关闭。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import db, permissions
from ..deps import require
from ..permissions import UserContext
from ..response import ApiError, ok

router = APIRouter(prefix="/alerts", tags=["预警中心"])


@router.get("")
def list_alerts(status: str | None = None, level: str | None = None,
                user: UserContext = Depends(require("alert:view"))):
    where, params = [], []
    if status:
        where.append("status = %s")
        params.append(status)
    if level:
        where.append("level = %s")
        params.append(level)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    rows = db.query(
        f"""SELECT id, rule_code, level, title, detail, metric_code, period, object_id,
                   amount, status, owner, handle_note, created_at, closed_at
            FROM app.sys_alert{clause}
            ORDER BY CASE status WHEN 'open' THEN 1 WHEN 'ack' THEN 2 ELSE 3 END,
                     CASE level WHEN 'high' THEN 1 WHEN 'mid' THEN 2 ELSE 3 END,
                     created_at DESC LIMIT 200""", params)
    out = []
    for r in rows:
        out.append({**r,
                    "amount": round(float(r["amount"] or 0), 2) if r["amount"] is not None else None,
                    "created_at": r["created_at"].isoformat(timespec="minutes"),
                    "closed_at": r["closed_at"].isoformat(timespec="minutes") if r["closed_at"] else None})
    stats = db.query_one(
        """SELECT count(*) FILTER (WHERE status = 'open') AS open,
                  count(*) FILTER (WHERE status = 'ack') AS ack,
                  count(*) FILTER (WHERE status = 'closed') AS closed,
                  count(*) FILTER (WHERE level = 'high' AND status <> 'closed') AS high
           FROM app.sys_alert""")
    return ok({"rows": out, "stats": stats})


@router.get("/rules")
def rules(user: UserContext = Depends(require("alert:view"))):
    return ok(db.query("""SELECT code, name, category, expr, level, channel, owner_role, enabled
                          FROM app.sys_alert_rule ORDER BY code"""))


class HandleBody(BaseModel):
    action: str          # ack / close
    note: str | None = None


@router.post("/{alert_id}/handle")
def handle(alert_id: int, body: HandleBody,
           user: UserContext = Depends(require("alert:handle"))):
    if body.action not in ("ack", "close", "reopen"):
        raise ApiError(40001, "action 只能是 ack / close / reopen")
    row = db.query_one("SELECT id, status FROM app.sys_alert WHERE id = %s", (alert_id,))
    if not row:
        raise ApiError(40401, "预警不存在")
    new_status = {"ack": "ack", "close": "closed", "reopen": "open"}[body.action]
    db.execute(
        """UPDATE app.sys_alert SET status=%s, handle_note=COALESCE(%s, handle_note),
                  closed_at = CASE WHEN %s = 'closed' THEN now() ELSE NULL END
           WHERE id=%s""",
        (new_status, body.note, new_status, alert_id))
    permissions.audit(user, "update", "alerts/handle",
                      {"alert": alert_id, "action": body.action, "note": body.note})
    return ok({"id": alert_id, "status": new_status})
