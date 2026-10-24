"""期间、数据版本等公共上下文。"""
from __future__ import annotations

from datetime import datetime

from .. import db
from ..config import settings

_cache: dict[str, object] = {}


def available_periods() -> list[str]:
    cached = _cache.get("periods")
    if cached:
        return cached  # type: ignore[return-value]
    rows = db.query("""SELECT DISTINCT "月份" AS m FROM "V_月度经营总览" ORDER BY 1 DESC""")
    periods = [r["m"] for r in rows]
    _cache["periods"] = periods
    return periods


def latest_period() -> str:
    periods = available_periods()
    return periods[0] if periods else settings.default_period


def resolve_period(period: str | None) -> str:
    if not period or period == "latest":
        return latest_period()
    if len(period) != 7 or period[4] != "-":
        from ..response import ApiError
        raise ApiError(40001, "period 格式应为 YYYY-MM")
    return period


def shift_period(period: str, months: int) -> str:
    y, m = int(period[:4]), int(period[5:7])
    idx = y * 12 + (m - 1) + months
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def period_status(period: str) -> dict:
    row = db.query_one("SELECT period, status, closed_at FROM app.fin_period WHERE period = %s", (period,))
    if not row:
        return {"period": period, "status": "open", "closedAt": None}
    return {
        "period": row["period"],
        "status": row["status"],
        "closedAt": row["closed_at"].isoformat() if row["closed_at"] else None,
    }


def data_version() -> str:
    """数据版本戳：取数据层最大业务月份 + 应用层最近刷新时间，供前端展示「数据截至」。"""
    row = db.query_one("""SELECT max("月份") AS m FROM "V_月度经营总览" """)
    month = row["m"] if row else latest_period()
    return f"{month}"


def meta(period: str | None = None, **extra) -> dict:
    m = {
        "period": period,
        "dataVersion": data_version(),
        "serverTime": datetime.now().isoformat(timespec="seconds"),
    }
    m.update(extra)
    return m


def invalidate() -> None:
    _cache.clear()
