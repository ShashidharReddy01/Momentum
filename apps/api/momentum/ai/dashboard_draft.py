"""Phase 7.5 (spec §8): a dashboard from a sentence ("New with Mo").

"A dashboard for my implementations: go-lives next 90 days, slipping projects, waiting on
customer, RAID by severity" becomes a ``DashboardDraft``: a portfolio, whether it's the asker's
own projects, and widgets picked by key from the **recipes** (every role template's widgets,
``role_templates.recipes()``). Mo never writes a widget spec: the server binds the chosen recipes
to the portfolio by name exactly like a role template (``bind_template``), so a field or stage
the workspace doesn't have drops that widget with a note, and the numbers in the preview come
from ``query_v2.run_any`` as the asker. What Mo couldn't map is asked back. Nothing is saved:
Create posts the previewed dashboard (``POST /dashboards/from-draft``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai import prompts
from momentum.ai.context.tokens import safe
from momentum.ai.llm import LLM
from momentum.ai.portfolio_facts import resolve_portfolio
from momentum.ai.structured import extract
from momentum.ai.tools.base import ToolContext, ToolError
from momentum.core.context import Ctx
from momentum.core.errors import NotFound, ValidationFailed
from momentum.domain.dashboards import query_v2, role_templates
from momentum.domain.dashboards.schemas import QueryResultOut
from momentum.domain.dashboards.schemas_v2 import DashboardFilters
from momentum.domain.portfolios.service import list_portfolios

MAX_TEXT = 400
MAX_WIDGETS = 10


class DraftWidget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipe: str = Field(max_length=80, description="A widget key from the list")
    title: str | None = Field(default=None, max_length=120, description="Only to rename it")


class DashboardDraftModel(BaseModel):
    """What the model submits: a dashboard in recipe keys and names, or only a question."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="", max_length=120)
    portfolio: str | None = Field(default=None, max_length=200, description="A portfolio name")
    mine: bool = Field(default=False, description="Only the asker's own projects")
    widgets: list[DraftWidget] = Field(default_factory=list, max_length=MAX_WIDGETS)
    left_out: list[str] = Field(
        default_factory=list,
        max_length=6,
        description="Parts of the request no widget in the list can show, in the asker's words",
    )
    question: str | None = Field(default=None, max_length=300)


@dataclass
class PreviewWidget:
    kind: str
    title: str
    size: str
    spec: Any
    result: QueryResultOut | None
    recipe: str


@dataclass
class DashboardDraft:
    question: str | None = None
    options: list[str] = field(default_factory=list)
    name: str = ""
    description: str = ""
    portfolio_id: uuid.UUID | None = None
    portfolio: str | None = None
    filters: DashboardFilters | None = None
    widgets: list[PreviewWidget] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    left_out: list[str] = field(default_factory=list)


def recipe_lines() -> str:
    return "\n".join(
        f"- {key}: {w['title']} ({w['kind']})" for key, w in role_templates.recipes().items()
    )


async def _portfolio(
    session: AsyncSession, ctx: Ctx, name: str | None, portfolio_id: uuid.UUID | None
) -> tuple[uuid.UUID | None, str | None, list[str]]:
    """The portfolio the dashboard reads: named, the one the asker is on, or the only one with
    stages. (id, name, options to ask back with)."""
    visible = [p for p, _n in await list_portfolios(session, ctx)]
    if name:
        try:
            p = await resolve_portfolio(ToolContext(session=session, ctx=ctx, mode="dry_run"), name)
        except ToolError:
            return None, None, sorted(x.name for x in visible)
        return p.id, p.name, []
    if portfolio_id is not None:
        for p in visible:
            if p.id == portfolio_id:
                return p.id, p.name, []
    staged = [p for p in visible if p.stage_field_id is not None]
    if len(staged) == 1:
        return staged[0].id, staged[0].name, []
    return None, None, sorted(x.name for x in visible)


