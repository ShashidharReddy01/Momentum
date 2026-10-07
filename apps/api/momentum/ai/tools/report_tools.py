"""Phase 7.5 (spec §6.3): Mo's ``generate_report`` (risk low; preview → confirm → apply → undo).

The preview shows the report's outline (built as the person, no file); applying makes the file
(as the person, with the narrative) and returns its link; undo deletes it.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select

from momentum.ai.tools.base import ToolContext, ToolResult, tool
from momentum.ai.tools.refs import resolve_project
from momentum.core.errors import Forbidden, NotFound, ValidationFailed
from momentum.core.storage import build_storage
from momentum.domain.dashboards.models import Dashboard
from momentum.domain.portfolios.models import Portfolio
from momentum.domain.portfolios.service import get_portfolio
from momentum.domain.reports import service as reports
from momentum.reports.data import today_for
from momentum.reports.spec import FORMATS, SCOPES, Audience, Format, Kind, ReportSpec

WRITE = ("tasks:write",)
KIND_WORDS = {
    "project_status": "status report",
    "portfolio_status": "portfolio status report",
    "task_export": "task export",
    "customer_status": "customer status report",
    "closeout": "close-out report",
    "dashboard": "dashboard report",
}


class GenerateReportArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Kind
    project: str | None = Field(default=None, max_length=200, description="Project name or id")
    portfolio: str | None = Field(default=None, max_length=200, description="Portfolio name")
    dashboard: str | None = Field(default=None, max_length=200, description="Dashboard name")
    format: Format | None = Field(default=None, description="Default: the kind's first format")
    period_days: int | None = Field(
        default=None, ge=1, le=366, description="The last N days (status reports; default 7)"
    )
    narrative: bool | None = Field(default=None, description="Add Mo's marked summary")
    audience: Audience | None = None


async def _by_name(tc: ToolContext, model: Any, name: str) -> Any:
    rows = list(
        (
            await tc.session.execute(
                select(model).where(
                    model.workspace_id == tc.ctx.workspace_id,
                    model.deleted_at.is_(None),
                    func.lower(model.name) == name.strip().lower(),
                )
            )
        ).scalars()
    )
    return rows[0] if len(rows) == 1 else None


async def _spec(tc: ToolContext, args: GenerateReportArgs) -> ReportSpec:
    scope: dict[str, Any] = {}
    allowed = SCOPES[args.kind]
    if "project" in allowed and args.project:
        project, _role = await resolve_project(tc, args.project)
        scope["project_id"] = str(project.id)
    elif "portfolio" in allowed and args.portfolio:
        p = await _by_name(tc, Portfolio, args.portfolio)
        if p is None:
            raise NotFound(f'No portfolio named "{args.portfolio}"')
        await get_portfolio(tc.session, tc.ctx, p.id)  # visible to the person
        scope["portfolio_id"] = str(p.id)
    elif "dashboard" in allowed and args.dashboard:
        d = await _by_name(tc, Dashboard, args.dashboard)
        if d is None:
            raise NotFound(f'No dashboard named "{args.dashboard}"')
        scope["dashboard_id"] = str(d.id)
    else:
        raise ValidationFailed(f"Say which {' or '.join(allowed)} the report is about")
    raw: dict[str, Any] = {
        "kind": args.kind,
        "scope": scope,
        "format": args.format or FORMATS[args.kind][0],
    }
    if args.period_days:
        today = today_for(tc.ctx)
        raw["period"] = {
            "from": (today - timedelta(days=args.period_days - 1)).isoformat(),
            "to": today.isoformat(),
        }
    if args.narrative is not None:
        raw["narrative"] = args.narrative
    if args.audience is not None:
        raw["audience"] = args.audience
    try:
        return ReportSpec.model_validate(raw)
    except ValidationError as e:
        raise ValidationFailed(str(e.errors()[0].get("msg", "invalid report"))) from None


@tool(
    name="generate_report",
    description=(
        "Make a report file from Momentum's data (status of a project or portfolio, a customer "
        "update, a close-out, a task export, or a dashboard) as docx, pdf, xlsx, md or csv. The "
        "preview shows the outline; applying makes the file in the project's or portfolio's files."
    ),
    risk="low",
    scopes=WRITE,
)
async def generate_report(tc: ToolContext, args: GenerateReportArgs) -> ToolResult:
    try:
        spec = await _spec(tc, args)
        if tc.preview:
            out = await reports.preview(tc.session, tc.ctx, spec)
            return ToolResult.success(
                f"Would make a {KIND_WORDS[spec.kind]} ({spec.format}): {out['title']}",
                {
                    "title": out["title"],
                    "format": spec.format,
                    "outline": [i["title"] for i in out["items"]],
                    "pages": out["pages"],
                },
                targets=[{"type": "report", "kind": spec.kind}],
            )
        from momentum.ai.report_narrative import make_narrator

        run = await reports.request_report(tc.session, tc.ctx, spec, via="ai")
        run = await reports.execute(
            tc.session,
            tc.ctx,
            run,
            storage=build_storage(tc.ctx.settings),
            narrator=make_narrator(tc.llm, tc.ctx.settings) if tc.llm else None,
            timeout_s=tc.ctx.settings.report_timeout_s,
            batch_id=tc.batch_id,
        )
    except (NotFound, Forbidden, ValidationFailed) as e:
        return ToolResult.failure(e.code or "invalid", e.detail)
    if run.status != "done" or run.attachment_id is None:
        return ToolResult.failure("report_failed", run.error or "The report could not be made")
    return ToolResult.success(
        f"Made the {KIND_WORDS[spec.kind]}",
        {
            "attachment_id": str(run.attachment_id),
            "download": f"/api/v1/attachments/{run.attachment_id}/download",
        },
        targets=[{"type": "attachment", "id": str(run.attachment_id)}],
    )


TOOLS = [generate_report]
