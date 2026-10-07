"""Phase 7.5 (spec §8 "Ask the portfolio", §9.2): plain-English filters.

One sentence ("implementations going live in November that are at risk") becomes a draft in the
surface's **existing** filter schema; nothing is applied until the person clicks Apply. The model
works in names (people, stages, fields, options, health) and the server resolves them among what
the viewer can see; anything it can't resolve is asked back with the real options. Relative dates
("in November", "next 30 days") are resolved here, in the viewer's timezone, never by the model.

S75-10 built the engine for the portfolio surface; S75-11 adds the list, board, calendar,
My Tasks and search surfaces (``nl_filters_tasks``) on the same engine.
"""

from __future__ import annotations

import calendar
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai import prompts
from momentum.ai.context.tokens import safe
from momentum.ai.llm import LLM
from momentum.ai.structured import extract
from momentum.ai.tools.base import ToolContext, ToolError
from momentum.ai.tools.refs import resolve_person
from momentum.core.context import Ctx
from momentum.core.errors import ValidationFailed
from momentum.domain.fields.models import FieldDef
from momentum.domain.fields.project_values import list_project_field_defs
from momentum.domain.portfolios.models import Portfolio
from momentum.domain.portfolios.service import get_portfolio
from momentum.domain.status_updates.service import STATUS_LABELS
from momentum.domain.users.service import list_users
from momentum.reports.data import today_for

