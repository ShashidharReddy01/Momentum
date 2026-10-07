"""Phase 7.5 (spec §8): what Mo knows about a portfolio, computed in code as the viewer.

The read tools (``get_portfolio_rows``, ``get_stage_metrics``) and the portfolio brief share these
functions, so an answer in chat and a brief count the same way as the portfolio table and the
stage widgets: rows come from ``portfolio_rows_v2`` and stage numbers from ``run_stages``. Hidden
projects (in the portfolio, not visible to the viewer) are only counted, never named.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai.tools.base import ToolContext, ToolError
from momentum.core.context import Ctx
from momentum.core.errors import ValidationFailed
from momentum.domain.dashboards.query_stages import run_stages
from momentum.domain.dashboards.schemas_v2 import AGING_BUCKETS, StageSpec
from momentum.domain.portfolios.models import Portfolio
from momentum.domain.portfolios.rows import ViewSpec, portfolio_rows_v2
from momentum.domain.portfolios.service import get_portfolio, list_portfolios
from momentum.domain.status_updates.service import STATUS_LABELS

MAX_ROWS = 60  # rows a tool or a brief shows the model
STALE_UPDATE_DAYS = 14


async def resolve_portfolio(tc: ToolContext, value: str) -> Portfolio:
    """A portfolio the viewer can see, by id or name (exact, then partial)."""
    try:
        pid: uuid.UUID | None = uuid.UUID(value.strip())
    except ValueError:
        pid = None
    visible = [p for p, _n in await list_portfolios(tc.session, tc.ctx)]
    if pid is not None:
        for p in visible:
            if p.id == pid:
                return p
        raise ToolError("not_found", f"No portfolio with id {pid} that you can see")
    v = " ".join(value.split()).lower()
    exact = [p for p in visible if p.name.lower() == v]
    pool = exact or [p for p in visible if v in p.name.lower()]
    if len(pool) == 1:
        return pool[0]
    if not pool:
        names = ", ".join(sorted(p.name for p in visible)[:10]) or "none"
        raise ToolError(
            "not_found", f'No portfolio named "{value}" that you can see (portfolios: {names})'
        )
    raise ToolError(
        "ambiguous",
        f'"{value}" matches {len(pool)} portfolios; ask the user which one they mean',
        candidates=[{"id": str(p.id), "name": p.name} for p in pool[:8]],
    )


def _day(v: Any) -> str | None:
    return v.isoformat() if isinstance(v, date) else None


def compact_row(r: dict[str, Any]) -> dict[str, Any]:
    """One portfolio row as the model sees it: the table's numbers, no ids."""
    out: dict[str, Any] = {
        "name": r["name"],
        "owner": r.get("owner_name"),
        "health": STATUS_LABELS.get(r.get("status") or "", "no status yet"),
        "stage": (r.get("stage") or {}).get("label"),
        "days_in_stage": r.get("stage_age_days"),
        "stage_target_days": r.get("stage_target_days"),
        "progress_pct": round(100 * r["progress"]) if r.get("progress") is not None else None,
        "open": r.get("open"),
        "overdue": r.get("overdue"),
        "blocked": r.get("blocked"),
        "waiting_on_customer": r.get("waiting_on_customer"),
        "target_date": _day(r.get("target_date")),
        "forecast_date": _day(r.get("forecast_date")),
        "slip_days": r.get("slip_days"),
    }
    m = r.get("next_milestone")
    if m:
        out["next_milestone"] = {"title": m["title"], "due_on": _day(m.get("due_on"))}
    u = r.get("latest_update")
    if u:
        out["latest_update"] = {"title": u["title"], "on": _day(u["at"].date())}
    return {k: v for k, v in out.items() if v is not None}


async def row_facts(
    session: AsyncSession,
    ctx: Ctx,
    p: Portfolio,
    filters: dict[str, Any] | None = None,
    *,
    today: date | None = None,
) -> tuple[list[dict[str, Any]], int, list[dict[str, Any]]]:
    """(compact rows, hidden count, the raw rows) for the viewer, with optional view filters."""
    rows = await portfolio_rows_v2(session, ctx, p, ViewSpec(filters=filters or {}), today=today)
    return [compact_row(r) for r in rows.rows[:MAX_ROWS]], rows.hidden, rows.rows


