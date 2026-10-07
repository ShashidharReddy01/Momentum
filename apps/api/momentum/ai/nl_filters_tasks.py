"""Phase 7.5 (spec §9.2): plain-English filters for the task surfaces, on the engine in
``nl_filters`` (S75-10 built it for portfolios).

- ``list`` / ``board`` / ``calendar``: a project's ``ProjectViewPrefs`` filters (assignees, tags,
  due, show completed, field filters, sort, group);
- ``my_tasks``: show completed and field filters (My Tasks groups by due itself);
- ``search``: the search page's params (words, type, project, assignee, completed, field filters).

The model answers in names; people, tags, projects, fields and options are resolved among what the
viewer can see (custom-field conditions through the same code as "Ask for a chart"), relative
dates in the viewer's timezone. What a surface can't filter by is asked back, never dropped.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai import chart
from momentum.ai.chart import ChartFieldFilter
from momentum.ai.context.tokens import safe
from momentum.ai.nl_filters import (
    Ask,
    Chip,
    FieldCondDraft,
    FilterDraft,
    month_bounds,
    resolve_day,
)
from momentum.ai.tools.base import ToolContext, ToolError
from momentum.ai.tools.refs import resolve_person, resolve_project
from momentum.core.context import Ctx
from momentum.domain.access import get_visible_project
from momentum.domain.fields.models import FieldDef
from momentum.domain.fields.service import list_project_fields
from momentum.domain.tags.service import list_tags
from momentum.domain.users.service import list_users
from momentum.reports.data import today_for

PROJECT_SURFACES = ("list", "board", "calendar")
Due = Literal["any", "overdue", "today", "this_week", "next_week", "no_date"]
DUE_WORDS = {
    "overdue": "Overdue",
    "today": "Due today",
    "this_week": "Due this week",
    "next_week": "Due next week",
    "no_date": "No due date",
}
UNASSIGNED = {"none", "nobody", "unassigned", "no one", "no assignee"}
ME = {"me", "myself", "mine", "i"}


class TaskFilterDraft(BaseModel):
    """What the model submits for a task surface: filters in names, or a question."""

    model_config = ConfigDict(extra="forbid")
    words: str | None = Field(default=None, max_length=100, description="Search words (search)")
    people: list[str] = Field(
        default_factory=list, max_length=10, description='Assignees: names, "me" or "unassigned"'
    )
    tags: list[str] = Field(default_factory=list, max_length=10)
    due: Due | None = None
    show_completed: bool | None = None
    completed: Literal["open", "completed", "any"] | None = Field(
        default=None, description="Search: open (the default), completed or any"
    )
    project: str | None = Field(default=None, max_length=200, description="Search: one project")
    types: list[Literal["task", "project", "person", "comment"]] = Field(
        default_factory=list, max_length=4, description="Search: what kinds of results"
    )
    fields: list[FieldCondDraft] = Field(default_factory=list, max_length=6)
    sort: Literal["manual", "due", "assignee", "created", "title"] | None = None
    group: Literal["section", "assignee", "due"] | None = None
    question: str | None = Field(
        default=None, max_length=300, description="Ask instead of guessing; leave the rest empty"
    )

    def empty(self) -> bool:
        return not (
            self.words
            or self.people
            or self.tags
            or self.due
            or self.show_completed is not None
            or self.completed
            or self.project
            or self.types
            or self.fields
            or self.sort
            or self.group
        )


async def _task_fields(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID | None
) -> list[FieldDef]:
    if project_id is not None:
        return [f for _pf, f in await list_project_fields(session, ctx, project_id)]
    return list(
        (
            await session.execute(
                select(FieldDef)
                .where(
                    FieldDef.workspace_id == ctx.workspace_id,
                    FieldDef.applies_to == "task",
                    FieldDef.deleted_at.is_(None),
                )
                .order_by(FieldDef.name)
            )
        ).scalars()
    )


async def reference(
    session: AsyncSession, ctx: Ctx, surface: str, project_id: uuid.UUID | None
) -> tuple[str, list[FieldDef]]:
    lines = [f"Surface: {surface}", f"Today (the viewer's timezone): {today_for(ctx).isoformat()}"]
    if surface in PROJECT_SURFACES:
        assert project_id is not None
        project, _ = await get_visible_project(session, ctx, project_id)
        lines.append(f"Project: {safe(project.name)}")
    lines.append(
        "People: " + ", ".join(safe(u.name) for u in (await list_users(session, ctx))[:60])
    )
    lines.append(
        "Tags: " + (", ".join(safe(t.name) for t in await list_tags(session, ctx)) or "none")
    )
    defs = await _task_fields(session, ctx, project_id if surface in PROJECT_SURFACES else None)
    described = []
    for f in defs[:40]:
        opts = [str(o.get("label", "")) for o in f.options or [] if isinstance(o, dict)]
        kind = f.type.replace("_", "-")
        if opts:
            kind += ": " + ", ".join(safe(o) for o in opts[:12])
        described.append(f"{safe(f.name)} ({kind})")
    lines.append("Custom fields: " + ("; ".join(described) or "none"))
    return '<data source="workspace">\n' + "\n".join(lines) + "\n</data>", defs


def _unsupported(surface: str, what: str, instead: str) -> Ask:
    where = {"my_tasks": "My Tasks", "search": "Search"}.get(surface, "This view")
    return Ask(f"{where} can't filter by {what}. {instead}")


async def _fields(
    tc: ToolContext, defs: list[FieldDef], conds: list[FieldCondDraft]
) -> tuple[list[str], list[dict[str, Any]], list[Chip]]:
    """Named field conditions → ``<field id>:<op>[:<arg>]`` texts (the chart's own resolution)."""
    by_name = {f.name.strip().lower(): f for f in defs}
    today = today_for(tc.ctx)
    texts: list[str] = []
    named: list[dict[str, Any]] = []
    chips: list[Chip] = []
    for c in conds:
        f = by_name.get(c.field.strip().lower())
        if f is None:
            raise Ask(
                f'There\'s no custom field "{c.field.strip()}" here. Which did you mean?',
                [x.name for x in defs],
            )
        lo: str | float | None = None
        hi: str | float | None = None
        nf: dict[str, Any] = {"field": f.name}
        if c.in_month:
            if f.type != "date":
                raise Ask(f'"{f.name}" isn\'t a date field.')
            a, b = month_bounds(c.in_month, today)
            lo, hi = a.isoformat(), b.isoformat()
            nf["in_month"] = a.strftime("%B")
        if c.on_or_after:
            lo = resolve_day(c.on_or_after, today, f.type)
            nf["on_or_after"] = c.on_or_after.strip().lower()
        if c.on_or_before:
            hi = resolve_day(c.on_or_before, today, f.type)
            nf["on_or_before"] = c.on_or_before.strip().lower()
        if c.is_any:
            nf["is_any"] = sorted(x.strip() for x in c.is_any)
        if c.has_value is not None:
            nf["has_value"] = c.has_value
        if c.contains:
            nf["contains"] = c.contains.strip()
        cf = ChartFieldFilter(
            field=f.name,
            is_any=c.is_any,
            at_least=None if lo is None else (lo if isinstance(lo, str) else f"{lo:g}"),
            at_most=None if hi is None else (hi if isinstance(hi, str) else f"{hi:g}"),
            contains=c.contains.strip() if c.contains else None,
            has_value=c.has_value,
        )
        try:
            parsed = await chart._field_filters(tc, f, cf)
        except chart.Ask as e:
            raise Ask(e.question) from None
        except ToolError as e:
            raise Ask(e.message) from None
        texts += [p.to_text() for p in parsed]
        named.append(nf)
        bits = [", ".join(c.is_any)] if c.is_any else []
        if lo is not None or hi is not None:
            bits.append(f"{lo if lo is not None else '…'} to {hi if hi is not None else '…'}")
        if c.contains:
            bits.append(f"contains “{c.contains.strip()}”")
        if c.has_value is not None:
            bits.append("has a value" if c.has_value else "empty")
        chips.append(Chip(f"field:{f.id}", f"{f.name}: {'; '.join(bits)}"))
    return texts, named, chips


async def resolve_task_draft(
    session: AsyncSession,
    ctx: Ctx,
    surface: str,
    d: TaskFilterDraft,
    defs: list[FieldDef],
    project_id: uuid.UUID | None,
) -> FilterDraft:
    """Names → the surface's own filter schema, with chips. Raises ``Ask``."""
    tc = ToolContext(session=session, ctx=ctx, mode="dry_run")
    out = FilterDraft(surface=surface)
    f: dict[str, Any] = {}
    project_view = surface in PROJECT_SURFACES

    # people
    if d.people:
        if surface == "my_tasks":
            raise _unsupported(surface, "assignee", "It only holds your own tasks.")
        if surface == "search" and len(d.people) > 1:
            raise Ask("Search filters by one assignee at a time. Which one?", d.people)
        ids: list[str] = []
        names: list[str] = []
        for p in d.people:
            v = p.strip()
            if v.lower() in UNASSIGNED:
                if surface == "search":
                    raise _unsupported(surface, "unassigned tasks", "Try the project's list.")
                ids.append("none")
                names.append("Unassigned")
            elif v.lower() in ME:
                ids.append("me" if project_view else str(ctx.actor.id))
                names.append("me")
            else:
                try:
                    u = await resolve_person(tc, v)
                except ToolError as e:
                    people = [x.name for x in (await list_users(session, ctx))[:12]]
                    raise Ask(e.message, people) from None
                ids.append(str(u.id))
                names.append(u.name)
        if project_view:
            f["assignees"] = ids
        else:
            f["assignee_id"] = ids[0]
        out.chips.append(Chip("assignees", "Assignee: " + ", ".join(names)))
        out.named["people"] = sorted(names)

    # tags
    if d.tags:
        if not project_view:
            raise _unsupported(surface, "tags", "Open a project's list to filter by tag.")
        library = {t.name.lower(): t for t in await list_tags(session, ctx)}
        picked = []
        for t in d.tags:
            tag = library.get(t.strip().lower())
            if tag is None:
                raise Ask(
                    f'There\'s no tag called "{t.strip()}". Which tag did you mean?',
                    sorted(x.name for x in library.values())[:20],
                )
            picked.append(tag)
        f["tags"] = [str(t.id) for t in picked]
        out.chips.append(Chip("tags", "Tags: " + ", ".join(t.name for t in picked)))
        out.named["tags"] = sorted(t.name for t in picked)

    # due
    if d.due and d.due != "any":
        if not project_view:
            hint = (
                "It already groups your tasks by when they're due."
                if surface == "my_tasks"
                else "Open a project's list to filter by due date."
            )
            raise _unsupported(surface, "due date", hint)
        f["due"] = d.due
        out.chips.append(Chip("due", DUE_WORDS[d.due]))
        out.named["due"] = d.due

    # completed
    if d.show_completed is not None and surface != "search":
        f["show_completed"] = d.show_completed
        out.chips.append(
            Chip("show_completed", "Completed shown" if d.show_completed else "Open only")
        )
        out.named["show_completed"] = d.show_completed
    if surface == "search" and (d.completed or d.show_completed is not None):
        state = d.completed or ("any" if d.show_completed else "open")
        if state != "any":
            f["completed"] = state == "completed"
        out.chips.append(
            Chip(
                "completed",
                {"open": "Open", "completed": "Completed"}.get(state, "Open and completed"),
            )
        )
        out.named["completed"] = state

    # search only: words, project, types
    if d.words and d.words.strip():
        if surface != "search":
            raise _unsupported(surface, "words", "Use Search to look for words.")
        f["q"] = d.words.strip()
        out.chips.append(Chip("q", f"“{f['q']}”"))
        out.named["words"] = f["q"]
    if d.project:
        if surface != "search":
            raise _unsupported(surface, "project", "It already shows one place.")
        try:
            proj, _ = await resolve_project(tc, d.project)
        except ToolError as e:
            raise Ask(e.message, [c["name"] for c in e.candidates or []]) from None
        f["project_id"] = str(proj.id)
        out.chips.append(Chip("project_id", f"Project: {proj.name}"))
        out.named["project"] = proj.name
    if d.types:
        if surface != "search":
            raise _unsupported(
                surface, "result type", "Use Search for projects, people or comments."
            )
        f["type"] = list(dict.fromkeys(d.types))
        out.chips.append(Chip("type", "Results: " + ", ".join(f["type"])))
        out.named["types"] = sorted(f["type"])

    # sort and group: the project views only
    if d.sort or d.group:
        if not project_view:
            raise _unsupported(surface, "sort or group", "Its order is fixed.")
        if d.sort:
            f["sort"] = d.sort
            out.chips.append(Chip("sort", f"Sorted by {d.sort}"))
            out.named["sort"] = d.sort
        if d.group:
            f["group"] = d.group
            out.chips.append(Chip("group", f"Grouped by {d.group}"))
            out.named["group"] = d.group

    if d.fields:
        texts, named, chips = await _fields(tc, defs, d.fields)
        f["field" if surface == "search" else "fields"] = texts
        out.named["fields"] = named
        out.chips += chips

    if not f:
        raise Ask("What should the view show? For example: my overdue tasks tagged Launch.")
    out.filters = f
    return out
