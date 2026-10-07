"""Phase 7.5 (spec §8): Mo's portfolio v2 read tools (risk ``read``), as the viewer.

- ``get_portfolio_rows``: the portfolio table's rows (stage, days in stage vs target, progress,
  overdue, blocked, waiting on customer, target vs forecast, slip, next milestone, latest update),
  with optional view filters by name.
- ``get_stage_metrics``: the lifecycle funnel, time in stage vs target, aging and the bottleneck.

Both share ``ai/portfolio_facts.py`` with the portfolio brief, so a chat answer and a brief count
the same way as the table and the stage widgets.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from momentum.ai.portfolio_facts import resolve_portfolio, row_facts, stage_facts
from momentum.ai.tools.base import ToolContext, ToolError, ToolResult, tool
from momentum.ai.tools.refs import resolve_person
from momentum.domain.fields.models import FieldDef
from momentum.reports.data import today_for

READ = ("tasks:read",)
Health = Literal["on_track", "at_risk", "off_track", "on_hold", "complete", "none"]


class GetPortfolioRowsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    portfolio: str = Field(max_length=200, description="Portfolio name or id")
    health: list[Health] = Field(default_factory=list, max_length=6)
    stages: list[str] = Field(
        default_factory=list, max_length=12, description="Stage names (the portfolio's stages)"
    )
    owner: str | None = Field(default=None, max_length=200, description='"me" or a name')
    overdue_only: bool = False
    slipping_only: bool = Field(default=False, description="Forecast later than target")
    waiting_on_customer_only: bool = False
    limit: int = Field(default=40, ge=1, le=60)


@tool(
    name="get_portfolio_rows",
    description=(
        "A portfolio's projects as its table shows them: stage, days in stage vs target, health, "
        "progress, open/overdue/blocked tasks, waiting on customer, target vs forecast date, "
        "slip days, next milestone and latest update. Filter by health, stage names, owner, "
        "overdue, slipping or waiting on the customer."
    ),
    risk="read",
    scopes=READ,
)
async def get_portfolio_rows(tc: ToolContext, args: GetPortfolioRowsArgs) -> ToolResult:
    s, ctx = tc.session, tc.ctx
    p = await resolve_portfolio(tc, args.portfolio)
    filters: dict[str, object] = {}
    if args.health:
        filters["status"] = list(args.health)
    if args.stages:
        stage = await s.get(FieldDef, p.stage_field_id) if p.stage_field_id else None
        if stage is None:
            raise ToolError("invalid", f"{p.name} has no stages")
        opts = {
            str(o.get("label", "")).lower(): str(o["id"])
            for o in stage.options or []
            if isinstance(o, dict)
        }
        ids = []
        for name in args.stages:
            oid = opts.get(name.strip().lower())
            if oid is None:
                listed = ", ".join(str(o.get("label")) for o in stage.options or [])
                raise ToolError("not_found", f'No stage "{name}" (stages: {listed})')
            ids.append(oid)
        filters["stage"] = ids
    if args.owner:
        filters["owner_ids"] = [str((await resolve_person(tc, args.owner)).id)]
    if args.overdue_only:
        filters["overdue_only"] = True
    rows, hidden, _raw = await row_facts(s, ctx, p, filters, today=today_for(ctx))
    if args.slipping_only:
        rows = [r for r in rows if (r.get("slip_days") or 0) > 0]
    if args.waiting_on_customer_only:
        rows = [r for r in rows if (r.get("waiting_on_customer") or 0) > 0]
    data: dict[str, object] = {"portfolio": p.name, "projects": rows[: args.limit]}
    if len(rows) > args.limit:
        data["more"] = len(rows) - args.limit
    if hidden:
        data["projects_you_cannot_see"] = hidden
    return ToolResult.success(f"{p.name}: {len(rows)} projects", data)


class GetStageMetricsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    portfolio: str = Field(max_length=200, description="Portfolio name or id")
    window_days: int = Field(default=90, ge=7, le=730, description="Look back this many days")


@tool(
    name="get_stage_metrics",
    description=(
        "Lifecycle numbers of a portfolio with stages: the funnel (projects reaching each stage, "
        "conversion), time in stage (median and 90th percentile days vs the target), aging (how "
        "long projects have been in their stage now, how many are past target) and the "
        "bottleneck stage."
    ),
    risk="read",
    scopes=READ,
)
async def get_stage_metrics(tc: ToolContext, args: GetStageMetricsArgs) -> ToolResult:
    p = await resolve_portfolio(tc, args.portfolio)
    facts = await stage_facts(tc.session, tc.ctx, p, args.window_days)
    if not facts:
        raise ToolError("invalid", f"{p.name} has no stage field, so it has no stage metrics")
    return ToolResult.success(f"{p.name}: stage metrics", {"portfolio": p.name, **facts})


TOOLS = [get_portfolio_rows, get_stage_metrics]