MAX_TEXT = 300
Surface = Literal["portfolio", "list", "board", "calendar", "my_tasks", "search"]
Health = Literal["on_track", "at_risk", "off_track", "on_hold", "complete", "none"]
MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS |= {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
RELATIVE = re.compile(r"^today\s*([+-])\s*(\d{1,3})\s*d?$")


class FieldCondDraft(BaseModel):
    """One project-field condition, in names."""

    model_config = ConfigDict(extra="forbid")
    field: str = Field(max_length=100, description="A project field name from the reference")
    is_any: list[str] = Field(
        default_factory=list, max_length=10, description="Option names or people's names"
    )
    in_month: str | None = Field(
        default=None, max_length=20, description='A month for a date field: "November"'
    )
    on_or_after: str | None = Field(
        default=None, max_length=20, description='YYYY-MM-DD, "today", "today+30" or a number'
    )
    on_or_before: str | None = Field(
        default=None, max_length=20, description='YYYY-MM-DD, "today", "today+30" or a number'
    )
    contains: str | None = Field(default=None, max_length=100, description="Text fields")
    has_value: bool | None = None


class PortfolioFilterDraft(BaseModel):
    """What the model submits for the portfolio surface: filters in names, or a question."""

    model_config = ConfigDict(extra="forbid")
    name_contains: str | None = Field(default=None, max_length=100)
    health: list[Health] = Field(default_factory=list, max_length=6)
    owners: list[str] = Field(default_factory=list, max_length=10, description='Names or "me"')
    stages: list[str] = Field(default_factory=list, max_length=12)
    fields: list[FieldCondDraft] = Field(default_factory=list, max_length=6)
    overdue_only: bool = False
    question: str | None = Field(
        default=None, max_length=300, description="Ask instead of guessing; leave the rest empty"
    )


class Ask(Exception):
    def __init__(self, question: str, options: list[str] | None = None) -> None:
        super().__init__(question)
        self.question = question
        self.options = options or []


@dataclass
class Chip:
    key: str
    label: str


@dataclass
class FilterDraft:
    surface: str
    filters: dict[str, Any] = field(default_factory=dict)  # the surface's own filter schema
    chips: list[Chip] = field(default_factory=list)
    named: dict[str, Any] = field(default_factory=dict)  # names, for evals and the UI
    question: str | None = None
    options: list[str] = field(default_factory=list)


def _labels(f: FieldDef) -> list[tuple[str, str]]:
    return [
        (str(o.get("label", "")), str(o["id"]))
        for o in f.options or []
        if isinstance(o, dict) and "id" in o
    ]


def resolve_day(raw: str, today: date, field_type: str) -> str | float:
    """A bound for a date or number field: ISO dates, "today[±N]" (the viewer's today), or a
    number. Raises ``Ask`` for anything else."""
    v = raw.strip().lower()
    if field_type == "date":
        if v == "today":
            return today.isoformat()
        m = RELATIVE.match(v)
        if m:
            n = int(m.group(2))
            return (today + timedelta(days=n if m.group(1) == "+" else -n)).isoformat()
        try:
            return date.fromisoformat(v[:10]).isoformat()
        except ValueError:
            raise Ask(f'I couldn\'t read "{raw}" as a date. Which day did you mean?') from None
    try:
        return float(v.replace(",", ""))
    except ValueError:
        raise Ask(f'I couldn\'t read "{raw}" as a number. Which value did you mean?') from None


def month_bounds(raw: str, today: date) -> tuple[date, date]:
    """ "November" → the next November (this year's if it hasn't ended); "2026-11" as given."""
    v = raw.strip().lower()
    m = re.match(r"^(\d{4})-(\d{1,2})$", v)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
    elif v in ("this month",):
        year, month = today.year, today.month
    elif v in ("next month",):
        year, month = (today.year + (today.month == 12), today.month % 12 + 1)
    else:
        name = v.split()[0] if v else ""
        if name not in MONTHS:
            raise Ask(f'Which month is "{raw}"?')
        month = MONTHS[name]
        year = today.year if month >= today.month else today.year + 1
        found = re.search(r"\b(\d{4})\b", v)
        if found:
            year = int(found.group(1))
    if not 1 <= month <= 12:
        raise Ask(f'Which month is "{raw}"?')
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


async def _reference(session: AsyncSession, ctx: Ctx, p: Portfolio) -> tuple[str, list[FieldDef]]:
    defs = await list_project_field_defs(session, ctx)
    stage = next((f for f in defs if f.id == p.stage_field_id), None)
    lines = [
        f"Portfolio: {safe(p.name)}",
        f"Today (the viewer's timezone): {today_for(ctx).isoformat()}",
        "Stages: "
        + (", ".join(safe(lb) for lb, _ in _labels(stage)) if stage else "none (no stage field)"),
        "Health: " + ", ".join(f"{k} ({v})" for k, v in STATUS_LABELS.items()) + ", none",
        "People: " + (", ".join(safe(u.name) for u in (await list_users(session, ctx))[:60])),
    ]
    described = []
    for f in defs:
        if stage is not None and f.id == stage.id:
            continue
        opts = _labels(f)
        kind = f.type.replace("_", "-")
        if opts:
            kind += ": " + ", ".join(safe(lb) for lb, _ in opts[:12])
        described.append(f"{safe(f.name)} ({kind})")
    lines.append("Project fields: " + ("; ".join(described[:40]) or "none"))
    return '<data source="workspace">\n' + "\n".join(lines) + "\n</data>", defs


async def resolve_portfolio_draft(
    session: AsyncSession, ctx: Ctx, p: Portfolio, d: PortfolioFilterDraft, defs: list[FieldDef]
) -> FilterDraft:
    """Names → the portfolio view's filters (``ViewFiltersIn``), with chips. Raises ``Ask``."""
    tc = ToolContext(session=session, ctx=ctx, mode="dry_run")
    today = today_for(ctx)
    out = FilterDraft(surface="portfolio")
    f: dict[str, Any] = {}
    by_name = {x.name.strip().lower(): x for x in defs}
    stage = next((x for x in defs if x.id == p.stage_field_id), None)

    if d.name_contains and d.name_contains.strip():
        f["q"] = d.name_contains.strip()
        out.chips.append(Chip("q", f"Name contains “{f['q']}”"))
        out.named["name_contains"] = f["q"]
    if d.health:
        f["status"] = list(dict.fromkeys(d.health))
        words = [STATUS_LABELS.get(h, "No status") for h in f["status"]]
        out.chips.append(Chip("status", "Health: " + ", ".join(words)))
        out.named["health"] = sorted(f["status"])
    if d.owners:
        ids, names = [], []
        for o in d.owners:
            try:
                u = await resolve_person(tc, o)
            except ToolError as e:
                people = [x.name for x in (await list_users(session, ctx))[:12]]
                raise Ask(e.message, people) from None
            ids.append(str(u.id))
            names.append("me" if o.strip().lower() in ("me", "myself", "mine", "i") else u.name)
        f["owner_ids"] = ids
        out.chips.append(Chip("owner_ids", "Owner: " + ", ".join(names)))
        out.named["owners"] = sorted(names)
    if d.stages:
        if stage is None:
            raise Ask(f"{p.name} has no stages to filter by.")
        stage_opts = {lb.lower(): (lb, oid) for lb, oid in _labels(stage)}
        picked = []
        for s in d.stages:
            hit = stage_opts.get(s.strip().lower())
            if hit is None:
                stage_labels = [lb for lb, _ in _labels(stage)]
                raise Ask(
                    f'There\'s no stage "{s.strip()}". Which stage did you mean?', stage_labels
                )
            picked.append(hit)
        f["stage"] = [oid for _lb, oid in picked]
        out.chips.append(Chip("stage", "Stage: " + ", ".join(lb for lb, _ in picked)))
        out.named["stages"] = sorted(lb for lb, _ in picked)
    conds: list[dict[str, Any]] = []
    named_fields: list[dict[str, Any]] = []
    for c in d.fields:
        target = by_name.get(c.field.strip().lower())
        if target is None or (stage is not None and target.id == stage.id):
            if stage is not None and target is not None:  # the stage field: use stages
                raise Ask("Say which stages instead (for example: in Implementation).")
            listed = [x.name for x in defs if stage is None or x.id != stage.id]
            raise Ask(f'There\'s no project field "{c.field.strip()}". Which did you mean?', listed)
        nf: dict[str, Any] = {"field": target.name}
        labels: list[str] = []
        if c.contains:
            raise Ask(f'Portfolio views can\'t search inside "{target.name}" yet.')
        if c.is_any:
            values: list[str] = []
            opts = {lb.lower(): oid for lb, oid in _labels(target)}
            for word in c.is_any:
                w = word.strip()
                if target.type == "people":
                    try:
                        values.append(str((await resolve_person(tc, w)).id))
                    except ToolError as e:
                        raise Ask(e.message) from None
                elif w.lower() in opts:
                    values.append(opts[w.lower()])
                else:
                    raise Ask(
                        f'"{target.name}" has no option "{w}". Which did you mean?',
                        [lb for lb, _ in _labels(target)],
                    )
                labels.append(w)
            conds.append({"field_id": str(target.id), "op": "any", "value": values})
            nf["is_any"] = sorted(labels)
        lo: str | float | None = None
        hi: str | float | None = None
        if c.in_month:
            if target.type != "date":
                raise Ask(f'"{target.name}" isn\'t a date field.')
            a, b = month_bounds(c.in_month, today)
            lo, hi = a.isoformat(), b.isoformat()
            nf["in_month"] = calendar.month_name[a.month]
        if c.on_or_after:
            lo = resolve_day(c.on_or_after, today, target.type)
            nf["on_or_after"] = c.on_or_after.strip().lower()
        if c.on_or_before:
            hi = resolve_day(c.on_or_before, today, target.type)
            nf["on_or_before"] = c.on_or_before.strip().lower()
        if lo is not None:
            conds.append({"field_id": str(target.id), "op": "gte", "value": lo})
        if hi is not None:
            conds.append({"field_id": str(target.id), "op": "lte", "value": hi})
        if c.has_value is not None:
            conds.append({"field_id": str(target.id), "op": "set" if c.has_value else "empty"})
            nf["has_value"] = c.has_value
        if len(nf) == 1:
            raise Ask(f'What should "{target.name}" be?')
        named_fields.append(nf)
        if labels:
            what = ", ".join(labels)
        elif lo is not None and hi is not None:
            what = f"{_show(lo)} to {_show(hi)}"
        elif lo is not None:
            what = f"from {_show(lo)}"
        elif hi is not None:
            what = f"until {_show(hi)}"
        else:
            what = "has a value" if c.has_value else "empty"
        out.chips.append(Chip(f"field:{target.id}", f"{target.name}: {what}"))
    if conds:
        f["fields"] = conds
        out.named["fields"] = named_fields
    if d.overdue_only:
        f["overdue_only"] = True
        out.chips.append(Chip("overdue_only", "Overdue work only"))
        out.named["overdue_only"] = True
    if not f:
        raise Ask("What should the view show? For example: at risk projects in Implementation.")
    out.filters = f
    return out


def _show(v: str | float) -> str:
    if isinstance(v, str):
        return date.fromisoformat(v).strftime("%d %b %Y").lstrip("0")
    return f"{v:g}"


async def draft_filters(
    session: AsyncSession,
    llm: LLM,
    ctx: Ctx,
    text: str,
    surface: Surface,
    *,
    portfolio_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
) -> FilterDraft:
    text = text.strip()
    if not text:
        raise ValidationFailed("Describe what to show first")
    if len(text) > MAX_TEXT:
        raise ValidationFailed(f"That's too long (at most {MAX_TEXT} characters)")
    if surface != "portfolio":
        return await _draft_tasks(session, llm, ctx, text, surface, project_id)
    if portfolio_id is None:
        raise ValidationFailed("Say which portfolio to filter")
    p = await get_portfolio(session, ctx, portfolio_id)
    reference, defs = await _reference(session, ctx, p)
    prompt = prompts.load("filters")
    d = await extract(
        llm,
        ctx,
        prompt=prompt,
        system=prompt.body,
        user=f'{reference}\n<data source="request" surface="portfolio">{safe(text)}</data>',
        schema=PortfolioFilterDraft,
        description="Submit the filters, or a question to ask back.",
    )
    empty = not (d.name_contains or d.health or d.owners or d.stages or d.fields or d.overdue_only)
    if d.question and empty:
        return FilterDraft(surface=surface, question=d.question.strip())
    try:
        return await resolve_portfolio_draft(session, ctx, p, d, defs)
    except Ask as ask:
        return FilterDraft(surface=surface, question=ask.question, options=ask.options[:20])


async def _draft_tasks(
    session: AsyncSession,
    llm: LLM,
    ctx: Ctx,
    text: str,
    surface: str,
    project_id: uuid.UUID | None,
) -> FilterDraft:
    from momentum.ai import nl_filters_tasks as tasks

    if surface in tasks.PROJECT_SURFACES and project_id is None:
        raise ValidationFailed("Say which project's view to filter")
    reference, defs = await tasks.reference(session, ctx, surface, project_id)
    prompt = prompts.load("filters")
    d = await extract(
        llm,
        ctx,
        prompt=prompt,
        system=prompt.body,
        user=f'{reference}\n<data source="request" surface="{surface}">{safe(text)}</data>',
        schema=tasks.TaskFilterDraft,
        description="Submit the filters, or a question to ask back.",
    )
    if d.question and d.empty():
        return FilterDraft(surface=surface, question=d.question.strip())
    try:
        return await tasks.resolve_task_draft(session, ctx, surface, d, defs, project_id)
    except Ask as ask:
        return FilterDraft(surface=surface, question=ask.question, options=ask.options[:20])
