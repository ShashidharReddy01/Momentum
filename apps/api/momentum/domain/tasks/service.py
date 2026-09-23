"""Tasks: create, edit, complete, delete, list (phase-1.md S1.2.2)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import Activity, Diff, jsonable_diff, record_activity
from momentum.core.context import Ctx
from momentum.core.errors import NotFound, ValidationFailed
from momentum.core.events import emit
from momentum.core.mutation import Mutation
from momentum.core.ordering import even_keys, key_between, keys_between, needs_rebalance
from momentum.core.undo import UndoConflict, undo_handler, undo_op
from momentum.domain.access import (
    get_visible_project,
    get_visible_task,
    require_project_role,
)
from momentum.domain.sections.models import Section
from momentum.domain.sections.service import list_sections, on_section_delete, on_section_restore
from momentum.domain.tasks.models import Follower, Task, TaskProject
from momentum.domain.users.models import User
from momentum.domain.workspace.models import Workspace

COMPLETED_PAGE = 100


def channels(task: Task, placement: TaskProject | None) -> list[str]:
    out = [f"task:{task.id}"]
    if placement is not None:
        out.append(f"project:{placement.project_id}")
    if task.assignee_id is not None:
        out.append(f"user:{task.assignee_id}")
    return out


async def _next_number(session: AsyncSession, workspace_id: uuid.UUID) -> int:
    result = await session.execute(
        update(Workspace)
        .where(Workspace.id == workspace_id)
        .values(task_seq=Workspace.task_seq + 1)
        .returning(Workspace.task_seq)
    )
    return int(result.scalar_one())


async def _section_for(
    session: AsyncSession, project_id: uuid.UUID, section_id: uuid.UUID | None
) -> Section:
    sections = await list_sections(session, project_id)
    if not sections:
        raise NotFound("Project has no sections")
    if section_id is None:
        return sections[0]
    for s in sections:
        if s.id == section_id:
            return s
    raise NotFound("Section not found")


async def _ordered_placements(
    session: AsyncSession, project_id: uuid.UUID, section_id: uuid.UUID
) -> list[TaskProject]:
    rows = await session.execute(
        select(TaskProject)
        .join(Task, Task.id == TaskProject.task_id)
        .where(
            TaskProject.project_id == project_id,
            TaskProject.section_id == section_id,
            Task.deleted_at.is_(None),
            Task.parent_id.is_(None),
        )
        .order_by(TaskProject.position, TaskProject.task_id)
    )
    return list(rows.scalars())


async def _slot(
    session: AsyncSession,
    project_id: uuid.UUID,
    section_id: uuid.UUID,
    after_id: uuid.UUID | None,
    before_id: uuid.UUID | None,
    exclude: set[uuid.UUID],
) -> tuple[str | None, str | None]:
    """Neighbor keys for an insert after ``after_id`` / before ``before_id`` / at the end."""
    items = [
        p
        for p in await _ordered_placements(session, project_id, section_id)
        if p.task_id not in exclude
    ]
    ids = [p.task_id for p in items]
    if after_id is not None:
        if after_id not in ids:
            raise NotFound("Neighbor task not found in this section")
        i = ids.index(after_id)
        return items[i].position, items[i + 1].position if i + 1 < len(items) else None
    if before_id is not None:
        if before_id not in ids:
            raise NotFound("Neighbor task not found in this section")
        i = ids.index(before_id)
        return items[i - 1].position if i > 0 else None, items[i].position
    return (items[-1].position if items else None), None


async def _rebalance(session: AsyncSession, project_id: uuid.UUID, section_id: uuid.UUID) -> None:
    """Re-space every placement in a section, keeping order. Includes deleted tasks (so restores
    sort correctly) and tasks being moved (so their undo positions stay consistent)."""
    rows = (
        (
            await session.execute(
                select(TaskProject)
                .where(TaskProject.project_id == project_id, TaskProject.section_id == section_id)
                .order_by(TaskProject.position, TaskProject.task_id)
            )
        )
        .scalars()
        .all()
    )
    for row, key in zip(rows, even_keys(len(rows)), strict=True):
        row.position = key
    await session.flush()


async def _keys_for(
    session: AsyncSession,
    project_id: uuid.UUID,
    section_id: uuid.UUID,
    n: int,
    *,
    after_id: uuid.UUID | None = None,
    before_id: uuid.UUID | None = None,
    exclude: set[uuid.UUID] | None = None,
) -> list[str]:
    """n order keys for consecutive items at a slot; rebalances the section if keys got long."""
    skip = exclude or set()
    for attempt in range(2):
        a, b = await _slot(session, project_id, section_id, after_id, before_id, skip)
        keys = [key_between(a, b)] if n == 1 else keys_between(a, b, n)
        if attempt == 1 or not any(needs_rebalance(k) for k in keys):
            return keys
        await _rebalance(session, project_id, section_id)
    raise AssertionError("unreachable")


def _as_uuid(v: Any) -> uuid.UUID | None:
    return None if v is None else v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))


def _as_date(v: Any) -> date | None:
    if v is None or (isinstance(v, date) and not isinstance(v, datetime)):
        return v
    return date.fromisoformat(str(v))


def _as_datetime(v: Any) -> datetime | None:
    if v is None:
        return None
    dt = v if isinstance(v, datetime) else datetime.fromisoformat(str(v))
    if dt.tzinfo is None:
        raise ValidationFailed("Due time needs a timezone", code="naive_datetime")
    return dt.astimezone(UTC)


def _local_date(dt: datetime, tz: str) -> date:
    try:
        return dt.astimezone(ZoneInfo(tz)).date()
    except (KeyError, ValueError):
        return dt.astimezone(UTC).date()


async def _require_assignable(session: AsyncSession, ctx: Ctx, user_id: uuid.UUID) -> None:
    user = await session.get(User, user_id)
    if user is None or user.workspace_id != ctx.workspace_id or user.status == "disabled":
        raise ValidationFailed("That person can't be assigned", code="invalid_assignee")


async def _follow(session: AsyncSession, task_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
    if user_id is not None and await session.get(Follower, (task_id, user_id)) is None:
        session.add(Follower(task_id=task_id, user_id=user_id))


# ---------- reads ----------


async def list_project_tasks(
    session: AsyncSession,
    ctx: Ctx,
    project_id: uuid.UUID,
    *,
    completed: bool = False,
    before: datetime | None = None,
) -> list[tuple[Task, TaskProject]]:
    """Top-level tasks of a project. Incomplete tasks: all of them, in section/position order.
    Completed tasks: newest first, paged by ``before`` (completed_at cursor)."""
    await get_visible_project(session, ctx, project_id)
    query = (
        select(Task, TaskProject)
        .join(TaskProject, TaskProject.task_id == Task.id)
        .join(Section, Section.id == TaskProject.section_id)
        .where(
            TaskProject.project_id == project_id,
            Task.deleted_at.is_(None),
            Task.parent_id.is_(None),
            Section.deleted_at.is_(None),
        )
    )
    if completed:
        query = query.where(Task.completed_at.is_not(None))
        if before is not None:
            query = query.where(Task.completed_at < before)
        query = query.order_by(Task.completed_at.desc()).limit(COMPLETED_PAGE)
    else:
        query = query.where(Task.completed_at.is_(None)).order_by(
            Section.position, TaskProject.position, Task.id
        )
    return [(t, p) for t, p in (await session.execute(query)).all()]


async def get_task(
    session: AsyncSession, ctx: Ctx, task_id: uuid.UUID
) -> tuple[Task, TaskProject | None, str]:
    return await get_visible_task(session, ctx, task_id)


async def placements_for(
    session: AsyncSession, task_ids: list[uuid.UUID]
) -> dict[uuid.UUID, TaskProject]:
    """Home-project placement per task (one query; Phase 1 tasks live in one project)."""
    if not task_ids:
        return {}
    rows = await session.execute(select(TaskProject).where(TaskProject.task_id.in_(task_ids)))
    return {p.task_id: p for p in rows.scalars()}


# ---------- writes ----------


async def create_task(
    session: AsyncSession,
    ctx: Ctx,
    project_id: uuid.UUID,
    title: str,
    *,
    section_id: uuid.UUID | None = None,
    after_id: uuid.UUID | None = None,
    before_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
) -> Mutation[tuple[Task, TaskProject]]:
    _, role = await get_visible_project(session, ctx, project_id)
    require_project_role(role, "editor", "add tasks")
    title = " ".join(title.split())
    if not title:
        raise ValidationFailed("Task name can't be empty")
    section = await _section_for(session, project_id, section_id)
    (position,) = await _keys_for(
        session, project_id, section.id, 1, after_id=after_id, before_id=before_id
    )
    task = Task(
        workspace_id=ctx.workspace_id,
        number=await _next_number(session, ctx.workspace_id),
        title=title,
        created_by=ctx.actor.id,
        created_via=ctx.via,
    )
    session.add(task)
    await session.flush()
    placement = TaskProject(
        task_id=task.id,
        project_id=project_id,
        section_id=section.id,
        position=position,
        added_by=ctx.actor.id,
    )
    session.add(placement)
    await _follow(session, task.id, ctx.actor.id)
    act = await record_activity(
        session,
        ctx,
        entity_type="task",
        entity_id=task.id,
        verb="task.created",
        changes={"title": (None, title)},
        undo=undo_op("tasks.delete", task_id=task.id),
        batch_id=batch_id,
    )
    await emit(
        session,
        ctx,
        type="task.created",
        entity_type="task",
        entity_id=task.id,
        data={
            "project_id": str(project_id),
            "section_id": str(section.id),
            "position": placement.position,
        },
        channels=channels(task, placement),
        activity_id=act.id,
    )
    await session.flush()
    return Mutation((task, placement), act.id, batch_id=batch_id, version=task.version)


async def create_tasks(
    session: AsyncSession,
    ctx: Ctx,
    project_id: uuid.UUID,
    titles: list[str],
    *,
    section_id: uuid.UUID | None = None,
    after_id: uuid.UUID | None = None,
) -> Mutation[list[tuple[Task, TaskProject]]]:
    """Create several tasks in order (e.g. pasted lines) as one undoable batch."""
    clean = [" ".join(t.split()) for t in titles]
    clean = [t[:500] for t in clean if t]
    if not clean:
        raise ValidationFailed("Nothing to create")
    batch_id = uuid.uuid4()
    created: list[tuple[Task, TaskProject]] = []
    prev = after_id
    for title in clean:
        m = await create_task(
            session, ctx, project_id, title, section_id=section_id, after_id=prev, batch_id=batch_id
        )
        created.append(m.entity)
        prev = m.entity[0].id
        section_id = m.entity[1].section_id
    return Mutation(created, batch_id=batch_id)


async def update_task(
    session: AsyncSession,
    ctx: Ctx,
    task_id: uuid.UUID,
    patch: dict[str, Any],
    *,
    expected_version: int | None = None,
    record_undo: bool = True,
    batch_id: uuid.UUID | None = None,
) -> Mutation[Task]:
    task, placement, role = await get_visible_task(session, ctx, task_id)
    require_project_role(role, "editor", "edit this task")
    if expected_version is not None and expected_version != task.version:
        from momentum.core.errors import VersionConflict

        raise VersionConflict("This task was changed by someone else", version=task.version)
    changes: Diff = {}
    if "title" in patch:
        title = " ".join(str(patch["title"] or "").split())
        if not title:
            raise ValidationFailed("Task name can't be empty")
        if title != task.title:
            changes["title"] = (task.title, title)
            task.title = title
    if "assignee_id" in patch:
        assignee = _as_uuid(patch["assignee_id"])
        if assignee != task.assignee_id:
            if assignee is not None:
                await _require_assignable(session, ctx, assignee)
                await _follow(session, task.id, assignee)
            changes["assignee_id"] = (task.assignee_id, assignee)
    _apply_dates(task, patch, ctx, changes)
    if not changes:
        return Mutation(task, version=task.version)
    previous_assignee = task.assignee_id
    for field, (_, new) in changes.items():
        setattr(task, field, new)
    task.version += 1
    act = await record_activity(
        session,
        ctx,
        entity_type="task",
        entity_id=task.id,
        verb="task.updated",
        changes=changes,
        undo=undo_op(
            "tasks.update",
            task_id=task.id,
            version=task.version,
            patch={k: o for k, (o, _) in changes.items()},
        )
        if record_undo
        else None,
        batch_id=batch_id,
    )
    await emit(
        session,
        ctx,
        type="task.updated",
        entity_type="task",
        entity_id=task.id,
        data={
            "changes": jsonable_diff(changes),
            "version": task.version,
        },
        channels=channels(task, placement),
        activity_id=act.id,
    )
    if "assignee_id" in changes:
        await emit(
            session,
            ctx,
            type="task.assigned",
            entity_type="task",
            entity_id=task.id,
            data={
                "assignee_id": str(task.assignee_id) if task.assignee_id else None,
                "previous_assignee_id": str(previous_assignee) if previous_assignee else None,
            },
            channels=channels(task, placement)
            + ([f"user:{previous_assignee}"] if previous_assignee else []),
            activity_id=act.id,
        )
    return Mutation(task, act.id, batch_id=batch_id, version=task.version)


def _apply_dates(task: Task, patch: dict[str, Any], ctx: Ctx, changes: Diff) -> None:
    """Resolve start_on/due_on/due_at from a partial patch and record what changes.

    Rules: due_at without due_on derives due_on in the actor's timezone; clearing due_on
    clears due_at; start_on must not be after due_on."""
    if not {"start_on", "due_on", "due_at"} & patch.keys():
        return
    start = _as_date(patch["start_on"]) if "start_on" in patch else task.start_on
    due = _as_date(patch["due_on"]) if "due_on" in patch else task.due_on
    due_at = _as_datetime(patch["due_at"]) if "due_at" in patch else task.due_at
    if "due_at" in patch and due_at is not None and "due_on" not in patch:
        due = _local_date(due_at, ctx.actor.timezone)
    if due is None:
        due_at = None
    if start is not None and due is not None and start > due:
        raise ValidationFailed(
            "Start date must be on or before the due date", code="dates_out_of_order"
        )
    for field, new in (("start_on", start), ("due_on", due), ("due_at", due_at)):
        if new != getattr(task, field):
            changes[field] = (getattr(task, field), new)


async def set_completed(
    session: AsyncSession,
    ctx: Ctx,
    task_id: uuid.UUID,
    completed: bool,
    *,
    record_undo: bool = True,
    batch_id: uuid.UUID | None = None,
) -> Mutation[Task]:
    task, placement, role = await get_visible_task(session, ctx, task_id)
    require_project_role(role, "editor", "complete this task")
    if (task.completed_at is not None) == completed:
        return Mutation(task, version=task.version)
    old = task.completed_at
    task.completed_at = datetime.now(UTC) if completed else None
    task.completed_by = ctx.actor.id if completed else None
    task.version += 1
    verb = "task.completed" if completed else "task.uncompleted"
    act = await record_activity(
        session,
        ctx,
        entity_type="task",
        entity_id=task.id,
        verb=verb,
        changes={"completed_at": (old, task.completed_at)},
        undo=undo_op("tasks.set_completed", task_id=task.id, completed=not completed)
        if record_undo
        else None,
        batch_id=batch_id,
    )
    await emit(
        session,
        ctx,
        type=verb,
        entity_type="task",
        entity_id=task.id,
        data={"version": task.version, "completed_by": str(ctx.actor.id) if completed else None},
        channels=channels(task, placement),
        activity_id=act.id,
    )
    return Mutation(task, act.id, batch_id=batch_id, version=task.version)


async def delete_task(
    session: AsyncSession, ctx: Ctx, task_id: uuid.UUID, *, batch_id: uuid.UUID | None = None
) -> Mutation[Task]:
    task, placement, role = await get_visible_task(session, ctx, task_id)
    require_project_role(role, "editor", "delete this task")
    task.deleted_at = datetime.now(UTC)
    task.version += 1
    act = await record_activity(
        session,
        ctx,
        entity_type="task",
        entity_id=task.id,
        verb="task.deleted",
        undo=undo_op("tasks.restore", task_id=task.id),
        batch_id=batch_id,
    )
    await emit(
        session,
        ctx,
        type="task.deleted",
        entity_type="task",
        entity_id=task.id,
        channels=channels(task, placement),
        activity_id=act.id,
    )
    return Mutation(task, act.id, batch_id=batch_id, version=task.version)


MAX_BULK = 500
BulkAction = Literal["update", "move", "complete", "uncomplete", "delete"]


def _dedupe(ids: list[uuid.UUID]) -> list[uuid.UUID]:
    return list(dict.fromkeys(ids))


async def move_tasks(
    session: AsyncSession,
    ctx: Ctx,
    task_ids: list[uuid.UUID],
    *,
    section_id: uuid.UUID,
    after_id: uuid.UUID | None = None,
    before_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
) -> Mutation[list[tuple[Task, TaskProject]]]:
    """Move tasks (keeping their current relative order) to a slot in a section of their project.

    All tasks must be top-level tasks of the same project and editable by the actor; the anchor
    (``after_id``/``before_id``) must not be one of the moved tasks. One task → one activity;
    several → one batch (a single undo)."""
    ids = _dedupe(task_ids)
    if not ids:
        raise ValidationFailed("Nothing to move")
    if len(ids) > MAX_BULK:
        raise ValidationFailed(f"At most {MAX_BULK} tasks at a time", code="too_many")
    if after_id is not None and before_id is not None:
        raise ValidationFailed("Give after_id or before_id, not both")
    if after_id in ids or before_id in ids:
        raise ValidationFailed("A task can't be moved next to itself", code="invalid_anchor")
    section = await session.get(Section, section_id)
    if section is None or section.deleted_at is not None:
        raise NotFound("Section not found")
    items: list[tuple[Task, TaskProject]] = []
    for tid in ids:
        task, placement, role = await get_visible_task(session, ctx, tid)
        require_project_role(role, "editor", "move this task")
        if placement is None or task.parent_id is not None:
            raise ValidationFailed("Only top-level project tasks can be moved", code="not_movable")
        if placement.project_id != section.project_id:
            raise ValidationFailed(
                "Tasks can only move within their project", code="cross_project_move"
            )
        items.append((task, placement))
    # keep the tasks' current visual order (section order, then position)
    section_order = {
        s.id: i for i, s in enumerate(await list_sections(session, section.project_id))
    }
    items.sort(key=lambda tp: (section_order.get(tp[1].section_id, 0), tp[1].position, tp[0].id))
    keys = await _keys_for(
        session,
        section.project_id,
        section.id,
        len(items),
        after_id=after_id,
        before_id=before_id,
        exclude=set(ids),
    )
    if len(items) > 1 and batch_id is None:
        batch_id = uuid.uuid4()
    last: Activity | None = None
    for (task, placement), key in zip(items, keys, strict=True):
        old_section, old_position = placement.section_id, placement.position
        placement.section_id, placement.position = section.id, key
        changes: Diff = {"position": (old_position, key)}
        if old_section != section.id:
            changes["section_id"] = (old_section, section.id)
        last = await record_activity(
            session,
            ctx,
            entity_type="task",
            entity_id=task.id,
            verb="task.moved",
            changes=changes,
            undo=undo_op(
                "tasks.move_back",
                task_id=task.id,
                project_id=section.project_id,
                section_id=old_section,
                position=old_position,
                expect_section_id=section.id,
                expect_position=key,
            ),
            batch_id=batch_id,
        )
        await emit(
            session,
            ctx,
            type="task.moved",
            entity_type="task",
            entity_id=task.id,
            data={"section_id": str(section.id), "position": key},
            channels=channels(task, placement),
            activity_id=last.id,
        )
    await session.flush()
    return Mutation(items, last.id if last and batch_id is None else None, batch_id=batch_id)


async def bulk(
    session: AsyncSession,
    ctx: Ctx,
    task_ids: list[uuid.UUID],
    action: BulkAction,
    *,
    patch: dict[str, Any] | None = None,
    section_id: uuid.UUID | None = None,
    after_id: uuid.UUID | None = None,
    before_id: uuid.UUID | None = None,
) -> Mutation[list[Task]]:
    """Apply one action to many tasks, all-or-nothing, as one undoable batch."""
    ids = _dedupe(task_ids)
    if not ids:
        raise ValidationFailed("No tasks selected")
    if len(ids) > MAX_BULK:
        raise ValidationFailed(f"At most {MAX_BULK} tasks at a time", code="too_many")
    batch_id = uuid.uuid4()
    if action == "move":
        if section_id is None:
            raise ValidationFailed("Choose a section to move to")
        m = await move_tasks(
            session,
            ctx,
            ids,
            section_id=section_id,
            after_id=after_id,
            before_id=before_id,
            batch_id=batch_id,
        )
        return Mutation([t for t, _ in m.entity], batch_id=batch_id)
    out: list[Task] = []
    for tid in ids:
        if action == "update":
            if not patch:
                raise ValidationFailed("Nothing to change")
            out.append((await update_task(session, ctx, tid, patch, batch_id=batch_id)).entity)
        elif action in ("complete", "uncomplete"):
            done = action == "complete"
            out.append((await set_completed(session, ctx, tid, done, batch_id=batch_id)).entity)
        else:
            out.append((await delete_task(session, ctx, tid, batch_id=batch_id)).entity)
    return Mutation(out, batch_id=batch_id)


# ---------- section hooks ----------


@on_section_delete
async def _move_or_delete_section_tasks(
    session: AsyncSession, ctx: Ctx, section: Section, mode: str, target: uuid.UUID | None
) -> dict[str, Any]:
    placements = (
        (
            await session.execute(
                select(TaskProject)
                .join(Task, Task.id == TaskProject.task_id)
                .where(TaskProject.section_id == section.id, Task.deleted_at.is_(None))
                .order_by(TaskProject.position)
            )
        )
        .scalars()
        .all()
    )
    if not placements:
        return {}
    moved: dict[str, str] = {}
    if mode == "delete":
        now = datetime.now(UTC)
        ids = [p.task_id for p in placements]
        for t in (await session.execute(select(Task).where(Task.id.in_(ids)))).scalars():
            t.deleted_at = now
            t.version += 1
        return {"deleted": [str(i) for i in ids]}
    assert target is not None
    moving = {p.task_id for p in placements}
    keys = await _keys_for(session, section.project_id, target, len(placements), exclude=moving)
    for p, key in zip(placements, keys, strict=True):
        moved[str(p.task_id)] = p.position
        p.section_id = target
        p.position = key
    return {"moved": moved, "from": str(section.id)}


@on_section_restore
async def _restore_section_tasks(
    session: AsyncSession, ctx: Ctx, section: Section, info: dict[str, Any]
) -> None:
    for tid, pos in (info.get("moved") or {}).items():
        p = await session.get(TaskProject, (uuid.UUID(tid), section.project_id))
        if p is not None:
            p.section_id = section.id
            p.position = str(pos)
    ids = [uuid.UUID(t) for t in info.get("deleted") or []]
    if ids:
        for t in (await session.execute(select(Task).where(Task.id.in_(ids)))).scalars():
            t.deleted_at = None
            t.version += 1


# ---------- undo handlers ----------


def _tid(args: dict[str, Any]) -> uuid.UUID:
    return uuid.UUID(str(args["task_id"]))


@undo_handler("tasks.update")
async def _undo_update(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    task, _, _ = await get_visible_task(session, ctx, _tid(args))
    if task.version != int(args["version"]):
        raise UndoConflict("This task changed after your edit")
    await update_task(session, ctx, task.id, dict(args["patch"]), record_undo=False)


@undo_handler("tasks.move_back")
async def _undo_move(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    task, placement, role = await get_visible_task(session, ctx, _tid(args))
    require_project_role(role, "editor", "move this task")
    if (
        placement is None
        or str(placement.section_id) != str(args["expect_section_id"])
        or placement.position != args["expect_position"]
    ):
        raise UndoConflict("This task was moved again since")
    section = await session.get(Section, uuid.UUID(str(args["section_id"])))
    if section is None or section.deleted_at is not None:
        raise UndoConflict("The original section no longer exists")
    placement.section_id = section.id
    placement.position = str(args["position"])
    await emit(
        session,
        ctx,
        type="task.moved",
        entity_type="task",
        entity_id=task.id,
        data={"section_id": str(section.id), "position": placement.position},
        channels=channels(task, placement),
    )


@undo_handler("tasks.set_completed")
async def _undo_complete(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    await set_completed(session, ctx, _tid(args), bool(args["completed"]), record_undo=False)


@undo_handler("tasks.restore")
async def _undo_delete(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    task, placement, role = await get_visible_task(session, ctx, _tid(args), include_deleted=True)
    require_project_role(role, "editor", "restore this task")
    task.deleted_at = None
    task.version += 1
    await record_activity(session, ctx, entity_type="task", entity_id=task.id, verb="task.restored")
    await emit(
        session,
        ctx,
        type="task.restored",
        entity_type="task",
        entity_id=task.id,
        channels=channels(task, placement),
    )


@undo_handler("tasks.delete")
async def _undo_create(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    task, placement, role = await get_visible_task(session, ctx, _tid(args))
    require_project_role(role, "editor", "delete this task")
    task.deleted_at = datetime.now(UTC)
    task.version += 1
    await emit(
        session,
        ctx,
        type="task.deleted",
        entity_type="task",
        entity_id=task.id,
        channels=channels(task, placement),
    )
