"""S6.5.1: dashboards and their widgets. The one write path for both.

Visibility (kickoff Q5): a **workspace** dashboard is visible to every workspace member and edited
by its owner or a workspace admin; a **project** dashboard (the project's Dashboard tab, one per
project) follows the project: whoever can see the project sees it, its editors and admins edit
it. Every number inside is computed per request **as the viewer** (``query.run``), so the same
dashboard can show different numbers to different people, and a widget's stored spec never
grants anything.

Until a project has a saved dashboard, its tab shows the starter layout live (``starter()``); the
first edit saves it (``create_dashboard`` with ``starter=True``), one undo.

Phase 7.5 (spec §7): widgets store a v1 or v2 spec (``AnySpec``) run through ``query_v2.run_any``
with the dashboard's filters (saved, or the viewer's own for one view); ``dashboard_members`` add
editors to a workspace dashboard; a portfolio's editors edit its Dashboard tab; people pin
dashboards to their Home (a personal preference like a favourite: no activity, no undo); results
are cached for 60 s by the running app (``cache.py``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import Diff, record_activity
from momentum.core.context import Ctx
from momentum.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from momentum.core.events import OutboxEvent, emit
from momentum.core.mutation import Mutation
from momentum.core.ordering import key_between
from momentum.core.permissions import Action, can
from momentum.core.undo import UndoConflict, undo_handler, undo_op
from momentum.domain.access import ROLE_RANK, forbid_agent, get_visible_project
from momentum.domain.dashboards import query_v2
from momentum.domain.dashboards.cache import ResultCache
from momentum.domain.dashboards.models import (
    Dashboard,
    DashboardMember,
    DashboardPin,
    DashboardWidget,
)
from momentum.domain.dashboards.schemas import (
    DashboardIn,
    DashboardPatchIn,
    DrillAnyIn,
    DrillOut,
    FromDraftIn,
    QueryFilters,
    QueryResultOut,
    QuerySpec,
    StarterWidgetOut,
    VizIn,
    WidgetIn,
    WidgetKind,
    WidgetMoveIn,
    WidgetPatchIn,
)
from momentum.domain.dashboards.schemas_v2 import (
    AnySpec,
    DashboardFilters,
    NoteSpec,
    TasksSpec,
    check_any,
)

MAX_WIDGETS = 24
SPEC = TypeAdapter[Any](AnySpec)


def _w(
    kind: WidgetKind, title: str, size: str, **spec: Any
) -> StarterWidgetOut:  # a starter widget, validated like any other
    filters = spec.pop("filters", {})
    return StarterWidgetOut(
        kind=kind,
        title=title,
        query_spec=QuerySpec(filters=QueryFilters(**filters), **spec),
        viz=VizIn.model_validate({"size": size}),
    )


def starter(scope: str) -> list[StarterWidgetOut]:
    """The starter layout: the numbers a lead checks first, then where work stands, who has it,
    how fast it gets done, and what's late. The same for every project (and, grouped by project
    instead of section, for the workspace)."""
    by_place = "section" if scope == "project" else "project"
    return [
        _w("count", "Open tasks", "sm"),
        _w("count", "Overdue", "sm", filters={"overdue": True}),
        _w("count", "Due in 7 days", "sm", filters={"due_within_days": 7}),
        _w(
            "count",
            "Completed in 7 days",
            "sm",
            filters={"status": "completed", "completed_within_days": 7},
        ),
        _w("donut", "Open work by due date", "md", group_by="status"),
        _w("bar", "Open tasks by assignee", "md", group_by="assignee"),
        _w(
            "line",
            "Completed per week",
            "md",
            filters={"status": "completed"},
            time_bucket="week",
            time_field="completed",
            window_days=84,
        ),
        _w("bar", f"Open tasks by {by_place}", "md", group_by=by_place),
        _w("list", "Overdue work", "lg", filters={"overdue": True}, limit=10),
    ]


def _channels(d: Dashboard) -> list[str]:
    return [f"dashboard:{d.id}"]


# ---------- access ----------


async def get_dashboard(
    session: AsyncSession, ctx: Ctx, dashboard_id: uuid.UUID, *, include_deleted: bool = False
) -> tuple[Dashboard, bool]:
    """A dashboard the viewer can see, with whether they may edit it; otherwise NotFound."""
    d = await session.get(Dashboard, dashboard_id)
    if d is None or d.workspace_id != ctx.workspace_id:
        raise NotFound("Dashboard not found")
    if d.deleted_at is not None and not include_deleted:
        raise NotFound("Dashboard not found")
    if d.project_id is not None:
        project, role = await get_visible_project(session, ctx, d.project_id)
        editable = ROLE_RANK[role] >= ROLE_RANK["editor"] and project.archived_at is None
        return d, editable
    return d, await _can_edit_workspace(session, ctx, d)


async def _can_edit_workspace(session: AsyncSession, ctx: Ctx, d: Dashboard) -> bool:
    """Owner, admins, ``dashboard_members`` editors, and (a portfolio's tab) its editors."""
    if ctx.actor.is_admin or d.owner_id == ctx.actor.id:
        return True
    if ctx.actor.id is None or ctx.actor.is_agent:
        return False
    m = await session.get(DashboardMember, (d.id, ctx.actor.id))
    if m is not None and m.role == "editor":
        return True
    if d.portfolio_id is not None:
        from momentum.domain.portfolios.service import can_edit, get_portfolio

        try:
            return await can_edit(session, ctx, await get_portfolio(session, ctx, d.portfolio_id))
        except NotFound:
            return False
    return False


async def can_edit_many(
    session: AsyncSession, ctx: Ctx, boards: list[Dashboard]
) -> dict[uuid.UUID, bool]:
    return {d.id: await _can_edit_workspace(session, ctx, d) for d in boards}


def _require_edit(editable: bool) -> None:
    if not editable:
        raise Forbidden("You can view this dashboard but not change it")


async def _record(
    session: AsyncSession,
    ctx: Ctx,
    d: Dashboard,
    verb: str,
    changes: Diff | None = None,
    undo: dict[str, Any] | None = None,
) -> uuid.UUID:
    act = await record_activity(
        session,
        ctx,
        entity_type="dashboard",
        entity_id=d.id,
        verb=verb,
        changes=changes or {},
        undo=undo,
    )
    await emit(
        session,
        ctx,
        type=verb,
        entity_type="dashboard",
        entity_id=d.id,
        data={"version": d.version},
        channels=_channels(d),
        activity_id=act.id,
    )
    return act.id


# ---------- dashboards ----------


async def list_dashboards(session: AsyncSession, ctx: Ctx) -> list[tuple[Dashboard, int]]:
    """Workspace dashboards (every member sees them), with their widget counts. Project
    dashboards live on their project's tab."""
    boards = list(
        (
            await session.execute(
                select(Dashboard)
                .where(
                    Dashboard.workspace_id == ctx.workspace_id,
                    Dashboard.scope == "workspace",
                    Dashboard.deleted_at.is_(None),
                )
                .order_by(func.lower(Dashboard.name))
            )
        ).scalars()
    )
    counts = await _widget_counts(session, [d.id for d in boards])
    return [(d, counts.get(d.id, 0)) for d in boards]


async def _widget_counts(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not ids:
        return {}
    return {
        did: int(n)
        for did, n in (
            await session.execute(
                select(DashboardWidget.dashboard_id, func.count())
                .where(DashboardWidget.dashboard_id.in_(ids), DashboardWidget.deleted_at.is_(None))
                .group_by(DashboardWidget.dashboard_id)
            )
        ).all()
    }


async def widgets_of(session: AsyncSession, d: Dashboard) -> list[DashboardWidget]:
    return list(
        (
            await session.execute(
                select(DashboardWidget)
                .where(DashboardWidget.dashboard_id == d.id, DashboardWidget.deleted_at.is_(None))
                .order_by(DashboardWidget.position, DashboardWidget.id)
            )
        ).scalars()
    )


async def project_dashboard(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID
) -> tuple[Dashboard | None, bool]:
    """A project's saved dashboard (or None) and whether the viewer may edit it."""
    project, role = await get_visible_project(session, ctx, project_id)
    d = (
        await session.execute(
            select(Dashboard).where(
                Dashboard.project_id == project.id, Dashboard.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    return d, ROLE_RANK[role] >= ROLE_RANK["editor"] and project.archived_at is None


async def create_dashboard(
    session: AsyncSession, ctx: Ctx, data: DashboardIn
) -> Mutation[Dashboard]:
    if ctx.actor.id is None:
        raise Forbidden("You can't create dashboards")
    name = data.name.strip()
    if not name:
        raise ValidationFailed("Dashboard name can't be empty")
    if data.project_id is not None:
        existing, editable = await project_dashboard(session, ctx, data.project_id)
        _require_edit(editable)
        if existing is not None:
            raise Conflict("This project already has a dashboard", code="duplicate")
    elif data.portfolio_id is not None:
        from momentum.domain.portfolios.service import get_portfolio, require_edit

        await require_edit(session, ctx, await get_portfolio(session, ctx, data.portfolio_id))
        if await portfolio_dashboard_of(session, data.portfolio_id) is not None:
            raise Conflict("This portfolio already has a dashboard", code="duplicate")
    elif not can(ctx, Action.PROJECT_CREATE):
        raise Forbidden("You can't create dashboards")
    d = Dashboard(
        workspace_id=ctx.workspace_id,
        owner_id=ctx.actor.id,
        name=name,
        description=(data.description or "").strip() or None,
        scope="project" if data.project_id else "workspace",
        project_id=data.project_id,
        portfolio_id=data.portfolio_id,
        filters={"portfolio_id": str(data.portfolio_id)} if data.portfolio_id else {},
    )
    session.add(d)
    await session.flush()
    if data.starter and data.portfolio_id is None:
        keys = _keys(None, len(starter(d.scope)))
        for w, pos in zip(starter(d.scope), keys, strict=True):
            session.add(_widget_row(ctx, d, w.kind, w.title, w.query_spec, w.viz, pos))
        await session.flush()
    act = await _record(
        session,
        ctx,
        d,
        "dashboard.created",
        {"name": (None, d.name)},
        undo_op("dashboards.delete", dashboard_id=d.id),
    )
    return Mutation(d, act, version=d.version)


def _keys(after: str | None, n: int) -> list[str]:
    out: list[str] = []
    last = after
    for _ in range(n):
        last = key_between(last, None)
        out.append(last)
    return out


async def update_dashboard(
    session: AsyncSession,
    ctx: Ctx,
    dashboard_id: uuid.UUID,
    patch: DashboardPatchIn,
    *,
    record_undo: bool = True,
) -> Mutation[Dashboard]:
    d, editable = await get_dashboard(session, ctx, dashboard_id)
    _require_edit(editable)
    changes: Diff = {}
    if "filters" in patch.model_fields_set:
        if d.project_id is not None:
            raise ValidationFailed("A project dashboard has no filters")
        await _check_filters(session, ctx, patch.filters)
        new_filters = (
            patch.filters.model_dump(mode="json", exclude_defaults=True) if patch.filters else {}
        )
        if d.filters != new_filters:
            changes["filters"] = (d.filters, new_filters)
            d.filters = new_filters
    for f in patch.model_fields_set & {"name", "description"}:
        new = getattr(patch, f)
        new = new.strip() if isinstance(new, str) else new
        if f == "name" and not new:
            raise ValidationFailed("Dashboard name can't be empty")
        if f == "description":
            new = new or None
        if getattr(d, f) != new:
            changes[f] = (getattr(d, f), new)
            setattr(d, f, new)
    if not changes:
        return Mutation(d, version=d.version)
    d.version += 1
    act = await _record(
        session,
        ctx,
        d,
        "dashboard.updated",
        changes,
        undo_op(
            "dashboards.update",
            dashboard_id=d.id,
            version=d.version,
            patch={k: o for k, (o, _) in changes.items()},
        )
        if record_undo
        else None,
    )
    return Mutation(d, act, version=d.version)


async def delete_dashboard(
    session: AsyncSession, ctx: Ctx, dashboard_id: uuid.UUID, *, record_undo: bool = True
) -> Mutation[Dashboard]:
    """Soft delete. For a project dashboard this is "reset": the tab shows the starter again."""
    forbid_agent(ctx, "delete dashboards")
    d, editable = await get_dashboard(session, ctx, dashboard_id)
    _require_edit(editable)
    d.deleted_at = datetime.now(UTC)
    d.version += 1
    act = await _record(
        session,
        ctx,
        d,
        "dashboard.deleted",
        undo=undo_op("dashboards.restore", dashboard_id=d.id) if record_undo else None,
    )
    return Mutation(d, act, version=d.version)


# ---------- widgets ----------


def _widget_row(
    ctx: Ctx,
    d: Dashboard,
    kind: str,
    title: str,
    spec: Any,
    viz: VizIn,
    position: str,
) -> DashboardWidget:
    return DashboardWidget(
        workspace_id=ctx.workspace_id,
        dashboard_id=d.id,
        kind=kind,
        title=title.strip(),
        query_spec=spec.model_dump(mode="json", exclude_defaults=True),
        viz=viz.model_dump(mode="json"),
        position=position,
        created_by=ctx.actor.id,
    )


def _check_scope(d: Dashboard, spec: Any) -> None:
    if d.project_id is None:
        return
    if isinstance(spec, QuerySpec) and spec.filters.project_ids:
        raise ValidationFailed("A project dashboard always shows its own project")
    if isinstance(spec, TasksSpec) and (spec.filters.project_ids or spec.filters.portfolio_id):
        raise ValidationFailed("A project dashboard always shows its own project")
    if not isinstance(spec, QuerySpec | TasksSpec | NoteSpec):
        raise ValidationFailed("A project dashboard shows its own project's tasks (or a note)")


def widget_spec(w: DashboardWidget) -> Any:
    """The stored spec, v1 (``QuerySpec``) or v2."""
    return SPEC.validate_python(w.query_spec)


async def _check_widget(
    session: AsyncSession, ctx: Ctx, d: Dashboard, kind: str, spec: Any
) -> None:
    try:
        check_any(kind, spec)
    except ValueError as e:
        raise ValidationFailed(str(e)) from None
    _check_scope(d, spec)
    await query_v2.check_any(session, ctx, spec)


async def _check_filters(session: AsyncSession, ctx: Ctx, filters: DashboardFilters | None) -> None:
    if filters is None:
        return
    if filters.portfolio_id is not None:
        from momentum.domain.portfolios.service import get_portfolio

        await get_portfolio(session, ctx, filters.portfolio_id)
    for c in filters.fields:
        await query_v2._field(session, ctx, c.field_id, "project", None)


async def get_widget(
    session: AsyncSession, ctx: Ctx, widget_id: uuid.UUID, *, include_deleted: bool = False
) -> tuple[DashboardWidget, Dashboard, bool]:
    w = await session.get(DashboardWidget, widget_id)
    if w is None or w.workspace_id != ctx.workspace_id:
        raise NotFound("Widget not found")
    if w.deleted_at is not None and not include_deleted:
        raise NotFound("Widget not found")
    d, editable = await get_dashboard(session, ctx, w.dashboard_id)
    return w, d, editable


async def add_widget(
    session: AsyncSession,
    ctx: Ctx,
    dashboard_id: uuid.UUID,
    data: WidgetIn,
    *,
    position: str | None = None,
) -> Mutation[DashboardWidget]:
    d, editable = await get_dashboard(session, ctx, dashboard_id)
    _require_edit(editable)
    await _check_widget(session, ctx, d, data.kind, data.query_spec)
    live = await widgets_of(session, d)
    if len(live) >= MAX_WIDGETS:
        raise ValidationFailed(f"A dashboard holds up to {MAX_WIDGETS} widgets")
    if position is None:
        position = key_between(live[-1].position if live else None, None)
    w = _widget_row(ctx, d, data.kind, data.title, data.query_spec, data.viz, position)
    w.created_from_prompt = (data.created_from_prompt or "").strip() or None
    session.add(w)
    d.version += 1
    await session.flush()
    act = await _record(
        session,
        ctx,
        d,
        "dashboard.widget_added",
        {"widget": (None, w.title)},
        undo_op("dashboards.remove_widget", widget_id=w.id),
    )
    return Mutation(w, act, version=w.version)


async def update_widget(
    session: AsyncSession,
    ctx: Ctx,
    widget_id: uuid.UUID,
    patch: WidgetPatchIn,
    *,
    record_undo: bool = True,
) -> Mutation[DashboardWidget]:
    w, d, editable = await get_widget(session, ctx, widget_id)
    _require_edit(editable)
    kind = patch.kind or w.kind
    spec = patch.query_spec or widget_spec(w)
    if patch.query_spec is not None:
        await _check_widget(session, ctx, d, kind, spec)
    else:
        try:
            check_any(kind, spec)
        except ValueError as e:
            raise ValidationFailed(str(e)) from None
    new: dict[str, Any] = {}
    if patch.kind is not None:
        new["kind"] = patch.kind
    if patch.title is not None:
        new["title"] = patch.title.strip()
    if patch.query_spec is not None:
        new["query_spec"] = spec.model_dump(mode="json", exclude_defaults=True)
    if patch.viz is not None:
        new["viz"] = patch.viz.model_dump(mode="json")
    changes: Diff = {}
    for k, v in new.items():
        if getattr(w, k) != v:
            changes[k] = (getattr(w, k), v)
            setattr(w, k, v)
    if not changes:
        return Mutation(w, version=w.version)
    w.version += 1
    d.version += 1
    act = await _record(
        session,
        ctx,
        d,
        "dashboard.widget_updated",
        {k: v for k, v in changes.items() if k in ("kind", "title")}
        or {"widget": (w.title, w.title)},
        undo_op(
            "dashboards.update_widget",
            widget_id=w.id,
            version=w.version,
            previous={k: o for k, (o, _) in changes.items()},
        )
        if record_undo
        else None,
    )
    return Mutation(w, act, version=w.version)


async def remove_widget(
    session: AsyncSession, ctx: Ctx, widget_id: uuid.UUID, *, record_undo: bool = True
) -> Mutation[DashboardWidget]:
    w, d, editable = await get_widget(session, ctx, widget_id)
    _require_edit(editable)
    w.deleted_at = datetime.now(UTC)
    w.version += 1
    d.version += 1
    act = await _record(
        session,
        ctx,
        d,
        "dashboard.widget_removed",
        {"widget": (w.title, None)},
        undo_op("dashboards.restore_widget", widget_id=w.id) if record_undo else None,
    )
    return Mutation(w, act, version=w.version)


async def move_widget(
    session: AsyncSession,
    ctx: Ctx,
    widget_id: uuid.UUID,
    body: WidgetMoveIn,
    *,
    record_undo: bool = True,
) -> Mutation[DashboardWidget]:
    """Place a widget between two neighbours (the same contract as every ordered list)."""
    w, d, editable = await get_widget(session, ctx, widget_id)
    _require_edit(editable)
    siblings = {x.id: x for x in await widgets_of(session, d) if x.id != w.id}
    after = siblings.get(body.after_id) if body.after_id else None
    before = siblings.get(body.before_id) if body.before_id else None
    if (body.after_id and after is None) or (body.before_id and before is None):
        raise ValidationFailed("Neighbours must be widgets on the same dashboard")
    lo = after.position if after else None
    hi = before.position if before else None
    if lo is None and hi is None:
        raise ValidationFailed("Give before_id or after_id")
    if lo is not None and hi is not None and lo >= hi:
        raise ValidationFailed("after_id must come before before_id")
    if lo is None and hi is not None:  # first: before the neighbour
        ordered = sorted(siblings.values(), key=lambda x: x.position)
        prev = [x for x in ordered if x.position < hi]
        lo = prev[-1].position if prev else None
    if hi is None and lo is not None:
        ordered = sorted(siblings.values(), key=lambda x: x.position)
        nxt = [x for x in ordered if x.position > lo]
        hi = nxt[0].position if nxt else None
    old = w.position
    w.position = key_between(lo, hi)
    w.version += 1
    d.version += 1
    act = await _record(
        session,
        ctx,
        d,
        "dashboard.widget_moved",
        {"widget": (w.title, w.title)},
        undo_op("dashboards.place_widget", widget_id=w.id, position=old, version=w.version)
        if record_undo
        else None,
    )
    return Mutation(w, act, version=w.version)


# ---------- numbers (as the viewer) ----------


def saved_filters(d: Dashboard) -> DashboardFilters:
    try:
        return DashboardFilters.model_validate(d.filters or {})
    except ValidationError:  # a stored filter that no longer validates is ignored, not fatal
        return DashboardFilters()


async def _latest_event(session: AsyncSession) -> int:
    return int(
        (
            await session.execute(select(OutboxEvent.id).order_by(OutboxEvent.id.desc()).limit(1))
        ).scalar_one_or_none()
        or 0
    )


async def widget_data(
    session: AsyncSession,
    ctx: Ctx,
    widget_id: uuid.UUID,
    *,
    filters: DashboardFilters | None = None,
    cache: ResultCache | None = None,
) -> QueryResultOut:
    """A widget's numbers as the viewer, with the viewer's own ``filters`` for this view, or the
    dashboard's saved ones. Cached 60 s per (widget version, viewer, filters, newest event)."""
    w, d, _ = await get_widget(session, ctx, widget_id)
    applied = filters if filters is not None else saved_filters(d)
    key = None
    if cache is not None:
        key = (
            w.id,
            w.version,
            ctx.actor.id,
            ctx.workspace_id,
            applied.model_dump_json(exclude_defaults=True),
            await _latest_event(session),
        )
        hit = cache.get(key)
        if hit is not None:
            return QueryResultOut.model_validate(hit)
    out = await query_v2.run_any(
        session, ctx, w.kind, widget_spec(w), project_id=d.project_id, filters=applied
    )
    if cache is not None and key is not None:
        cache.put(key, out.model_dump())
    return out


async def run_query(
    session: AsyncSession,
    ctx: Ctx,
    kind: str,
    spec: Any,
    project_id: uuid.UUID | None,
    filters: DashboardFilters | None = None,
) -> QueryResultOut:
    """An unsaved spec (the add-chart preview, the starter layout), run as the viewer."""
    if project_id is not None:
        _check_scope(Dashboard(project_id=project_id), spec)
    await query_v2.check_any(session, ctx, spec)
    return await query_v2.run_any(session, ctx, kind, spec, project_id=project_id, filters=filters)


async def drill(
    session: AsyncSession, ctx: Ctx, body: DrillAnyIn, split_key: str | None = None
) -> DrillOut:
    if not isinstance(body.query_spec, QuerySpec):
        await query_v2.check_any(session, ctx, body.query_spec)
    return await query_v2.drill_any(session, ctx, body, split_key)


# ---------- the portfolio tab, members, pins (Phase 7.5) ----------


async def portfolio_dashboard_of(
    session: AsyncSession, portfolio_id: uuid.UUID
) -> Dashboard | None:
    return (
        await session.execute(
            select(Dashboard).where(
                Dashboard.portfolio_id == portfolio_id, Dashboard.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()


async def portfolio_dashboard(
    session: AsyncSession, ctx: Ctx, portfolio_id: uuid.UUID
) -> tuple[Dashboard | None, bool]:
    """A portfolio's Dashboard tab (or None yet) and whether the viewer may make or edit it."""
    from momentum.domain.portfolios.service import can_edit, get_portfolio

    p = await get_portfolio(session, ctx, portfolio_id)
    return await portfolio_dashboard_of(session, p.id), await can_edit(session, ctx, p)


async def list_members(
    session: AsyncSession, ctx: Ctx, dashboard_id: uuid.UUID
) -> list[DashboardMember]:
    d, _ = await get_dashboard(session, ctx, dashboard_id)
    return list(
        (
            await session.execute(
                select(DashboardMember)
                .where(DashboardMember.dashboard_id == d.id)
                .order_by(DashboardMember.created_at)
            )
        ).scalars()
    )


async def set_member(
    session: AsyncSession,
    ctx: Ctx,
    dashboard_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str | None,
    *,
    record_undo: bool = True,
) -> Mutation[Dashboard]:
    """Add, change or (``role=None``) remove a member of a workspace dashboard: its owner or an
    admin decides who else edits it."""
    from momentum.domain.users.models import User

    forbid_agent(ctx, "share dashboards")
    d, _ = await get_dashboard(session, ctx, dashboard_id)
    if d.project_id is not None:
        raise ValidationFailed("A project dashboard follows its project's members")
    if not (ctx.actor.is_admin or d.owner_id == ctx.actor.id):
        raise Forbidden("Only the dashboard's owner or an admin can share it")
    user = await session.get(User, user_id)
    if user is None or user.workspace_id != ctx.workspace_id or user.status != "active":
        raise NotFound("Person not found")
    if user.is_agent:
        raise ValidationFailed("Agents can't be dashboard members")
    m = await session.get(DashboardMember, (d.id, user_id))
    old = m.role if m is not None else None
    if old == role:
        return Mutation(d, version=d.version)
    if role is None:
        await session.delete(m)
    elif m is None:
        session.add(
            DashboardMember(
                dashboard_id=d.id, user_id=user_id, workspace_id=ctx.workspace_id, role=role
            )
        )
    else:
        m.role = role
    d.version += 1
    await session.flush()
    act = await _record(
        session,
        ctx,
        d,
        "dashboard.member_changed",
        {"member": (old, role), "user_id": (None, str(user_id))},
        undo_op("dashboards.set_member", dashboard_id=d.id, user_id=user_id, role=old)
        if record_undo
        else None,
    )
    return Mutation(d, act, version=d.version)


async def pinned_ids(session: AsyncSession, ctx: Ctx) -> list[uuid.UUID]:
    if ctx.actor.id is None:
        return []
    return list(
        (
            await session.execute(
                select(DashboardPin.dashboard_id)
                .join(Dashboard, Dashboard.id == DashboardPin.dashboard_id)
                .where(DashboardPin.user_id == ctx.actor.id, Dashboard.deleted_at.is_(None))
                .order_by(DashboardPin.position)
            )
        ).scalars()
    )


async def pin(session: AsyncSession, ctx: Ctx, dashboard_id: uuid.UUID, pinned: bool) -> None:
    """Pin to (or take off) the viewer's Home: a personal preference, like a favourite."""
    if ctx.actor.id is None or ctx.actor.is_agent:
        raise Forbidden("Only people pin dashboards")
    d, _ = await get_dashboard(session, ctx, dashboard_id)
    have = await session.get(DashboardPin, (ctx.actor.id, d.id))
    if not pinned:
        if have is not None:
            await session.delete(have)
            await session.flush()
        return
    if have is not None:
        return
    last = (
        await session.execute(
            select(func.max(DashboardPin.position)).where(DashboardPin.user_id == ctx.actor.id)
        )
    ).scalar_one_or_none()
    session.add(
        DashboardPin(
            user_id=ctx.actor.id,
            dashboard_id=d.id,
            workspace_id=ctx.workspace_id,
            position=key_between(last, None),
        )
    )
    await session.flush()


# ---------- undo ----------


def _did(args: dict[str, Any]) -> uuid.UUID:
    return uuid.UUID(str(args["dashboard_id"]))


def _wid(args: dict[str, Any]) -> uuid.UUID:
    return uuid.UUID(str(args["widget_id"]))


@undo_handler("dashboards.delete")
async def _undo_create(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    d, editable = await get_dashboard(session, ctx, _did(args))
    _require_edit(editable)
    d.deleted_at = datetime.now(UTC)
    d.version += 1
    await _record(session, ctx, d, "dashboard.deleted")


@undo_handler("dashboards.restore")
async def _undo_delete(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    d, editable = await get_dashboard(session, ctx, _did(args), include_deleted=True)
    _require_edit(editable)
    if d.deleted_at is None:
        raise UndoConflict("The dashboard is not deleted")
    if d.project_id is not None:
        taken = (
            await session.execute(
                select(Dashboard.id).where(
                    Dashboard.project_id == d.project_id, Dashboard.deleted_at.is_(None)
                )
            )
        ).first()
        if taken is not None:
            raise UndoConflict("The project has a new dashboard since")
    d.deleted_at = None
    d.version += 1
    await _record(session, ctx, d, "dashboard.restored")


@undo_handler("dashboards.update")
async def _undo_update(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    d, _ = await get_dashboard(session, ctx, _did(args))
    if d.version != int(args["version"]):
        raise UndoConflict("This dashboard changed after your edit")
    await update_dashboard(session, ctx, d.id, DashboardPatchIn(**args["patch"]), record_undo=False)


@undo_handler("dashboards.remove_widget")
async def _undo_add_widget(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    await remove_widget(session, ctx, _wid(args), record_undo=False)


@undo_handler("dashboards.restore_widget")
async def _undo_remove_widget(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    w, d, editable = await get_widget(session, ctx, _wid(args), include_deleted=True)
    _require_edit(editable)
    if w.deleted_at is None:
        raise UndoConflict("The widget is not removed")
    w.deleted_at = None
    w.version += 1
    d.version += 1
    await _record(session, ctx, d, "dashboard.widget_restored", {"widget": (None, w.title)})


@undo_handler("dashboards.update_widget")
async def _undo_update_widget(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    w, d, editable = await get_widget(session, ctx, _wid(args))
    _require_edit(editable)
    if w.version != int(args["version"]):
        raise UndoConflict("This widget changed after your edit")
    previous: dict[str, Any] = args["previous"]
    try:
        spec = SPEC.validate_python(previous.get("query_spec", w.query_spec))
        check_any(previous.get("kind", w.kind), spec)
    except (ValidationError, ValueError):
        raise UndoConflict("The earlier version of this widget is no longer valid") from None
    for k, v in previous.items():
        setattr(w, k, v)
    w.version += 1
    d.version += 1
    await _record(session, ctx, d, "dashboard.widget_updated", {"widget": (w.title, w.title)})


@undo_handler("dashboards.place_widget")
async def _undo_move_widget(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    w, d, editable = await get_widget(session, ctx, _wid(args))
    _require_edit(editable)
    if w.version != int(args["version"]):
        raise UndoConflict("This widget changed after your move")
    w.position = str(args["position"])
    w.version += 1
    d.version += 1
    await _record(session, ctx, d, "dashboard.widget_moved", {"widget": (w.title, w.title)})


@undo_handler("dashboards.set_member")
async def _undo_set_member(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    role = args.get("role")
    await set_member(
        session,
        ctx,
        _did(args),
        uuid.UUID(str(args["user_id"])),
        str(role) if role else None,
        record_undo=False,
    )


# ---------- role templates (Phase 7.5, spec §7.5) ----------


async def create_from_template(
    session: AsyncSession,
    ctx: Ctx,
    key: str,
    portfolio_id: uuid.UUID,
    name: str | None = None,
    *,
    portfolio_tab: bool = False,
) -> tuple[Mutation[Dashboard], list[str]]:
    """A workspace dashboard from a role template bound to a portfolio (or that portfolio's
    Dashboard tab), in one undoable step; with the notes on anything left out."""
    from momentum.domain.dashboards import role_templates

    if ctx.actor.id is None:
        raise Forbidden("You can't create dashboards")
    if portfolio_tab:
        from momentum.domain.portfolios.service import get_portfolio, require_edit

        await require_edit(session, ctx, await get_portfolio(session, ctx, portfolio_id))
        if await portfolio_dashboard_of(session, portfolio_id) is not None:
            raise Conflict("This portfolio already has a dashboard", code="duplicate")
    elif not can(ctx, Action.PROJECT_CREATE):
        raise Forbidden("You can't create dashboards")
    bound = await role_templates.bind(session, ctx, key, portfolio_id)  # checked, as the viewer
    d = Dashboard(
        workspace_id=ctx.workspace_id,
        owner_id=ctx.actor.id,
        name=(name or "").strip() or bound.name,
        description=bound.description or None,
        scope="workspace",
        filters=bound.filters.model_dump(mode="json", exclude_defaults=True),
        template=key,
        portfolio_id=portfolio_id if portfolio_tab else None,
    )
    session.add(d)
    await session.flush()
    for w, pos in zip(bound.widgets, _keys(None, len(bound.widgets)), strict=True):
        viz = VizIn.model_validate({"size": w.size})
        session.add(_widget_row(ctx, d, w.kind, w.title, w.spec, viz, pos))
    await session.flush()
    act = await _record(
        session,
        ctx,
        d,
        "dashboard.created",
        {"name": (None, d.name), "template": (None, key)},
        undo_op("dashboards.delete", dashboard_id=d.id),
    )
    return Mutation(d, act, version=d.version), bound.notes


# ---------- dashboard from a sentence (Phase 7.5 S75-10, spec §8) ----------


async def create_from_draft(
    session: AsyncSession, ctx: Ctx, data: FromDraftIn
) -> Mutation[Dashboard]:
    """The dashboard Mo drafted, created as the person after they saw its preview: every
    widget's spec is validated and checked again (it comes back from the client), in one
    undoable step. Each widget keeps the sentence in ``created_from_prompt``."""
    if ctx.actor.id is None or not can(ctx, Action.PROJECT_CREATE):
        raise Forbidden("You can't create dashboards")
    if data.filters.portfolio_id is not None:
        from momentum.domain.portfolios.service import get_portfolio

        await get_portfolio(session, ctx, data.filters.portfolio_id)
    for w in data.widgets:
        check_any(w.kind, w.query_spec)
        await query_v2.check_any(session, ctx, w.query_spec)
    prompt = data.prompt.strip()
    d = Dashboard(
        workspace_id=ctx.workspace_id,
        owner_id=ctx.actor.id,
        name=data.name.strip(),
        description=(data.description or "").strip() or None,
        scope="workspace",
        filters=data.filters.model_dump(mode="json", exclude_defaults=True),
    )
    session.add(d)
    await session.flush()
    for w, pos in zip(data.widgets, _keys(None, len(data.widgets)), strict=True):
        row = _widget_row(ctx, d, w.kind, w.title, w.query_spec, w.viz, pos)
        row.created_from_prompt = prompt
        session.add(row)
    await session.flush()
    act = await _record(
        session,
        ctx,
        d,
        "dashboard.created",
        {"name": (None, d.name), "created_from_prompt": (None, prompt)},
        undo_op("dashboards.delete", dashboard_id=d.id),
    )
    return Mutation(d, act, version=d.version)