async def stage_facts(
    session: AsyncSession, ctx: Ctx, p: Portfolio, window_days: int = 90
) -> dict[str, Any]:
    """Funnel, time in stage (vs target) and aging, over the portfolio's stage field; plus the
    bottleneck: the stage whose median time most exceeds its target. Empty without a stage."""
    if p.stage_field_id is None:
        return {}
    spec = {"version": 2, "entity": "stage_events", "portfolio_id": p.id}
    try:
        funnel = await run_stages(
            session,
            ctx,
            "funnel",
            StageSpec.model_validate({**spec, "analysis": "funnel", "window_days": window_days}),
        )
        tis = await run_stages(
            session,
            ctx,
            "bar",
            StageSpec.model_validate(
                {**spec, "analysis": "time_in_stage", "window_days": window_days}
            ),
        )
        aging = await run_stages(
            session, ctx, "table", StageSpec.model_validate({**spec, "analysis": "aging"})
        )
    except ValidationFailed:
        return {}
    labels = [f"{lo}-{hi}" if hi is not None else f"{lo}+" for lo, hi in AGING_BUCKETS]
    out: dict[str, Any] = {
        "window_days": window_days,
        "funnel": [
            {
                "stage": s.label,
                "reached": s.count,
                **({"conversion_pct": round(100 * s.conversion)} if s.conversion else {}),
            }
            for s in funnel.stages
        ],
        "time_in_stage": [
            {
                "stage": s.label,
                "stays": s.count,
                "median_days": s.median_days,
                "p90_days": s.p90_days,
                "target_days": s.target_days,
            }
            for s in tis.stages
            if s.count
        ],
        "aging": [
            {
                "stage": s.label,
                "projects": s.count,
                "past_target": s.breaches,
                "target_days": s.target_days,
                "by_days": dict(zip(labels, s.buckets or [], strict=False)),
            }
            for s in aging.stages
            if s.count
        ],
    }
    worst: tuple[float, str] | None = None
    for s in tis.stages:
        if s.median_days is not None and s.target_days:
            ratio = s.median_days / s.target_days
            if ratio > 1 and (worst is None or ratio > worst[0]):
                worst = (ratio, s.label)
    if worst is not None:
        st = next(x for x in tis.stages if x.label == worst[1])
        out["bottleneck"] = {
            "stage": st.label,
            "median_days": st.median_days,
            "target_days": st.target_days,
        }
    return out


def brief_facts(
    p: Portfolio,
    rows: list[dict[str, Any]],
    hidden: int,
    stages: dict[str, Any],
    today: date,
) -> dict[str, Any]:
    """What a portfolio brief may say, sorted into the spec §8 buckets (computed here, so the
    model only words them)."""
    slipping = sorted(
        (r for r in rows if (r.get("slip_days") or 0) > 0), key=lambda r: -r["slip_days"]
    )
    over_target = [
        r
        for r in rows
        if r.get("days_in_stage") is not None
        and r.get("stage_target_days")
        and r["days_in_stage"] > r["stage_target_days"]
    ]
    waiting_customer = [r for r in rows if (r.get("waiting_on_customer") or 0) > 0]
    waiting_us = [r for r in rows if (r.get("overdue") or 0) > 0 or (r.get("blocked") or 0) > 0]
    decisions = []
    for r in rows:
        why = []
        if r.get("health") in ("Off track", "At risk"):
            why.append(f"health is {r['health']}")
        upd = r.get("latest_update")
        if upd is None:
            why.append("no status update yet")
        elif (today - date.fromisoformat(upd["on"])).days > STALE_UPDATE_DAYS:
            why.append(f"last update {upd['on']}")
        if why and r.get("health") != "Complete":
            decisions.append({"name": r["name"], "why": why})

    def pick(rs: list[dict[str, Any]], *keys: str) -> list[dict[str, Any]]:
        return [
            {"name": r["name"], **{k: r.get(k) for k in keys if r.get(k) is not None}} for r in rs
        ]

    return {
        "portfolio": p.name,
        "today": today.isoformat(),
        "projects_shown": len(rows),
        "projects_hidden": hidden,
        "slipping": pick(slipping[:10], "stage", "slip_days", "forecast_date", "target_date"),
        "over_stage_target": pick(over_target[:10], "stage", "days_in_stage", "stage_target_days"),
        "bottleneck": stages.get("bottleneck"),
        "waiting_on_customer": pick(waiting_customer[:10], "stage", "waiting_on_customer"),
        "waiting_on_us": pick(waiting_us[:10], "stage", "overdue", "blocked"),
        "decisions_needed": decisions[:10],
        "funnel": stages.get("funnel", []),
    }


async def portfolio_by_id(session: AsyncSession, ctx: Ctx, portfolio_id: uuid.UUID) -> Portfolio:
    return await get_portfolio(session, ctx, portfolio_id)
