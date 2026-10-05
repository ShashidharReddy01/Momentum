"""S6.5.2 "Ask for a chart": one question ("open tasks by assignee", "how many are overdue?") →
a validated dashboard ``QuerySpec`` → the chart's numbers, computed as the asker. Nothing is
saved: the client shows the preview and posts the widget like any hand-built one (one write
path), with ``created_from_prompt`` set to the question.

The model works in **names** (people, projects, sections, tags, a custom field) and the server
resolves them to ids among what the asker can see, as ``nl_rule`` does; anything it can't
resolve, or can't chart (money, time logged, anything but tasks), becomes a question back
instead of a guess. The model only chooses among the spec's own options: the numbers always
come from ``domain/dashboards/query.py``, never from the model.

``resolve()`` is shared with Mo's ``query_metrics`` read tool, so a chart and an answer in chat
count the same way.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai import prompts
from momentum.ai.context.tokens import safe
from momentum.ai.llm import LLM
from momentum.ai.structured import extract
from momentum.ai.tools.base import ToolContext, ToolError
from momentum.ai.tools.refs import resolve_person, resolve_project, resolve_section
from momentum.core.context import Ctx
from momentum.core.errors import ValidationFailed
from momentum.domain.access import get_visible_project, visible_projects_clause
from momentum.domain.dashboards import query
from momentum.domain.dashboards.query import GROUPABLE_FIELDS
from momentum.domain.dashboards.schemas import (
    NONE_KEY,
    GroupBy,
    Measure,
    Priority,
    QueryFilters,
    QueryResultOut,
    QuerySpec,
    TaskStatus,
    TimeBucket,
    TimeField,
    WidgetKind,
    check_kind,
)
from momentum.domain.fields.filters import NUMERIC, FieldFilter
from momentum.domain.fields.models import FIELD_TYPES, FieldDef
from momentum.domain.fields.service import list_project_fields
from momentum.domain.projects.models import Project
from momentum.domain.sections.service import list_sections
from momentum.domain.tags.service import list_tags
from momentum.domain.users.service import list_users

MAX_TEXT = 300
LISTED_PROJECTS = 40  # named in the prompt; naming one that isn't listed still resolves
LISTED_PEOPLE = 60
UNASSIGNED = {"none", "nobody", "unassigned", "no one", "no assignee"}


class ChartFieldFilter(BaseModel):
    """One custom-field condition, in names (the server maps them to option and user ids)."""

    model_config = ConfigDict(extra="forbid")
    field: str = Field(max_length=100, description="A custom field name from the reference")
    is_any: list[str] = Field(
        default_factory=list,
        max_length=10,
        description='Option names, people\'s names, "checked", "not checked" or "empty"',
    )
    at_least: str | None = Field(default=None, max_length=20, description="Number or YYYY-MM-DD")
    at_most: str | None = Field(default=None, max_length=20, description="Number or YYYY-MM-DD")
    contains: str | None = Field(default=None, max_length=100, description="Text fields")
    has_value: bool | None = None


class ChartFilters(BaseModel):
    """Which tasks to count (by name), at most one way to split them, and what to measure."""

    model_config = ConfigDict(extra="forbid")
    kind: WidgetKind | None = Field(
        default=None, description="count, bar, donut, line (over time) or list (the tasks)"
    )
    status: TaskStatus = "open"
    overdue: bool = False
    blocked: bool = False
    people: list[str] = Field(
        default_factory=list, max_length=10, description='Names, "me" or "unassigned"'
    )
    projects: list[str] = Field(default_factory=list, max_length=10)
    sections: list[str] = Field(default_factory=list, max_length=10)
    tags: list[str] = Field(default_factory=list, max_length=10)
    priorities: list[Priority] = Field(default_factory=list, max_length=5)
    due_within_days: int | None = Field(default=None, ge=0, le=366)
    completed_within_days: int | None = Field(default=None, ge=1, le=366)
    group_by: GroupBy | None = None
    field: str | None = Field(
        default=None,
        max_length=100,
        description="The field to split by when group_by=field (single- or multi-select, "
        "people, checkbox)",
    )
    field_filters: list[ChartFieldFilter] = Field(default_factory=list, max_length=5)
    time_bucket: TimeBucket | None = None
    time_field: TimeField = "completed"
    date_field: str | None = Field(
        default=None, max_length=100, description="The date field when time_field=field"
    )
    window_days: int | None = Field(default=None, ge=7, le=366)
    measure: Measure = "count"
    measure_field: str | None = Field(
        default=None,
        max_length=100,
        description="The number field when measure is sum_field or avg_field",
    )
    limit: int | None = Field(default=None, ge=1, le=50)


class ChartDraft(ChartFilters):
    """What the model submits: a chart in names, or only a question."""

    title: str = Field(default="", max_length=120)
    question: str | None = Field(
        default=None, max_length=300, description="Ask instead of guessing; leave the rest empty"
    )


class Ask(Exception):
    def __init__(self, question: str) -> None:
        super().__init__(question)
        self.question = question


@dataclass
class Resolved:
    kind: WidgetKind
    spec: QuerySpec
    named: dict[str, Any] = field(default_factory=dict)  # the filters as names, for the UI


@dataclass
class ChartAnswer:
    question: str | None = None
    kind: WidgetKind | None = None
    title: str = ""
    spec: QuerySpec | None = None
    named: dict[str, Any] = field(default_factory=dict)
    result: QueryResultOut | None = None


def _kind(d: ChartFilters) -> WidgetKind:
    """The kind that fits the dimension asked for (a count can't be split; a line needs time)."""
    if d.time_bucket is not None:
        return "line"
    if d.group_by is not None:
        return d.kind if d.kind in ("bar", "donut") else "bar"
    if d.kind in ("bar", "donut", "line"):  # a split without a dimension
        return "count"
    return d.kind or "count"


async def resolve(
    session: AsyncSession, ctx: Ctx, d: ChartFilters, project_id: uuid.UUID | None
) -> Resolved:
    """Names → ids among what the asker can see, then a validated spec. Raises ``Ask``."""
    tc = ToolContext(session=session, ctx=ctx, mode="dry_run")
    kind = _kind(d)
    named: dict[str, Any] = {}
    status = d.status
    if kind == "line" and d.time_field == "completed" and status == "open":
        status = "completed"
    if (d.overdue or d.blocked) and status == "completed":
        status = "open"
    if d.completed_within_days is not None and status == "open":
        status = "completed"

    try:
        # people
        assignees: list[str] = []
        people: list[str] = []
        for p in d.people:
            v = p.strip()
            if v.lower() in UNASSIGNED:
                assignees.append(NONE_KEY)
                people.append("Unassigned")
            elif v.lower() in ("me", "myself", "i", "mine"):
                assignees.append("me")
                people.append("me")
            else:
                user = await resolve_person(tc, v)
                assignees.append(str(user.id))
                people.append(user.name)
        if people:
            named["people"] = people

        # projects (a project dashboard always shows its own project)
        project_ids: list[uuid.UUID] = []
        for name in d.projects:
            project, _ = await resolve_project(tc, name.strip())
            if project_id is not None:
                if project.id != project_id:
                    raise Ask(
                        f"This dashboard only shows its own project, not {project.name}. "
                        "Ask on a workspace dashboard to chart other projects."
                    )
                continue
            project_ids.append(project.id)
        if project_ids:
            names = (
                await session.execute(select(Project.name).where(Project.id.in_(project_ids)))
            ).scalars()
            named["projects"] = sorted(names)

        # sections need one project to be read in
        section_ids: list[uuid.UUID] = []
        if d.sections:
            home = project_id or (project_ids[0] if len(project_ids) == 1 else None)
            if home is None:
                raise Ask("Which project are those sections in?")
            for s in d.sections:
                section_ids.append((await resolve_section(tc, home, s.strip())).id)
            named["sections"] = [s.strip() for s in d.sections]

        # tags
        tag_ids: list[uuid.UUID] = []
        if d.tags:
            library = {t.name.lower(): t for t in await list_tags(session, ctx)}
            for t in d.tags:
                tag = library.get(t.strip().lower())
                if tag is None:
                    raise Ask(f'There\'s no tag called "{t.strip()}". Which tag did you mean?')
                tag_ids.append(tag.id)
            named["tags"] = [library[t.strip().lower()].name for t in d.tags]

        # custom fields (S7.4.1): split by, add up, date by, filter by
        fields = await _fields(session, ctx, project_id)

        def pick(name: str | None, types: tuple[str, ...], use: str, kinds: str) -> FieldDef:
            if not name:
                raise Ask(f"Which custom field should the chart {use}?")
            match = fields.get(name.strip().lower())
            if match is None or match.type not in types:
                listed = (
                    ", ".join(sorted(f.name for f in fields.values() if f.type in types))
                    or "none here"
                )
                raise Ask(
                    f'I can {use} {kinds}, and "{name.strip()}" isn\'t one here '
                    f"(those fields: {listed}). Which should I use?"
                )
            return match

        field_id: uuid.UUID | None = None
        group_by = d.group_by if kind in ("bar", "donut") else None
        if group_by == "field":
            g = pick(
                d.field,
                GROUPABLE_FIELDS,
                "split by",
                "single-select, multi-select, people or checkbox fields",
            )
            field_id = g.id
            named["field"] = g.name
        measure_field_id: uuid.UUID | None = None
        if d.measure in ("sum_field", "avg_field") and kind != "list":
            m = pick(d.measure_field, NUMERIC, "add up", "number fields")
            measure_field_id = m.id
            named["measure_field"] = m.name
        time_field_id: uuid.UUID | None = None
        if kind == "line" and d.time_field == "field":
            dated = pick(d.date_field, ("date",), "count by", "date fields")
            time_field_id = dated.id
            named["date_field"] = dated.name
        field_filters = []
        for ff in d.field_filters:
            target = pick(ff.field, FIELD_TYPES, "filter by", "custom fields")
            field_filters += await _field_filters(tc, target, ff)
        if d.field_filters:
            named["field_filters"] = [
                ff.model_dump(exclude_defaults=True) for ff in d.field_filters
            ]
    except ToolError as e:
        raise Ask(e.message) from None

    filters = dict(
        status=status,
        overdue=d.overdue,
        blocked=d.blocked,
        assignees=assignees,
        project_ids=project_ids,
        section_ids=section_ids,
        tag_ids=tag_ids,
        priorities=d.priorities,
        due_within_days=None if d.overdue else d.due_within_days,
        completed_within_days=d.completed_within_days if status != "open" else None,
        fields=field_filters,
    )
    spec_args: dict[str, Any] = {"filters": filters, "measure": d.measure}
    if kind == "list":
        spec_args["measure"] = "count"
    elif measure_field_id is not None:
        spec_args["measure_field_id"] = measure_field_id
    if group_by is not None:
        spec_args["group_by"] = group_by
        spec_args["field_id"] = field_id
    if kind == "line":
        spec_args["time_bucket"] = d.time_bucket or "week"
        spec_args["time_field"] = d.time_field
        if time_field_id is not None:
            spec_args["time_field_id"] = time_field_id
        if d.window_days is not None:
            spec_args["window_days"] = d.window_days
    if d.limit is not None and kind in ("bar", "donut", "list"):
        spec_args["limit"] = d.limit
    elif kind == "list":
        spec_args["limit"] = 10
    try:
        spec = QuerySpec(
            filters=QueryFilters(**filters),
            **{k: v for k, v in spec_args.items() if k != "filters"},
        )
        check_kind(kind, spec)
    except (ValidationError, ValueError) as e:
        detail = str(e.errors()[0].get("msg", "")) if isinstance(e, ValidationError) else str(e)
        raise Ask(
            f"I couldn't make that into a chart ({detail.removeprefix('Value error, ')}). "
            "Can you say it another way?"
        ) from None
    await query.check_spec(session, ctx, spec)
    return Resolved(kind=kind, spec=spec, named=named)


async def _field_filters(
    tc: ToolContext, field: FieldDef, ff: ChartFieldFilter
) -> list[FieldFilter]:
    """One named condition → the spec's filters: option and people names to ids."""
    out: list[FieldFilter] = []
    if ff.is_any:
        values: list[str] = []
        labels = [
            (str(o.get("label", "")), str(o["id"]))
            for o in (field.options if isinstance(field.options, list) else [])
        ]
        options = {label.lower(): oid for label, oid in labels}
        for word in ff.is_any:
            w = word.strip().lower()
            if w in ("empty", "none", "no value"):
                values.append("none")
            elif field.type == "checkbox" and w in ("checked", "yes", "true", "not checked", "no"):
                values.append("true" if w in ("checked", "yes", "true") else "false")
            elif field.type == "people":
                values.append(str((await resolve_person(tc, word.strip())).id))
            elif w in options:
                values.append(options[w])
            else:
                listed = ", ".join(label for label, _ in labels if label) or "none"
                raise Ask(
                    f'"{field.name}" has no option "{word.strip()}" (options: {listed}). '
                    "Which did you mean?"
                )
        out.append(FieldFilter(field_id=field.id, op="any", values=values))
    for op, raw in (("min", ff.at_least), ("max", ff.at_most), ("has", ff.contains)):
        if raw is not None and raw.strip():
            out.append(FieldFilter(field_id=field.id, op=op, value=raw.strip()))
    if ff.has_value is not None:
        out.append(FieldFilter(field_id=field.id, op="set" if ff.has_value else "empty"))
    if not out:
        raise Ask(f'What should "{field.name}" be for the tasks counted?')
    return out


async def _fields(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID | None
) -> dict[str, FieldDef]:
    """Every custom field by lowercase name: the project's own, or the workspace's."""
    return await _all_fields(session, ctx, project_id)


async def _select_fields(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID | None
) -> dict[str, FieldDef]:
    """Fields a chart can split by, by lowercase name: the project's own, or the workspace's."""
    return {
        k: f
        for k, f in (await _all_fields(session, ctx, project_id)).items()
        if f.type in GROUPABLE_FIELDS
    }


async def _all_fields(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID | None
) -> dict[str, FieldDef]:
    if project_id is not None:
        defs = [f for _pf, f in await list_project_fields(session, ctx, project_id)]
    else:
        defs = list(
            (
                await session.execute(
                    select(FieldDef).where(
                        FieldDef.workspace_id == ctx.workspace_id, FieldDef.deleted_at.is_(None)
                    )
                )
            ).scalars()
        )
    return {f.name.lower(): f for f in defs}


async def _reference(session: AsyncSession, ctx: Ctx, project_id: uuid.UUID | None) -> str:
    """What the model may name: the scope, people, projects, sections, tags, fields."""
    lines: list[str] = []
    if project_id is not None:
        project, _ = await get_visible_project(session, ctx, project_id)
        lines.append(f"Scope: the project {safe(project.name)} (every chart counts only its tasks)")
        sections = [safe(s.name) for s in await list_sections(session, project_id)]
        lines.append("Sections: " + (", ".join(sections) or "none"))
    else:
        lines.append("Scope: the whole workspace (every project the asker can see)")
        projects = (
            await session.execute(
                select(Project.name)
                .where(visible_projects_clause(ctx), Project.is_template.is_(False))
                .order_by(func.lower(Project.name))
                .limit(LISTED_PROJECTS)
            )
        ).scalars()
        lines.append("Projects: " + (", ".join(safe(p) for p in projects) or "none"))
    people = [safe(u.name) for u in (await list_users(session, ctx))[:LISTED_PEOPLE]]
    lines.append("People: " + (", ".join(people) or "none"))
    tags = [safe(t.name) for t in await list_tags(session, ctx)]
    lines.append("Tags: " + (", ".join(tags) or "none"))
    described = []
    for f in sorted(
        (await _fields(session, ctx, project_id)).values(), key=lambda f: f.name.lower()
    ):
        options = [o.get("label", "") for o in (f.options if isinstance(f.options, list) else [])]
        kind_word = f.type.replace("_", "-")
        if options:
            kind_word += ": " + ", ".join(safe(str(o)) for o in options[:12])
        described.append(f"{safe(f.name)} ({kind_word})")
    lines.append("Custom fields: " + ("; ".join(described[:40]) or "none"))
    return '<data source="workspace">\n' + "\n".join(lines) + "\n</data>"


async def ask_chart(
    session: AsyncSession, llm: LLM, ctx: Ctx, text: str, project_id: uuid.UUID | None
) -> ChartAnswer:
    """A question → a chart preview (spec + numbers as the asker), or a question back."""
    text = text.strip()
    if not text:
        raise ValidationFailed("Ask for a chart first")
    if len(text) > MAX_TEXT:
        raise ValidationFailed(f"That's too long (at most {MAX_TEXT} characters)")
    reference = await _reference(session, ctx, project_id)  # also checks the project is visible
    prompt = prompts.load("chart")
    draft = await extract(
        llm,
        ctx,
        prompt=prompt,
        system=prompt.body,
        user=f'{reference}\n<data source="request">{safe(text)}</data>',
        schema=ChartDraft,
        description="Submit the chart, or a question to ask back.",
    )
    if draft.question and not (
        draft.kind or draft.group_by or draft.time_bucket or draft.people or draft.overdue
    ):
        return ChartAnswer(question=draft.question.strip())
    try:
        r = await resolve(session, ctx, draft, project_id)
    except Ask as ask:
        return ChartAnswer(question=ask.question)
    result = await query.run(session, ctx, r.kind, r.spec, project_id=project_id)
    title = draft.title.strip() or result.description
    return ChartAnswer(kind=r.kind, title=title[:120], spec=r.spec, named=r.named, result=result)


def canonical(a: ChartAnswer) -> dict[str, Any] | None:
    """The answer's chart with names in place of ids and defaults left out, so an eval case
    can state exactly what it expects without depending on a database's uuids."""
    if a.spec is None or a.kind is None:
        return None
    s, f = a.spec, a.spec.filters
    filters: dict[str, Any] = {"status": f.status}
    if f.overdue:
        filters["overdue"] = True
    if f.blocked:
        filters["blocked"] = True
    for key in ("people", "projects", "sections", "tags"):
        if a.named.get(key):
            filters[key] = sorted(a.named[key])
    if f.priorities:
        filters["priorities"] = sorted(f.priorities)
    if f.due_within_days is not None:
        filters["due_within_days"] = f.due_within_days
    if f.completed_within_days is not None:
        filters["completed_within_days"] = f.completed_within_days
    out: dict[str, Any] = {
        "kind": a.kind,
        "group_by": s.group_by,
        "measure": s.measure,
        "filters": filters,
    }
    if s.group_by == "field":
        out["field"] = a.named.get("field")
    if a.named.get("measure_field"):
        out["measure_field"] = a.named["measure_field"]
    if a.named.get("field_filters"):
        out["field_filters"] = a.named["field_filters"]
    if s.time_bucket is not None:
        out["time_bucket"] = s.time_bucket
        out["time_field"] = s.time_field
        if a.named.get("date_field"):
            out["date_field"] = a.named["date_field"]
        out["window_days"] = s.window_days
    return out
