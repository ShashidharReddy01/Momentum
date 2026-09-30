"""S6.3.1: goals. The one write path for goals, their links and their check-ins.

Visibility (kickoff Q5): every workspace member sees every goal; its owner and workspace admins
edit it. Progress is computed for the viewer, from the goal's ``progress_source``:

- ``manual``: the metric's position from ``start`` to ``target`` (``current``, moved by check-ins);
- ``projects``: the average completion (done / all top-level tasks) of the linked projects and of
  the projects in linked portfolios that the viewer can see, ignoring projects with no tasks;
- ``subgoals``: the average of the sub-goals' own progress (recursively).

Null when there's nothing to go on (no metric, nothing linked, no sub-goals with progress): the
UI says so instead of showing 0%. Check-ins are ``status_updates`` with ``entity_type='goal'``;
posting one sets ``goals.status`` and can move the metric, undoable in one step.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import Diff, record_activity
from momentum.core.context import Ctx
from momentum.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from momentum.core.events import emit
from momentum.core.mutation import Mutation
from momentum.core.permissions import Action, can
from momentum.core.undo import UndoConflict, undo_handler, undo_op
from momentum.domain.access import get_visible_project, visible_projects_clause
from momentum.domain.goals.models import Goal, GoalLink
from momentum.domain.goals.schemas import GoalCheckInIn, GoalIn, GoalPatchIn
from momentum.domain.portfolios.models import Portfolio, PortfolioItem
from momentum.domain.projects.models import Project
from momentum.domain.status_updates.models import StatusUpdate
from momentum.domain.status_updates.service import body_text
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.users.models import User

MAX_DEPTH = 4  # a goal, its sub-goals, theirs, and one more level


def _channels(g: Goal) -> list[str]:
    return [f"goal:{g.id}"]


async def get_goal(
    session: AsyncSession, ctx: Ctx, goal_id: uuid.UUID, *, include_deleted: bool = False
) -> Goal:
    g = await session.get(Goal, goal_id)
    if g is None or g.workspace_id != ctx.workspace_id:
        raise NotFound("Goal not found")
    if g.deleted_at is not None and not include_deleted:
        raise NotFound("Goal not found")
    return g


def can_edit(ctx: Ctx, g: Goal) -> bool:
    return ctx.actor.is_admin or g.owner_id == ctx.actor.id


def _require_edit(ctx: Ctx, g: Goal) -> None:
    if not can_edit(ctx, g):
        raise Forbidden("Only the goal's owner or a workspace admin can change it")


async def _record(
    session: AsyncSession,
    ctx: Ctx,
    g: Goal,
    verb: str,
    changes: Diff | None = None,
    undo: dict[str, Any] | None = None,
) -> uuid.UUID:
    act = await record_activity(
        session,
        ctx,
        entity_type="goal",
        entity_id=g.id,
        verb=verb,
        changes=changes or {},
        undo=undo,
    )
    await emit(
        session,
        ctx,
        type=verb,
        entity_type="goal",
        entity_id=g.id,
        data={"version": g.version},
        channels=_channels(g),
        activity_id=act.id,
    )
    return act.id


# ---------- progress ----------


def metric_progress(metric: dict[str, Any] | None) -> float | None:
    if not metric or metric.get("current") is None:
        return None
    start, target, current = (
        float(metric.get("start", 0)),
        float(metric["target"]),
        float(metric["current"]),
    )
    if target == start:
        return 1.0 if current == target else None
    return max(0.0, min(1.0, (current - start) / (target - start)))


class Progress:
    """Progress of every goal in the workspace, for one viewer (goals are few; one pass)."""

    def __init__(self) -> None:
        self.by_goal: dict[uuid.UUID, float | None] = {}
        self.project_completion: dict[uuid.UUID, float | None] = {}
        self.visible_projects: set[uuid.UUID] = set()
        self.links: dict[uuid.UUID, list[GoalLink]] = {}
        self.portfolio_projects: dict[uuid.UUID, list[uuid.UUID]] = {}


async def compute_progress(session: AsyncSession, ctx: Ctx) -> Progress:
    out = Progress()
    goals = list(
        (
            await session.execute(
                select(Goal).where(Goal.workspace_id == ctx.workspace_id, Goal.deleted_at.is_(None))
            )
        ).scalars()
    )
    children: dict[uuid.UUID, list[Goal]] = {}
    for g in goals:
        if g.parent_id:
            children.setdefault(g.parent_id, []).append(g)
    for link in (
        await session.execute(select(GoalLink).where(GoalLink.workspace_id == ctx.workspace_id))
    ).scalars():
        out.links.setdefault(link.goal_id, []).append(link)
    portfolio_ids = {
        link.entity_id
        for links in out.links.values()
        for link in links
        if link.entity_type == "portfolio"
    }
    if portfolio_ids:
        for pf, pid in (
            await session.execute(
                select(PortfolioItem.portfolio_id, PortfolioItem.project_id).where(
                    PortfolioItem.portfolio_id.in_(portfolio_ids)
                )
            )
        ).all():
            out.portfolio_projects.setdefault(pf, []).append(pid)
    project_ids = {
        link.entity_id
        for links in out.links.values()
        for link in links
        if link.entity_type == "project"
    } | {pid for ids in out.portfolio_projects.values() for pid in ids}
    if project_ids:
        out.visible_projects = set(
            (
                await session.execute(
                    select(Project.id).where(
                        Project.id.in_(project_ids),
                        Project.deleted_at.is_(None),
                        visible_projects_clause(ctx),
                    )
                )
            ).scalars()
        )
    if out.visible_projects:
        for pid, total, done in (
            await session.execute(
                select(TaskProject.project_id, func.count(), func.count(Task.completed_at))
                .join(Task, Task.id == TaskProject.task_id)
                .where(
                    TaskProject.project_id.in_(out.visible_projects),
                    Task.parent_id.is_(None),
                    Task.deleted_at.is_(None),
                )
                .group_by(TaskProject.project_id)
            )
        ).all():
            out.project_completion[pid] = done / total if total else None

    def projects_of(goal_id: uuid.UUID) -> list[uuid.UUID]:
        ids: list[uuid.UUID] = []
        for link in out.links.get(goal_id, []):
            if link.entity_type == "project":
                ids.append(link.entity_id)
            else:
                ids.extend(out.portfolio_projects.get(link.entity_id, []))
        return [i for i in dict.fromkeys(ids) if i in out.visible_projects]

    visiting: set[uuid.UUID] = set()

    def progress(g: Goal) -> float | None:
        if g.id in out.by_goal:
            return out.by_goal[g.id]
        if g.id in visiting:
            return None  # a cycle the API refuses; never loop
        visiting.add(g.id)
        if g.progress_source == "manual":
            value = metric_progress(g.metric)
        elif g.progress_source == "projects":
            vals = [
                v for pid in projects_of(g.id) if (v := out.project_completion.get(pid)) is not None
            ]
            value = sum(vals) / len(vals) if vals else None
        else:
            vals = [v for c in children.get(g.id, []) if (v := progress(c)) is not None]
            value = sum(vals) / len(vals) if vals else None
        visiting.discard(g.id)
        out.by_goal[g.id] = value
        return value

    for g in goals:
        progress(g)
    return out


# ---------- goals ----------


async def list_goals(session: AsyncSession, ctx: Ctx) -> tuple[list[Goal], Progress]:
    goals = list(
        (
            await session.execute(
                select(Goal)
                .where(Goal.workspace_id == ctx.workspace_id, Goal.deleted_at.is_(None))
                .order_by(Goal.period_start.desc(), func.lower(Goal.name))
            )
        ).scalars()
    )
    return goals, await compute_progress(session, ctx)


async def _check_owner(session: AsyncSession, ctx: Ctx, owner_id: uuid.UUID) -> None:
    u = await session.get(User, owner_id)
    if u is None or u.workspace_id != ctx.workspace_id or u.is_agent:
        raise ValidationFailed("The owner must be a person in this workspace")


async def _check_parent(
    session: AsyncSession, ctx: Ctx, goal_id: uuid.UUID | None, parent_id: uuid.UUID
) -> None:
    """The parent exists here, isn't this goal or one of its descendants, and the tree stays
    within MAX_DEPTH levels."""
    parent = await get_goal(session, ctx, parent_id)
    depth = 1
    cur: Goal | None = parent
    while cur is not None:
        if goal_id is not None and cur.id == goal_id:
            raise ValidationFailed(
                "A goal can't sit under itself or one of its sub-goals", code="goal_cycle"
            )
        depth += 1
        cur = await session.get(Goal, cur.parent_id) if cur.parent_id else None
    if depth > MAX_DEPTH:
        raise ValidationFailed(f"Goals nest at most {MAX_DEPTH} levels deep", code="too_deep")


async def create_goal(session: AsyncSession, ctx: Ctx, data: GoalIn) -> Mutation[Goal]:
    if ctx.actor.id is None or not can(ctx, Action.PROJECT_CREATE):
        raise Forbidden("You can't create goals")
    name = data.name.strip()
    if not name:
        raise ValidationFailed("Goal name can't be empty")
    owner = data.owner_id or ctx.actor.id
    await _check_owner(session, ctx, owner)
    if data.parent_id is not None:
        await _check_parent(session, ctx, None, data.parent_id)
    g = Goal(
        workspace_id=ctx.workspace_id,
        parent_id=data.parent_id,
        name=name,
        description=(data.description or "").strip() or None,
        owner_id=owner,
        period_start=data.period_start,
        period_end=data.period_end,
        period_label=(data.period_label or "").strip() or None,
        metric=data.metric.model_dump() if data.metric else None,
        progress_source=data.progress_source,
    )
    session.add(g)
    await session.flush()
    act = await _record(
        session,
        ctx,
        g,
        "goal.created",
        {"name": (None, g.name)},
        undo_op("goals.delete", goal_id=g.id),
    )
    return Mutation(g, act, version=g.version)


async def update_goal(
    session: AsyncSession,
    ctx: Ctx,
    goal_id: uuid.UUID,
    patch: GoalPatchIn,
    *,
    record_undo: bool = True,
) -> Mutation[Goal]:
    g = await get_goal(session, ctx, goal_id)
    _require_edit(ctx, g)
    fields = patch.model_fields_set
    if "owner_id" in fields:
        if patch.owner_id is None:
            raise ValidationFailed("A goal needs an owner")
        await _check_owner(session, ctx, patch.owner_id)
    if "parent_id" in fields and patch.parent_id is not None:
        await _check_parent(session, ctx, g.id, patch.parent_id)
    start = patch.period_start if "period_start" in fields else g.period_start
    end = patch.period_end if "period_end" in fields else g.period_end
    if start is None or end is None or start > end:
        raise ValidationFailed("The period ends before it starts", code="period_out_of_order")
    changes: Diff = {}
    for f in fields:
        new: Any = getattr(patch, f)
        if f == "metric":
            new = patch.metric.model_dump() if patch.metric else None
        elif isinstance(new, str):
            new = new.strip() or (None if f in ("description", "period_label") else new)
            if f == "name" and not new:
                raise ValidationFailed("Goal name can't be empty")
        if getattr(g, f) != new:
            changes[f] = (getattr(g, f), new)
            setattr(g, f, new)
    if not changes:
        return Mutation(g, version=g.version)
    g.version += 1
    act = await _record(
        session,
        ctx,
        g,
        "goal.updated",
        changes,
        undo_op(
            "goals.update",
            goal_id=g.id,
            version=g.version,
            patch={k: o for k, (o, _) in changes.items()},
        )
        if record_undo
        else None,
    )
    return Mutation(g, act, version=g.version)


async def delete_goal(
    session: AsyncSession, ctx: Ctx, goal_id: uuid.UUID, *, record_undo: bool = True
) -> Mutation[Goal]:
    g = await get_goal(session, ctx, goal_id)
    _require_edit(ctx, g)
    has_children = (
        await session.execute(
            select(func.count()).where(Goal.parent_id == g.id, Goal.deleted_at.is_(None))
        )
    ).scalar_one()
    if has_children:
        raise Conflict("Move or delete its sub-goals first", code="has_subgoals")
    g.deleted_at = datetime.now(UTC)
    g.version += 1
    act = await _record(
        session,
        ctx,
        g,
        "goal.deleted",
        undo=undo_op("goals.restore", goal_id=g.id) if record_undo else None,
    )
    return Mutation(g, act, version=g.version)


# ---------- links ----------


async def link(
    session: AsyncSession,
    ctx: Ctx,
    goal_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    *,
    record_undo: bool = True,
) -> Mutation[Goal]:
    g = await get_goal(session, ctx, goal_id)
    _require_edit(ctx, g)
    if entity_type == "project":
        target, _ = await get_visible_project(session, ctx, entity_id)  # you link what you see
        label = target.name
    else:
        pf = await session.get(Portfolio, entity_id)
        if pf is None or pf.workspace_id != ctx.workspace_id or pf.deleted_at is not None:
            raise NotFound("Portfolio not found")
        label = pf.name
    if await session.get(GoalLink, (g.id, entity_type, entity_id)) is not None:
        raise Conflict("Already linked", code="already_linked")
    session.add(
        GoalLink(
            goal_id=g.id,
            entity_type=entity_type,
            entity_id=entity_id,
            workspace_id=ctx.workspace_id,
        )
    )
    g.version += 1
    await session.flush()
    act = await _record(
        session,
        ctx,
        g,
        "goal.linked",
        {entity_type: (None, label)},
        undo_op("goals.unlink", goal_id=g.id, entity_type=entity_type, entity_id=entity_id)
        if record_undo
        else None,
    )
    return Mutation(g, act, version=g.version)


async def unlink(
    session: AsyncSession,
    ctx: Ctx,
    goal_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    *,
    record_undo: bool = True,
) -> Mutation[Goal]:
    g = await get_goal(session, ctx, goal_id)
    _require_edit(ctx, g)
    row = await session.get(GoalLink, (g.id, entity_type, entity_id))
    if row is None:
        raise NotFound("That isn't linked to this goal")
    await session.delete(row)
    g.version += 1
    await session.flush()
    act = await _record(
        session,
        ctx,
        g,
        "goal.unlinked",
        {entity_type: (str(entity_id), None)},
        undo_op("goals.link", goal_id=g.id, entity_type=entity_type, entity_id=entity_id)
        if record_undo
        else None,
    )
    return Mutation(g, act, version=g.version)


async def link_views(
    session: AsyncSession, ctx: Ctx, g: Goal, progress: Progress
) -> tuple[list[dict[str, Any]], int]:
    """(the goal's links the viewer can see, with names, status and progress; how many linked
    projects they can't see)."""
    views: list[dict[str, Any]] = []
    hidden = 0
    for link_row in progress.links.get(g.id, []):
        if link_row.entity_type == "project":
            if link_row.entity_id not in progress.visible_projects:
                hidden += 1
                continue
            p = await session.get(Project, link_row.entity_id)
            if p is None:
                continue
            views.append(
                {
                    "entity_type": "project",
                    "id": p.id,
                    "name": p.name,
                    "status": p.status,
                    "progress": progress.project_completion.get(p.id),
                }
            )
        else:
            pf = await session.get(Portfolio, link_row.entity_id)
            if pf is None or pf.deleted_at is not None:
                continue
            vals = [
                v
                for pid in progress.portfolio_projects.get(pf.id, [])
                if pid in progress.visible_projects
                and (v := progress.project_completion.get(pid)) is not None
            ]
            views.append(
                {
                    "entity_type": "portfolio",
                    "id": pf.id,
                    "name": pf.name,
                    "status": pf.status,
                    "progress": sum(vals) / len(vals) if vals else None,
                }
            )
    return views, hidden


# ---------- check-ins ----------


async def list_check_ins(
    session: AsyncSession, ctx: Ctx, goal_id: uuid.UUID, *, limit: int = 20
) -> list[StatusUpdate]:
    g = await get_goal(session, ctx, goal_id)
    return list(
        (
            await session.execute(
                select(StatusUpdate)
                .where(
                    StatusUpdate.entity_type == "goal",
                    StatusUpdate.entity_id == g.id,
                    StatusUpdate.deleted_at.is_(None),
                )
                .order_by(StatusUpdate.created_at.desc(), StatusUpdate.id.desc())
                .limit(limit)
            )
        ).scalars()
    )


async def check_in(
    session: AsyncSession, ctx: Ctx, goal_id: uuid.UUID, data: GoalCheckInIn
) -> Mutation[StatusUpdate]:
    g = await get_goal(session, ctx, goal_id)
    _require_edit(ctx, g)
    if data.current is not None and not g.metric:
        raise ValidationFailed("This goal has no metric to move", code="no_metric")
    update = StatusUpdate(
        workspace_id=ctx.workspace_id,
        entity_type="goal",
        entity_id=g.id,
        status=data.status,
        title=data.title.strip(),
        body={"summary": data.summary.strip(), "sections": data.sections.model_dump()},
        body_text=body_text(data),
        author_id=ctx.actor.id,
        generated_by_ai=data.generated_by_ai or ctx.via in ("ai", "agent"),
        created_via=ctx.via,
    )
    session.add(update)
    previous_status = g.status
    previous_current = (g.metric or {}).get("current")
    changes: Diff = {"status": (previous_status, data.status), "check_in": (None, update.title)}
    g.status = data.status
    if data.current is not None and g.metric:
        g.metric = {**g.metric, "current": data.current}
        changes["current"] = (previous_current, data.current)
    g.version += 1
    await session.flush()
    act = await _record(
        session,
        ctx,
        g,
        "goal.checked_in",
        changes,
        undo_op(
            "goals.withdraw_check_in",
            update_id=update.id,
            goal_id=g.id,
            previous_status=previous_status,
            previous_current=previous_current,
            moved_current=data.current is not None,
        ),
    )
    return Mutation(update, act, version=g.version)


# ---------- undo ----------


def _gid(args: dict[str, Any]) -> uuid.UUID:
    return uuid.UUID(str(args["goal_id"]))


@undo_handler("goals.delete")
async def _undo_create(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    await delete_goal(session, ctx, _gid(args), record_undo=False)


@undo_handler("goals.restore")
async def _undo_delete(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    g = await get_goal(session, ctx, _gid(args), include_deleted=True)
    _require_edit(ctx, g)
    if g.deleted_at is None:
        raise UndoConflict("The goal is not deleted")
    g.deleted_at = None
    g.version += 1
    await _record(session, ctx, g, "goal.restored")


@undo_handler("goals.update")
async def _undo_update(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    g = await get_goal(session, ctx, _gid(args))
    if g.version != int(args["version"]):
        raise UndoConflict("This goal changed after your edit")
    await update_goal(session, ctx, g.id, GoalPatchIn(**args["patch"]), record_undo=False)


@undo_handler("goals.unlink")
async def _undo_link(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    await unlink(
        session,
        ctx,
        _gid(args),
        str(args["entity_type"]),
        uuid.UUID(str(args["entity_id"])),
        record_undo=False,
    )


@undo_handler("goals.link")
async def _undo_unlink(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    await link(
        session,
        ctx,
        _gid(args),
        str(args["entity_type"]),
        uuid.UUID(str(args["entity_id"])),
        record_undo=False,
    )


@undo_handler("goals.withdraw_check_in")
async def _undo_check_in(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    update = await session.get(StatusUpdate, uuid.UUID(str(args["update_id"])))
    if update is None or update.deleted_at is not None:
        raise UndoConflict("That check-in is already gone")
    g = await get_goal(session, ctx, _gid(args))
    if g.status != update.status:
        raise UndoConflict("The goal's status changed after this check-in")
    update.deleted_at = datetime.now(UTC)
    g.status = args.get("previous_status")
    if args.get("moved_current") and g.metric:
        g.metric = {**g.metric, "current": args.get("previous_current")}
    g.version += 1
    await _record(session, ctx, g, "goal.check_in_withdrawn")
