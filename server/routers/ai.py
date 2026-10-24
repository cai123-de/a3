"""AI 分析：提问、会话、反馈、评测集。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from .. import db, permissions
from ..deps import require
from ..permissions import UserContext
from ..response import ok
from ..services import ai_engine, agent, common

router = APIRouter(prefix="/ai", tags=["AI 分析"])


class AskBody(BaseModel):
    question: str = Field(min_length=2, max_length=200)
    sessionId: str | None = None
    period: str | None = None
    stream: bool = False


@router.post("/ask")
def ask(body: AskBody, user: UserContext = Depends(require("ai:ask"))):
    result = ai_engine.ask(body.question, user, body.sessionId, body.period)
    permissions.audit(user, "query", "ai/ask",
                      {"question": body.question, "metric": result["meta"]["metricCode"],
                       "rows": len(result["rows"])})
    return ok(result, meta=common.meta(body.period))


@router.post("/agent")
def agent_ask(body: AskBody, user: UserContext = Depends(require("ai:ask"))):
    """Data Agent：自主查数计算分析（数据字典 / 自由只读 SQL / 性能验证 三工具）。"""
    result = agent.run(body.question, user, body.sessionId, body.period)
    permissions.audit(user, "query", "ai/agent",
                      {"question": body.question, "steps": len(result["steps"]),
                       "tools": result["meta"]["tools"], "rows": len(result["rows"])})
    return ok(result, meta=common.meta(body.period))


@router.get("/session/{session_id}")
def session(session_id: str, user: UserContext = Depends(require("ai:ask"))):
    rows = ai_engine.history(session_id, user)
    return ok([{
        "role": r["role"], "content": r["content"], "meta": r["meta"],
        "feedback": r["feedback"], "at": r["created_at"].isoformat(timespec="minutes"),
    } for r in rows])


class FeedbackBody(BaseModel):
    message: int
    value: int = Field(ge=-1, le=1)
    note: str | None = None


@router.post("/feedback")
def feedback(body: FeedbackBody, user: UserContext = Depends(require("ai:ask"))):
    db.execute("UPDATE app.ai_message SET feedback=%s WHERE id=%s", (body.value, body.message))
    permissions.audit(user, "update", "ai/feedback", {"message": body.message, "value": body.value})
    return ok({"message": body.message, "feedback": body.value})


@router.get("/eval")
def eval_cases(user: UserContext = Depends(require("ai:ask"))):
    rows = ai_engine.eval_cases()
    return ok({
        "total": len(rows),
        "byLevel": {lv: sum(1 for r in rows if r["level"] == lv) for lv in ("L1", "L2", "L3", "L4")},
        "safety": sum(1 for r in rows if r["safety"]),
        "cases": [{**r, "expected": float(r["expected"]) if r["expected"] is not None else None}
                  for r in rows],
    })


@router.get("/metrics")
def metrics(q: str | None = None, user: UserContext = Depends(require("ai:ask"))):
    rows = db.query(
        """SELECT code, name, alias, definition, unit, view_name, version
           FROM app.meta_metric WHERE is_active
             AND (%s IS NULL OR name ILIKE '%%'||%s||'%%' OR alias ILIKE '%%'||%s||'%%')
           ORDER BY code""", (q, q, q))
    return ok(rows)


@router.get("/status")
def status(user: UserContext = Depends(require("ai:ask"))):
    """LLM 接入状态：是否配置 DeepSeek、模型与端点（不回传密钥）。"""
    from ..config import settings
    from ..services import llm
    return ok({
        "enabled": llm.available(),
        "model": settings.llm_model if llm.available() else None,
        "baseUrl": settings.llm_base_url if llm.available() else None,
        "fallback": "语义层规则引擎",
        "boundary": "LLM 仅做意图解析（指标/维度/期间），取数与六道闸门全部在服务端语义层",
    })


@router.get("/suggestions")
def suggestions(user: UserContext = Depends(require("ai:ask"))):
    p = common.latest_period()
    return ok([
        f"{p} 营业收入是多少",
        f"{p} 各产品线毛利率",
        f"{p} 哪个大区收入最高",
        f"{p} 账龄分布",
        f"{p} 期间费用按科目类别拆开",
        "为什么毛利率比上月下降",
    ])
