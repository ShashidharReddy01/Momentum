"""Phase 7.5 (spec §8): Mo on portfolios and dashboards, all on request. Every endpoint reads as
the person and stores nothing: posting a brief or a handoff goes through the normal status-update
endpoints after the preview, and a drafted dashboard through ``POST /dashboards/from-draft``.

S75-11 adds the other plain-English filter surfaces and Catch me up here."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from momentum.ai import dashboard_draft, explain_chart, handoff, nl_filters, portfolio_brief
from momentum.ai import readiness_check as readiness_ai
from momentum.ai.router import require_llm
from momentum.api.deps import CtxDep, RuntimeDep, UowDep
from momentum.domain.dashboards.schemas import KindIn, QueryResultOut, VizIn
from momentum.domain.dashboards.schemas_v2 import AnySpec, DashboardFilters
from momentum.domain.portfolios.schemas import GateItemOut, ReadinessOut
from momentum.domain.status_updates.schemas import StatusUpdateIn
from momentum.reports.data import today_for

router = APIRouter(prefix="/ai", tags=["ai"])


# ---------------- portfolio brief ----------------


class BriefItemOut(BaseModel):
    kind: str
    text: str
    cites: list[str]
    project_ids: list[uuid.UUID]


class BriefOut(BaseModel):
    portfolio_id: uuid.UUID
    portfolio: str
    headline: str
    items: list[BriefItemOut]
    hidden: int = Field(description="Projects in the portfolio the viewer can't see (not named)")
    ai: bool = Field(description="False when nothing needed Mo (no model call)")
    status_update: StatusUpdateIn = Field(
        description="The brief as a portfolio status update, for the preview to confirm"
    )


@router.post(
    "/portfolios/{portfolio_id}/brief",
    response_model=BriefOut,
    summary="Brief me on a portfolio: slipping, bottleneck, waiting, decisions (stores nothing)",
)
async def ai_portfolio_brief(
    portfolio_id: uuid.UUID, ctx: CtxDep, uow: UowDep, rt: RuntimeDep
) -> BriefOut:
    llm = require_llm(rt)
    ctx = ctx.with_(via="ai")
    async with uow.transaction() as s:
        b = await portfolio_brief.brief(s, llm, ctx, portfolio_id)
    return BriefOut(
        portfolio_id=b.portfolio_id,
        portfolio=b.portfolio,
        headline=b.headline,
        items=[
            BriefItemOut(kind=i.kind, text=i.text, cites=i.cites, project_ids=i.project_ids)
            for i in b.items
        ],
        hidden=b.hidden,
        ai=b.ai,
        status_update=b.status_update(today_for(ctx)),
    )


# ---------------- plain-English filters ----------------


class FiltersIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=nl_filters.MAX_TEXT)
    surface: nl_filters.Surface
    portfolio_id: uuid.UUID | None = None


class ChipOut(BaseModel):
    key: str
    label: str


class FilterDraftOut(BaseModel):
    surface: str
    filters: dict[str, Any] = Field(description="In the surface's own filter schema")
    chips: list[ChipOut]
    question: str | None = None
    options: list[str] = Field(default_factory=list, description="Real options to pick from")


@router.post(
    "/filters",
    response_model=FilterDraftOut,
    summary="Turn a sentence into the view's filters (nothing applies until Apply)",
)
async def ai_filters(body: FiltersIn, ctx: CtxDep, uow: UowDep, rt: RuntimeDep) -> FilterDraftOut:
    llm = require_llm(rt)
    ctx = ctx.with_(via="ai")
    async with uow.transaction() as s:
        d = await nl_filters.draft_filters(
            s, llm, ctx, body.text, body.surface, portfolio_id=body.portfolio_id
        )
    return FilterDraftOut(
        surface=d.surface,
        filters=d.filters,
        chips=[ChipOut(key=c.key, label=c.label) for c in d.chips],
        question=d.question,
        options=d.options,
    )


# ---------------- dashboard from a sentence ----------------


class DashboardDraftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=dashboard_draft.MAX_TEXT)
    portfolio_id: uuid.UUID | None = Field(
        default=None, description="The portfolio the person is on, if any"
    )


class DraftWidgetOut(BaseModel):
    kind: KindIn
    title: str
    query_spec: AnySpec
    viz: VizIn
    result: QueryResultOut | None


class DashboardDraftOut(BaseModel):
    question: str | None = None
    options: list[str] = Field(default_factory=list)
    name: str = ""
    description: str = ""
    portfolio_id: uuid.UUID | None = None
    portfolio: str | None = None
    filters: DashboardFilters | None = None
    widgets: list[DraftWidgetOut] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    left_out: list[str] = Field(
        default_factory=list, description="Parts of the sentence no widget can show"
    )


@router.post(
    "/dashboards/draft",
    response_model=DashboardDraftOut,
    summary="Draft a dashboard from a sentence, with real numbers (saves nothing)",
)
async def ai_dashboard_draft(
    body: DashboardDraftIn, ctx: CtxDep, uow: UowDep, rt: RuntimeDep
) -> DashboardDraftOut:
    llm = require_llm(rt)
    ctx = ctx.with_(via="ai")
    async with uow.transaction() as s:
        d = await dashboard_draft.draft_dashboard(
            s, llm, ctx, body.text, portfolio_id=body.portfolio_id
        )
    return DashboardDraftOut(
        question=d.question,
        options=d.options,
        name=d.name,
        description=d.description,
        portfolio_id=d.portfolio_id,
        portfolio=d.portfolio,
        filters=d.filters,
        widgets=[
            DraftWidgetOut(
                kind=w.kind,
                title=w.title,
                query_spec=w.spec,
                viz=VizIn.model_validate({"size": w.size}),
                result=w.result,
            )
            for w in d.widgets
        ],
        notes=d.notes,
        left_out=d.left_out,
    )


# ---------------- explain this chart ----------------


class ExplainIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filters: DashboardFilters | None = Field(
        default=None, description="The viewer's filters for this view (the saved ones if absent)"
    )


class ExplainParagraphOut(BaseModel):
    text: str
    cites: list[str]


class LinkOut(BaseModel):
    kind: Literal["task", "project"]
    id: uuid.UUID
    label: str


class ExplainOut(BaseModel):
    widget_id: uuid.UUID
    title: str
    paragraphs: list[ExplainParagraphOut]
    links: list[LinkOut] = Field(description="What's behind the biggest mark (Open the tasks)")
    sample_label: str | None = None
    ai: bool


@router.post(
    "/dashboards/widgets/{widget_id}/explain",
    response_model=ExplainOut,
    summary="Explain a chart: changes and outliers, from its own numbers (stores nothing)",
)
async def ai_explain_chart(
    widget_id: uuid.UUID, body: ExplainIn, ctx: CtxDep, uow: UowDep, rt: RuntimeDep
) -> ExplainOut:
    llm = require_llm(rt)
    ctx = ctx.with_(via="ai")
    async with uow.transaction() as s:
        e = await explain_chart.explain(s, llm, ctx, widget_id, filters=body.filters)
    return ExplainOut(
        widget_id=e.widget_id,
        title=e.title,
        paragraphs=[ExplainParagraphOut(text=p.text, cites=p.cites) for p in e.paragraphs],
        links=[LinkOut(kind=lk.kind, id=lk.id, label=lk.label) for lk in e.links],
        sample_label=e.sample_label,
        ai=e.ai,
    )


# ---------------- readiness check ----------------


class ReadinessCheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: str = Field(min_length=1, max_length=64, description="The stage option id")
    read_files: bool = Field(default=False, description="Also let Mo read the gate's files")


class ReadinessNoteOut(BaseModel):
    item: str
    text: str
    concern: bool
    cites: list[str]


class ReadinessCheckOut(BaseModel):
    project: str
    readiness: ReadinessOut
    notes: list[ReadinessNoteOut]
    files_read: list[str]
    unreadable: list[str]
    ai: bool


@router.post(
    "/portfolios/{portfolio_id}/projects/{project_id}/readiness",
    response_model=ReadinessCheckOut,
    summary="Check readiness for a stage: the gate's checklist, plus Mo's notes on its files "
    "when asked (stores nothing)",
)
async def ai_readiness(
    portfolio_id: uuid.UUID,
    project_id: uuid.UUID,
    body: ReadinessCheckIn,
    ctx: CtxDep,
    uow: UowDep,
    rt: RuntimeDep,
) -> ReadinessCheckOut:
    llm = require_llm(rt) if body.read_files else None
    ctx = ctx.with_(via="ai")
    async with uow.transaction() as s:
        r = await readiness_ai.check(
            s, llm, ctx, portfolio_id, project_id, body.to, read_files=body.read_files
        )
    g = r.readiness
    return ReadinessCheckOut(
        project=r.project,
        readiness=ReadinessOut(
            stage=g.stage,
            stage_label=g.stage_label,
            met=g.met,
            items=[GateItemOut(kind=i.kind, label=i.label, met=i.met, ref=i.ref) for i in g.items],
        ),
        notes=[
            ReadinessNoteOut(item=n.item, text=n.text, concern=n.concern, cites=n.cites)
            for n in r.notes
        ],
        files_read=r.files_read,
        unreadable=r.unreadable,
        ai=r.ai,
    )


# ---------------- handoff note ----------------


class HandoffIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to_stage: str | None = Field(default=None, max_length=100, description="The stage's name")
    read_files: bool = False


class HandoffItemOut(BaseModel):
    text: str
    cites: list[str]


class HandoffOut(BaseModel):
    project_id: uuid.UUID
    project: str
    to_stage: str | None
    sections: dict[str, list[HandoffItemOut]]
    files_read: list[str]
    status_update: StatusUpdateIn = Field(
        description="The note as a project status update, for the preview to confirm"
    )


@router.post(
    "/projects/{project_id}/handoff",
    response_model=HandoffOut,
    summary="Draft a handoff note for the next stage (stores nothing)",
)
async def ai_handoff(
    project_id: uuid.UUID, body: HandoffIn, ctx: CtxDep, uow: UowDep, rt: RuntimeDep
) -> HandoffOut:
    llm = require_llm(rt)
    ctx = ctx.with_(via="ai")
    async with uow.transaction() as s:
        h = await handoff.draft_handoff(
            s, llm, ctx, project_id, to_stage=body.to_stage, read_files=body.read_files
        )
    return HandoffOut(
        project_id=h.project_id,
        project=h.project,
        to_stage=h.to_stage,
        sections={
            k: [HandoffItemOut(text=i.text, cites=i.cites) for i in v]
            for k, v in h.sections.items()
        },
        files_read=h.files_read,
        status_update=h.status_update(),
    )
