"""S6.5.1: dashboards and their widgets. The one write path for both.

Visibility (kickoff Q5): a **workspace** dashboard is visible to every workspace member and edited
by its owner or a workspace admin; a **project** dashboard (the project's Dashboard tab, one per
project) follows the project: whoever can see the project sees it, its editors and admins edit
it. Every number inside is computed per request **as the viewer** (``query.run``), so the same
dashboard can show different numbers to different people, and a widget's stored spec never
grants anything.

Until a project has a saved dashboard, its tab shows the starter layout live (``starter()``); the
first edit saves it (``create_dashboard`` with ``starter=True``), one undo.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import Diff, record_activity
from momentum.core.context import Ctx
from momentum.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from momentum.core.events import emit
from momentum.core.mutation import Mutation
from momentum.core.ordering import key_between
from momentum.core.permissions import Action, can
from momentum.core.undo import UndoConflict, undo_handler, undo_op
from momentum.domain.access import ROLE_RANK, forbid_agent, get_visible_project
from momentum.domain.dashboards import query
from momentum.domain.dashboards.models import Dashboard, DashboardWidget
from momentum.domain.dashboards.schemas import (
    DashboardIn,
    DashboardPatchIn,
    DrillIn,
    DrillOut,
    QueryFilters,
    QueryResultOut,
    QuerySpec,
    StarterWidgetOut,
    VizIn,
    WidgetIn,
    WidgetKind,
    WidgetMoveIn,
    WidgetPatchIn,
    check_kind,
)

MAX_WIDGETS = 24


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
    return d, ctx.actor.is_admin or d.owner_id == ctx.actor.id


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
    elif not can(ctx, Action.PROJECT_CREATE):
        raise Forbidden("You can't create dashboards")
    d = Dashboard(
        workspace_id=ctx.workspace_id,
        owner_id=ctx.actor.id,
        name=name,
        description=(data.description or "").strip() or None,
        scope="project" if data.project_id else "workspace",
        project_id=data.project_id,
    )
    session.add(d)
    await session.flush()
    if data.starter:
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
    spec: QuerySpec,
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


def _check_scope(d: Dashboard, spec: QuerySpec) -> None:
    if d.project_id is not None and spec.filters.project_ids:
        raise ValidationFailed("A project dashboard always shows its own project")


def widget_spec(w: DashboardWidget) -> QuerySpec:
    return QuerySpec.model_validate(w.query_spec)


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
    _check_scope(d, data.query_spec)
    await query.check_spec(session, ctx, data.query_spec)
    live = await widgets_of(session, d)
    if len(live) >= MAX_WIDGETS:
        raise ValidationFailed(f"A dashboard holds up to {MAX_WIDGETS} widgets")
    if position is None:
        position = key_between(live[-1].position if live else None, None)
    w = _widget_row(ctx, d, data.kind, data.title, data.query_spec, data.viz, position)
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
    kind: WidgetKind = patch.kind or w.kind  # type: ignore[assignment]
    spec = patch.query_spec or widget_spec(w)
    try:
        check_kind(kind, spec)
    except ValueError as e:
        raise ValidationFailed(str(e)) from None
    if patch.query_spec is not None:
        _check_scope(d, spec)
        await query.check_spec(session, ctx, spec)
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


async def widget_data(session: AsyncSession, ctx: Ctx, widget_id: uuid.UUID) -> QueryResultOut:
    w, d, _ = await get_widget(session, ctx, widget_id)
    return await query.run(session, ctx, w.kind, widget_spec(w), project_id=d.project_id)  # type: ignore[arg-type]


async def run_query(
    session: AsyncSession,
    ctx: Ctx,
    kind: WidgetKind,
    spec: QuerySpec,
    project_id: uuid.UUID | None,
) -> QueryResultOut:
    """An unsaved spec (the add-chart preview, the starter layout), run as the viewer."""
    return await query.run(session, ctx, kind, spec, project_id=project_id)


async def drill(session: AsyncSession, ctx: Ctx, body: DrillIn) -> DrillOut:
    return await query.drill(session, ctx, body)


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
        spec = QuerySpec.model_validate(previous.get("query_spec", w.query_spec))
        check_kind(previous.get("kind", w.kind), spec)
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