async def draft_dashboard(
    session: AsyncSession,
    llm: LLM,
    ctx: Ctx,
    text: str,
    *,
    portfolio_id: uuid.UUID | None = None,
) -> DashboardDraft:
    text = text.strip()
    if not text:
        raise ValidationFailed("Say what the dashboard should show first")
    if len(text) > MAX_TEXT:
        raise ValidationFailed(f"That's too long (at most {MAX_TEXT} characters)")
    names = sorted(p.name for p, _n in await list_portfolios(session, ctx))
    reference = "\n".join(
        [
            '<data source="workspace">',
            "Portfolios: " + (", ".join(safe(n) for n in names) or "none"),
            "Widgets you can use (key: title):",
            recipe_lines(),
            "</data>",
        ]
    )
    prompt = prompts.load("dashboard_draft")
    d = await extract(
        llm,
        ctx,
        prompt=prompt,
        system=prompt.body,
        user=f'{reference}\n<data source="request">{safe(text)}</data>',
        schema=DashboardDraftModel,
        description="Submit the dashboard draft, or a question to ask back.",
    )
    if d.question and not d.widgets:
        return DashboardDraft(question=d.question.strip())
    return await resolve(session, ctx, d, text, portfolio_id=portfolio_id)


async def resolve(
    session: AsyncSession,
    ctx: Ctx,
    d: DashboardDraftModel,
    text: str,
    *,
    portfolio_id: uuid.UUID | None = None,
) -> DashboardDraft:
    """The draft bound to the portfolio as the asker, with every widget's numbers."""
    pid, pname, options = await _portfolio(session, ctx, d.portfolio, portfolio_id)
    if pid is None:
        which = f'There\'s no portfolio "{d.portfolio}". ' if d.portfolio else ""
        return DashboardDraft(
            question=f"{which}Which portfolio should the dashboard read?", options=options
        )
    catalog = role_templates.recipes()
    notes: list[str] = []
    widgets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for w in d.widgets:
        key = w.recipe.strip().lower()
        recipe = catalog.get(key)
        if recipe is None:
            notes.append(f'Mo has no widget called "{w.recipe}".')
            continue
        if key in seen:
            continue
        seen.add(key)
        widgets.append({**recipe, "title": (w.title or "").strip() or recipe["title"], "_key": key})
    if not widgets:
        return DashboardDraft(
            question="Which of these should the dashboard show? Pick a few widgets.",
            options=[str(r["title"]) for r in list(catalog.values())[:12]],
            left_out=d.left_out,
            notes=notes,
        )
    filters: dict[str, Any] = {"portfolio_id": "$portfolio"}
    if d.mine:
        filters["owner"] = ["me"]
    name = d.name.strip() or f"{pname}: my view"
    template = {"name": name, "description": text, "filters": filters, "widgets": widgets}
    try:
        bound = await role_templates.bind_template(session, ctx, "mo", template, pid)
    except (ValidationFailed, NotFound) as e:
        return DashboardDraft(question=f"{e.detail} Which widgets should it have instead?")
    keys = {(w["title"], w["kind"]): w["_key"] for w in widgets}
    out = DashboardDraft(
        name=bound.name,
        description=text,
        portfolio_id=pid,
        portfolio=pname,
        filters=bound.filters,
        notes=notes + bound.notes,
        left_out=[x.strip() for x in d.left_out if x.strip()],
    )
    for bw in bound.widgets:
        result: QueryResultOut | None
        try:
            result = await query_v2.run_any(session, ctx, bw.kind, bw.spec, filters=bound.filters)
        except (ValidationFailed, NotFound) as e:
            out.notes.append(f'"{bw.title}" can\'t show numbers yet: {e.detail}')
            result = None
        out.widgets.append(
            PreviewWidget(
                bw.kind, bw.title, bw.size, bw.spec, result, keys.get((bw.title, bw.kind), "")
            )
        )
    return out


def canonical(d: DashboardDraft) -> dict[str, Any]:
    """The draft without ids, for an eval case to state exactly."""
    if d.question:
        return {"question": True}
    return {
        "portfolio": d.portfolio,
        "mine": bool(d.filters and d.filters.owner),
        "widgets": sorted(w.recipe for w in d.widgets),
    }
