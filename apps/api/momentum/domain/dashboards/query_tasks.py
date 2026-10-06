"""Phase 7.5 (spec §7.1): the ``tasks`` entity of query spec version 2, on top of the v1 engine
(``query.py``, unchanged).

A version 2 tasks spec is a v1 question plus a portfolio, project-level narrowing from the
dashboard (project owner, project-field conditions) and a second dimension (``split_by``) for
stacked bars. The project narrowing becomes the v1 ``project_ids`` filter (the visible projects
that match, or an id no project has when none match: an empty scope never means "everything"),
so visibility, the counting rules and the drill stay the v1 ones.

- ``kpi`` is a v1 count; ``compare_previous`` needs a "completed in the last N days" filter (the
  previous period is the N days before: the count over 2N days minus the count over N).
- ``table`` is a v1 list (key, title, assignee, due, project).
- ``stacked_bar`` runs the v1 bar once for the groups, then once per split value (a priority, or an
  option of a single-select task field, plus "none"), and lines the values up with the groups.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.core.errors import ValidationFailed
from momentum.domain.dashboards import query
from momentum.domain.dashboards.query_scope import NO_PROJECT, scope_projects
from momentum.domain.dashboards.schemas import (
    DrillIn,
    DrillOut,
    QueryResultOut,
    QuerySpec,
    StackOut,
)
from momentum.domain.dashboards.schemas_v2 import TasksSpec
from momentum.domain.dashboards.spec import NONE_KEY, OTHER_KEY
from momentum.domain.fields.filters import FieldFilter
from momentum.domain.fields.models import FieldDef

BASE_KIND = {"kpi": "count", "table": "list", "stacked_bar": "bar"}
PRIORITIES = (("urgent", "Urgent"), ("high", "High"), ("medium", "Medium"), ("low", "Low"))
TABLE_COLUMNS = ["key", "title", "assignee", "due_on", "project"]


async def project_scope(
    session: AsyncSession,
    ctx: Ctx,
    spec: TasksSpec,
    *,
    owner: list[str] | None = None,
    fields: list[dict[str, Any]] | None = None,
) -> list[uuid.UUID] | None:
    """The project ids a v2 tasks spec is narrowed to, or None when it isn't narrowed."""
    portfolio_id = spec.filters.portfolio_id
    conds = [*(c.model_dump(mode="json") for c in spec.filters.project_fields), *(fields or [])]
    if portfolio_id is None and not owner and not conds:
        return None
    scope = await scope_projects(session, ctx, portfolio_id=portfolio_id, owner=owner, fields=conds)
    ids = [p.id for p in scope.projects]
    if spec.filters.project_ids:
        wanted = set(spec.filters.project_ids)
        ids = [i for i in ids if i in wanted]
    return ids or [NO_PROJECT]


async def v1_of(
    session: AsyncSession,
    ctx: Ctx,
    spec: TasksSpec,
    *,
    owner: list[str] | None = None,
    fields: list[dict[str, Any]] | None = None,
) -> QuerySpec:
    return spec.to_v1(await project_scope(session, ctx, spec, owner=owner, fields=fields))


async def run_tasks(
    session: AsyncSession,
    ctx: Ctx,
    kind: str,
    spec: TasksSpec,
    *,
    project_id: uuid.UUID | None = None,
    owner: list[str] | None = None,
    fields: list[dict[str, Any]] | None = None,
    prev_len: int | None = None,
) -> QueryResultOut:
    v1 = await v1_of(session, ctx, spec, owner=owner, fields=fields)
    base = BASE_KIND.get(kind, kind)
    out = await query.run(session, ctx, base, v1, project_id=project_id)  # type: ignore[arg-type]
    out.kind = kind  # type: ignore[assignment]
    out.target = spec.target
    if spec.filters.portfolio_id is not None:
        out.description = f"{out.description} · in the portfolio"
    if kind == "kpi" and spec.compare_previous:
        n = v1.filters.completed_within_days
        span = n + (prev_len or n) if n is not None else 0  # this period and the one before
        if n is not None and span <= 366:
            wider = v1.model_copy(
                update={"filters": v1.filters.model_copy(update={"completed_within_days": span})}
            )
            both = await query.run(session, ctx, "count", wider, project_id=project_id)
            out.previous = (both.value or 0) - (out.value or 0)
        else:
            out.notes.append(
                "No comparison: it needs a 'completed in the last N days' filter (N up to 183)."
            )
    if kind == "table":
        out.columns = list(TABLE_COLUMNS)
    if kind == "stacked_bar":
        out.stacks = await _stacks(session, ctx, spec, v1, out, project_id)
    return out


async def _split_values(
    session: AsyncSession, ctx: Ctx, spec: TasksSpec
) -> list[tuple[str, str, str | None]]:
    """(key, label, colour) of every split value, "none" last."""
    if spec.split_by == "priority":
        return [*((k, label, None) for k, label in PRIORITIES), (NONE_KEY, "No priority", None)]
    f = await session.get(FieldDef, spec.split_field_id)
    if f is None or f.workspace_id != ctx.workspace_id or f.deleted_at is not None:
        raise ValidationFailed("That custom field doesn't exist")
    if f.type != "single_select":
        raise ValidationFailed("A stacked bar splits by priority or a single-select field")
    opts = [
        (str(o["id"]), str(o.get("label") or "Option"), o.get("color"))
        for o in f.options or []
        if isinstance(o, dict)
    ]
    return [*opts, (NONE_KEY, f"No {f.name}", None)]


def _narrow(v1: QuerySpec, spec: TasksSpec, key: str) -> QuerySpec:
    f = v1.filters
    if spec.split_by == "priority":
        filters = f.model_copy(update={"priorities": [key]})
    else:
        cond = FieldFilter(field_id=spec.split_field_id, op="any", values=[key])
        filters = f.model_copy(update={"fields": [*f.fields, cond]})
    return v1.model_copy(update={"filters": filters, "limit": 50})


async def _stacks(
    session: AsyncSession,
    ctx: Ctx,
    spec: TasksSpec,
    v1: QuerySpec,
    out: QueryResultOut,
    project_id: uuid.UUID | None,
) -> list[StackOut]:
    shown = [g.key for g in out.groups if g.key != OTHER_KEY]
    has_other = any(g.key == OTHER_KEY for g in out.groups)
    stacks: list[StackOut] = []
    for key, label, color in await _split_values(session, ctx, spec):
        part = await query.run(session, ctx, "bar", _narrow(v1, spec, key), project_id=project_id)
        by_key = {g.key: g.value for g in part.groups}
        values = [by_key.get(k, 0.0) for k in shown]
        if has_other:
            values.append(sum(v for k, v in by_key.items() if k not in shown))
        if any(values):
            stacks.append(
                StackOut(
                    key=key,
                    label=label,
                    color=color if isinstance(color, str) else None,
                    values=values,
                )
            )
    return stacks


async def drill_tasks(
    session: AsyncSession,
    ctx: Ctx,
    spec: TasksSpec,
    *,
    project_id: uuid.UUID | None,
    key: str | None,
    bucket_start: Any,
    limit: int,
    split_key: str | None = None,
    owner: list[str] | None = None,
    fields: list[dict[str, Any]] | None = None,
) -> DrillOut:
    v1 = await v1_of(session, ctx, spec, owner=owner, fields=fields)
    if split_key is not None and spec.split_by is not None:
        v1 = _narrow(v1, spec, split_key)
    return await query.drill(
        session,
        ctx,
        DrillIn(
            query_spec=v1, project_id=project_id, key=key, bucket_start=bucket_start, limit=limit
        ),
    )
