"""Tasks: create, edit, complete, delete, list (phase-1.md S1.2.2)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from momentum.core.activity import Activity, Diff, jsonable_diff, record_activity
from momentum.core.context import Ctx
from momentum.core.errors import Conflict, NotFound, ValidationFailed, VersionConflict
from momentum.core.events import emit
from momentum.core.mutation import Mutation
from momentum.core.ordering import even_keys, key_between, keys_between, needs_rebalance
from momentum.core.richtext import doc_hash, plain_text, preview, sanitize_doc
from momentum.core.undo import UndoConflict, undo_handler, undo_op
from momentum.domain.access import (
    MAX_TASK_DEPTH,
    get_visible_project,
    get_visible_task,
    project_role,
    require_project_role,
    task_ancestors,
    visible_projects_clause,
)
from momentum.domain.notifications.service import notify
from momentum.domain.projects.models import Project
from momentum.domain.sections.models import Section
from momentum.domain.sections.service import list_sections, on_section_delete, on_section_restore
from momentum.domain.tasks.models import Follower, Task, TaskDependency, TaskProject
from momentum.domain.users.models import User
from momentum.domain.workspace.models import Workspace

COMPLETED_PAGE = 100


def channels(task: Task, placement: TaskProject | None) -> list[str]:
    """Realtime channels for one of this task's own events. Always includes the parent's
    channel too (if it has one), so a subtask's pane list, subtask_count and
    completed_subtask_count badge stay live wherever the parent is open."""
    out = [f"task:{task.id}"]
    if task.parent_id is not None:
        out.append(f"task:{task.parent_id}")
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


PRIORITIES = ("urgent", "high", "medium", "low")
RECURRENCE_FREQS = ("daily", "weekly", "monthly", "yearly")


def _check_priority(value: Any) -> str | None:
    if value is None:
        return None
    if value not in PRIORITIES:
        raise ValidationFailed(
            "Priority must be urgent, high, medium or low", code="invalid_priority"
        )
    return str(value)


def _check_recurrence(value: Any) -> dict[str, Any] | None:
    """A repeat rule as stored in ``tasks.recurrence`` (generation arrives in Phase 4):
    ``{freq, interval, by_weekday?, workdays_only?, text?}``."""
    if value is None:
        return None
    if not isinstance(value, dict) or value.get("freq") not in RECURRENCE_FREQS:
        raise ValidationFailed("Invalid repeat rule", code="invalid_recurrence")
    interval = value.get("interval", 1)
    if not isinstance(interval, int) or not 1 <= interval <= 99:
        raise ValidationFailed("Invalid repeat interval", code="invalid_recurrence")
    out: dict[str, Any] = {"freq": value["freq"], "interval": interval}
    days = value.get("by_weekday")
    if days:
        if not isinstance(days, list) or not all(isinstance(d, int) and 0 <= d <= 6 for d in days):
            raise ValidationFailed("Invalid repeat weekdays", code="invalid_recurrence")
        out["by_weekday"] = sorted(set(days))
    if value.get("workdays_only"):
        out["workdays_only"] = True
    if value.get("text"):
        out["text"] = str(value["text"])[:100]
    return out


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
    """Idempotent, also within one transaction (flushes so a second call sees the first)."""
    if user_id is not None and await session.get(Follower, (task_id, user_id)) is None:
        session.add(Follower(task_id=task_id, user_id=user_id))
        await session.flush()


# ---------- reads ----------


DueFilter = Literal["any", "overdue", "today", "this_week", "next_week", "no_date"]
TaskSort = Literal["manual", "due", "assignee", "created", "title"]


def today_for(ctx: Ctx) -> date:
    try:
        return datetime.now(ZoneInfo(ctx.actor.timezone)).date()
    except (KeyError, ValueError):
        return datetime.now(UTC).date()


def due_clause(due: DueFilter, today: date) -> ColumnElement[bool] | None:
    """SQL condition for a due bucket (weeks start on Monday, in the actor's timezone)."""
    week_end = today + timedelta(days=6 - today.weekday())
    if due == "overdue":
        return Task.due_on < today
    if due == "today":
        return Task.due_on == today
    if due == "this_week":
        return Task.due_on.between(today, week_end)
    if due == "next_week":
        return Task.due_on.between(week_end + timedelta(days=1), week_end + timedelta(days=7))
    if due == "no_date":
        return Task.due_on.is_(None)
    return None


async def list_project_tasks(
    session: AsyncSession,
    ctx: Ctx,
    project_id: uuid.UUID,
    *,
    completed: bool = False,
    before: datetime | None = None,
    assignees: list[str] | None = None,
    due: DueFilter = "any",
    sort: TaskSort = "manual",
) -> list[tuple[Task, TaskProject]]:
    """Top-level tasks of a project. Incomplete tasks: all of them, in section order, then by
    ``sort`` within a section (manual = drag order). Completed tasks: newest first, paged by
    ``before`` (completed_at cursor); ``sort`` does not apply to them.

    ``assignees`` holds user ids, ``"me"`` and/or ``"none"`` (unassigned); several are OR-ed."""
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
    if assignees:
        ids = {ctx.actor.id if a == "me" else _as_uuid(a) for a in assignees if a != "none"}
        conds: list[ColumnElement[bool]] = []
        if ids - {None}:
            conds.append(Task.assignee_id.in_([i for i in ids if i is not None]))
        if "none" in assignees:
            conds.append(Task.assignee_id.is_(None))
        query = query.where(or_(*conds)) if conds else query
    clause = due_clause(due, today_for(ctx))
    if clause is not None:
        query = query.where(clause)
    if completed:
        query = query.where(Task.completed_at.is_not(None))
        if before is not None:
            query = query.where(Task.completed_at < before)
        return [
            (t, p)
            for t, p in (
                await session.execute(
                    query.order_by(Task.completed_at.desc()).limit(COMPLETED_PAGE)
                )
            ).all()
        ]
    query = query.where(Task.completed_at.is_(None))
    keys: list[Any] = [Section.position]
    if sort == "due":
        keys += [Task.due_on.asc().nulls_last(), Task.due_at.asc().nulls_last()]
    elif sort == "assignee":
        query = query.outerjoin(User, User.id == Task.assignee_id)
        keys += [func.lower(User.name).asc().nulls_last()]
    elif sort == "created":
        keys += [Task.created_at]
    elif sort == "title":
        keys += [func.lower(Task.title)]
    keys += [TaskProject.position, Task.id]
    return [(t, p) for t, p in (await session.execute(query.order_by(*keys))).all()]


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
    assignee_id: uuid.UUID | None = None,
    due_on: date | None = None,
    due_at: datetime | None = None,
    priority: str | None = None,
    recurrence: dict[str, Any] | None = None,
) -> Mutation[tuple[Task, TaskProject]]:
    """Create a task (optionally already assigned, dated, prioritized and with a repeat rule:
    quick add is one change, one undo)."""
    _, role = await get_visible_project(session, ctx, project_id)
    require_project_role(role, "editor", "add tasks")
    title = " ".join(title.split())
    if not title:
        raise ValidationFailed("Task name can't be empty")
    if assignee_id is not None:
        await _require_assignable(session, ctx, assignee_id)
    section = await _section_for(session, project_id, section_id)
    (position,) = await _keys_for(
        session, project_id, section.id, 1, after_id=after_id, before_id=before_id
    )
    priority = _check_priority(priority)
    recurrence = _check_recurrence(recurrence)
    task = Task(
        workspace_id=ctx.workspace_id,
        number=await _next_number(session, ctx.workspace_id),
        title=title,
        assignee_id=assignee_id,
        priority=priority,
        recurrence=recurrence,
        created_by=ctx.actor.id,
        created_via=ctx.via,
    )
    created: Diff = {"title": (None, title)}
    if assignee_id is not None:
        created["assignee_id"] = (None, assignee_id)
    if priority is not None:
        created["priority"] = (None, priority)
    if recurrence is not None:
        created["recurrence"] = (None, recurrence)
    dates = {k: v for k, v in (("due_on", due_on), ("due_at", due_at)) if v is not None}
    _apply_dates(task, dates, ctx, created)  # same rules as editing (due_at → local due_on)
    for field in ("due_on", "due_at"):
        if field in created:
            setattr(task, field, created[field][1])
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
    await _follow(session, task.id, assignee_id)
    act = await record_activity(
        session,
        ctx,
        entity_type="task",
        entity_id=task.id,
        verb="task.created",
        changes=created,
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
    if assignee_id is not None:
        await emit(
            session,
            ctx,
            type="task.assigned",
            entity_type="task",
            entity_id=task.id,
            data={"assignee_id": str(assignee_id), "previous_assignee_id": None},
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
        raise VersionConflict("This task was changed by someone else", version=task.version)
    changes: Diff = {}
    if "description" in patch:
        # Conflict only when the description itself changed since the client loaded it
        # (other fields changing in between must not block a save).
        base = patch.get("description_base")
        if base is not None and base != doc_hash(task.description):
            raise VersionConflict(
                "The description was changed by someone else", version=task.version
            )
        doc = sanitize_doc(patch["description"])
        if doc != task.description:
            changes["description"] = (task.description, doc)
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
    if "priority" in patch:
        priority = _check_priority(patch["priority"])
        if priority != task.priority:
            changes["priority"] = (task.priority, priority)
    if "recurrence" in patch:
        recurrence = _check_recurrence(patch["recurrence"])
        if recurrence != task.recurrence:
            changes["recurrence"] = (task.recurrence, recurrence)
    _apply_dates(task, patch, ctx, changes)
    if not changes:
        return Mutation(task, version=task.version)
    previous_assignee = task.assignee_id
    for field, (_, new) in changes.items():
        setattr(task, field, new)
    if "description" in changes:
        task.description_text = plain_text(task.description) or None
    task.version += 1
    # Activity/event payloads carry a text preview of descriptions, not whole documents.
    shown: Diff = {
        k: ((preview(o), preview(n)) if k == "description" else (o, n))
        for k, (o, n) in changes.items()
    }
    act = None
    if record_undo and batch_id is None and set(changes) == {"description"}:
        act = await _coalesce_description_edit(session, ctx, task, shown)
    if act is None:
        act = await record_activity(
            session,
            ctx,
            entity_type="task",
            entity_id=task.id,
            verb="task.updated",
            changes=shown,
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
            "changes": jsonable_diff(shown),
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
        await notify(
            session,
            ctx,
            user_id=task.assignee_id,
            kind="assigned",
            entity_type="task",
            entity_id=task.id,
            title=f'You were assigned "{task.title}"',
            activity_id=act.id,
        )
    return Mutation(task, act.id, batch_id=batch_id, version=task.version)


COALESCE_WINDOW = timedelta(minutes=10)


async def _coalesce_description_edit(
    session: AsyncSession, ctx: Ctx, task: Task, shown: Diff
) -> Activity | None:
    """Autosave writes the description every second or so while someone types. Fold those saves
    into the actor's previous description edit (if it's the task's latest activity and recent),
    so the feed shows one change and undo returns to the text from before the editing session."""
    last = (
        await session.execute(
            select(Activity)
            .where(Activity.entity_type == "task", Activity.entity_id == task.id)
            .order_by(Activity.created_at.desc(), Activity.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if (
        last is None
        or last.actor_id != ctx.actor.id
        or last.verb != "task.updated"
        or set(last.diff) != {"description"}
        or last.undone_at is not None
        or last.batch_id is not None
        or last.undo_payload is None
        or datetime.now(UTC) - last.created_at > COALESCE_WINDOW
    ):
        return None
    first_old = last.diff["description"][0]
    last.diff = jsonable_diff({"description": (first_old, shown["description"][1])})
    args = dict(last.undo_payload.get("args") or {})
    args["version"] = task.version
    last.undo_payload = {**last.undo_payload, "args": args}
    return last


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


CONVERTIBLE_TYPES = ("task", "milestone")


async def convert_task_type(
    session: AsyncSession, ctx: Ctx, task_id: uuid.UUID, new_type: str, *, record_undo: bool = True
) -> Mutation[Task]:
    """Convert a task to a milestone or back (S2.4.3). `approval` is a valid `type` at the schema
    level (data-model.md) but isn't offered by this conversion — it has no UI or behavior of its
    own yet, so exposing it here would just be a state nothing else understands."""
    if new_type not in CONVERTIBLE_TYPES:
        raise ValidationFailed(f"Can't convert to '{new_type}'")
    task, placement, role = await get_visible_task(session, ctx, task_id)
    require_project_role(role, "editor", "convert this task")
    if task.type == new_type:
        return Mutation(task, version=task.version)
    old_type = task.type
    task.type = new_type
    task.version += 1
    act = await record_activity(
        session,
        ctx,
        entity_type="task",
        entity_id=task.id,
        verb="task.type_changed",
        changes={"type": (old_type, new_type)},
        undo=undo_op("tasks.convert_type", task_id=task.id, new_type=old_type)
        if record_undo
        else None,
    )
    await emit(
        session,
        ctx,
        type="task.type_changed",
        entity_type="task",
        entity_id=task.id,
        data={"type": new_type},
        channels=channels(task, placement),
        activity_id=act.id,
    )
    return Mutation(task, act.id, version=task.version)


async def set_completed(
    session: AsyncSession,
    ctx: Ctx,
    task_id: uuid.UUID,
    completed: bool,
    *,
    record_undo: bool = True,
    batch_id: uuid.UUID | None = None,
    force: bool = False,
) -> Mutation[Task]:
    task, placement, role = await get_visible_task(session, ctx, task_id)
    require_project_role(role, "editor", "complete this task")
    if (task.completed_at is not None) == completed:
        return Mutation(task, version=task.version)
    if completed and not force and await _has_incomplete_blockers(session, task_id):
        raise Conflict("This task has incomplete blockers", code="has_incomplete_blockers")
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
    if completed:
        await notify(
            session,
            ctx,
            user_id=task.created_by,
            kind="completed",
            entity_type="task",
            entity_id=task.id,
            title=f'"{task.title}" was completed',
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
            # Bulk complete skips the confirm-if-blocked prompt — a per-task confirmation dialog
            # doesn't make sense across a multi-select; the "waiting on" icon already tells you
            # before you pick "Complete" from the bulk bar.
            out.append(
                (await set_completed(session, ctx, tid, done, batch_id=batch_id, force=True)).entity
            )
        else:
            out.append((await delete_task(session, ctx, tid, batch_id=batch_id)).entity)
    return Mutation(out, batch_id=batch_id)


# ---------- subtasks ----------


async def _children(
    session: AsyncSession, parent_id: uuid.UUID, *, include_deleted: bool = False
) -> list[Task]:
    query = select(Task).where(Task.parent_id == parent_id)
    if not include_deleted:
        query = query.where(Task.deleted_at.is_(None))
    rows = await session.execute(query.order_by(Task.parent_position, Task.id))
    return list(rows.scalars())


async def _child_keys(
    session: AsyncSession,
    parent_id: uuid.UUID,
    n: int,
    *,
    after_id: uuid.UUID | None = None,
    before_id: uuid.UUID | None = None,
    exclude: set[uuid.UUID] | None = None,
) -> list[str]:
    """Order keys among a task's subtasks (same rules as sections; rebalances if keys get long)."""
    skip = exclude or set()
    for attempt in range(2):
        items = [t for t in await _children(session, parent_id) if t.id not in skip]
        ids = [t.id for t in items]
        a: str | None
        b: str | None
        if after_id is not None:
            if after_id not in ids:
                raise NotFound("Neighbor subtask not found")
            i = ids.index(after_id)
            a, b = (
                items[i].parent_position,
                items[i + 1].parent_position if i + 1 < len(items) else None,
            )
        elif before_id is not None:
            if before_id not in ids:
                raise NotFound("Neighbor subtask not found")
            i = ids.index(before_id)
            a, b = items[i - 1].parent_position if i > 0 else None, items[i].parent_position
        else:
            a, b = (items[-1].parent_position if items else None), None
        keys = [key_between(a, b)] if n == 1 else keys_between(a, b, n)
        if attempt == 1 or not any(needs_rebalance(k) for k in keys):
            return keys
        everyone = await _children(session, parent_id, include_deleted=True)
        for child, key in zip(everyone, even_keys(len(everyone)), strict=True):
            child.parent_position = key
        await session.flush()
    raise AssertionError("unreachable")


async def subtask_counts(
    session: AsyncSession, task_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int]]:
    """(total, completed) visible subtasks per task, in one query."""
    if not task_ids:
        return {}
    rows = await session.execute(
        select(Task.parent_id, func.count(), func.count(Task.completed_at))
        .where(Task.parent_id.in_(task_ids), Task.deleted_at.is_(None))
        .group_by(Task.parent_id)
    )
    return {pid: (int(total), int(done)) for pid, total, done in rows.all() if pid is not None}


async def list_subtasks(session: AsyncSession, ctx: Ctx, parent_id: uuid.UUID) -> list[Task]:
    await get_visible_task(session, ctx, parent_id)
    return await _children(session, parent_id)


async def create_subtask(
    session: AsyncSession,
    ctx: Ctx,
    parent_id: uuid.UUID,
    title: str,
    *,
    after_id: uuid.UUID | None = None,
    before_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
) -> Mutation[Task]:
    parent, placement, role = await get_visible_task(session, ctx, parent_id)
    require_project_role(role, "editor", "add subtasks")
    if len(await task_ancestors(session, parent)) + 1 >= MAX_TASK_DEPTH:
        raise ValidationFailed(
            f"Subtasks can be nested {MAX_TASK_DEPTH} levels deep", code="too_deep"
        )
    title = " ".join(title.split())
    if not title:
        raise ValidationFailed("Task name can't be empty")
    (position,) = await _child_keys(session, parent.id, 1, after_id=after_id, before_id=before_id)
    task = Task(
        workspace_id=ctx.workspace_id,
        number=await _next_number(session, ctx.workspace_id),
        title=title,
        parent_id=parent.id,
        parent_position=position,
        created_by=ctx.actor.id,
        created_via=ctx.via,
    )
    session.add(task)
    await session.flush()
    await _follow(session, task.id, ctx.actor.id)
    act = await record_activity(
        session,
        ctx,
        entity_type="task",
        entity_id=task.id,
        verb="task.created",
        changes={"title": (None, title), "parent_id": (None, parent.id)},
        undo=undo_op("tasks.delete", task_id=task.id),
        batch_id=batch_id,
    )
    await emit(
        session,
        ctx,
        type="task.created",
        entity_type="task",
        entity_id=task.id,
        data={"parent_id": str(parent.id), "position": position},
        channels=channels(task, placement),
        activity_id=act.id,
    )
    await session.flush()
    return Mutation(task, act.id, batch_id=batch_id, version=task.version)


async def move_subtask(
    session: AsyncSession,
    ctx: Ctx,
    task_id: uuid.UUID,
    *,
    after_id: uuid.UUID | None = None,
    before_id: uuid.UUID | None = None,
) -> Mutation[Task]:
    """Reorder a subtask among its siblings."""
    task, placement, role = await get_visible_task(session, ctx, task_id)
    require_project_role(role, "editor", "move this subtask")
    if task.parent_id is None:
        raise ValidationFailed("Not a subtask", code="not_a_subtask")
    if task_id in (after_id, before_id):
        raise ValidationFailed("A task can't be moved next to itself", code="invalid_anchor")
    old = task.parent_position
    (key,) = await _child_keys(
        session, task.parent_id, 1, after_id=after_id, before_id=before_id, exclude={task.id}
    )
    task.parent_position = key
    act = await record_activity(
        session,
        ctx,
        entity_type="task",
        entity_id=task.id,
        verb="task.moved",
        changes={"parent_position": (old, key)},
        undo=undo_op(
            "tasks.parent_back",
            task_id=task.id,
            parent_id=task.parent_id,
            parent_position=old,
            expect_parent_id=task.parent_id,
            expect_position=key,
            placement=None,
        ),
    )
    await emit(
        session,
        ctx,
        type="task.moved",
        entity_type="task",
        entity_id=task.id,
        data={"parent_id": str(task.parent_id), "position": key},
        channels=channels(task, placement),
        activity_id=act.id,
    )
    return Mutation(task, act.id, version=task.version)


async def outdent_subtask(
    session: AsyncSession, ctx: Ctx, task_id: uuid.UUID
) -> Mutation[tuple[Task, TaskProject | None]]:
    """Move a subtask up one level: under its grandparent, or (for a direct subtask of a
    top-level task) into the parent's section as a top-level task right after the parent."""
    task, placement, role = await get_visible_task(session, ctx, task_id)
    require_project_role(role, "editor", "move this subtask")
    if task.parent_id is None:
        raise ValidationFailed("Not a subtask", code="not_a_subtask")
    parent = await session.get(Task, task.parent_id)
    assert parent is not None
    old_parent, old_position = task.parent_id, task.parent_position
    new_placement: TaskProject | None = None
    if parent.parent_id is not None:
        (key,) = await _child_keys(session, parent.parent_id, 1, after_id=parent.id)
        task.parent_id, task.parent_position = parent.parent_id, key
        expect: dict[str, Any] = {"expect_parent_id": parent.parent_id, "expect_position": key}
    else:
        parent_pl = (
            await session.execute(select(TaskProject).where(TaskProject.task_id == parent.id))
        ).scalar_one_or_none()
        if parent_pl is None:
            raise ValidationFailed("The parent task isn't in a project", code="not_movable")
        (key,) = await _keys_for(
            session, parent_pl.project_id, parent_pl.section_id, 1, after_id=parent.id
        )
        task.parent_id, task.parent_position = None, None
        new_placement = TaskProject(
            task_id=task.id,
            project_id=parent_pl.project_id,
            section_id=parent_pl.section_id,
            position=key,
            added_by=ctx.actor.id,
        )
        session.add(new_placement)
        expect = {"expect_parent_id": None, "expect_position": key}
    task.version += 1
    act = await record_activity(
        session,
        ctx,
        entity_type="task",
        entity_id=task.id,
        verb="task.moved",
        changes={"parent_id": (old_parent, task.parent_id)},
        undo=undo_op(
            "tasks.parent_back",
            task_id=task.id,
            parent_id=old_parent,
            parent_position=old_position,
            placement=str(new_placement.project_id) if new_placement else None,
            **expect,
        ),
    )
    await emit(
        session,
        ctx,
        type="task.moved",
        entity_type="task",
        entity_id=task.id,
        data={"parent_id": str(task.parent_id) if task.parent_id else None},
        channels=[*channels(task, new_placement or placement), f"task:{old_parent}"],
        activity_id=act.id,
    )
    await session.flush()
    return Mutation((task, new_placement or placement), act.id, version=task.version)


# ---------- followers ----------


async def list_followers(session: AsyncSession, task_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await session.execute(
        select(Follower.user_id)
        .where(Follower.task_id == task_id)
        .order_by(Follower.created_at, Follower.user_id)
    )
    return list(rows.scalars())


async def set_following(
    session: AsyncSession,
    ctx: Ctx,
    task_id: uuid.UUID,
    user_id: uuid.UUID,
    follow: bool,
    *,
    record_undo: bool = True,
) -> Mutation[list[uuid.UUID]]:
    """Add or remove a follower. Anyone with comment access may follow or leave a task
    themselves; adding or removing someone else needs edit access. A follower can see and comment
    on the task even outside its project (auth-and-permissions.md §6)."""
    task, placement, role = await get_visible_task(session, ctx, task_id)
    if user_id == ctx.actor.id:
        require_project_role(role, "commenter", "follow this task")
    else:
        require_project_role(role, "editor", "change who follows this task")
        if follow:
            await _require_assignable(session, ctx, user_id)
    existing = await session.get(Follower, (task.id, user_id))
    if (existing is not None) == follow:
        return Mutation(await list_followers(session, task.id))
    if follow:
        session.add(Follower(task_id=task.id, user_id=user_id))
    else:
        await session.delete(existing)
    await session.flush()
    verb = "task.follower_added" if follow else "task.follower_removed"
    act = await record_activity(
        session,
        ctx,
        entity_type="task",
        entity_id=task.id,
        verb=verb,
        changes={"follower": (None, user_id) if follow else (user_id, None)},
        undo=undo_op("tasks.follow", task_id=task.id, user_id=user_id, follow=not follow)
        if record_undo
        else None,
    )
    await emit(
        session,
        ctx,
        type=verb,
        entity_type="task",
        entity_id=task.id,
        data={"user_id": str(user_id)},
        channels=[*channels(task, placement), f"user:{user_id}"],
        activity_id=act.id,
    )
    return Mutation(await list_followers(session, task.id), act.id)


# ---------- multi-homing (S2.4.1) ----------


async def list_task_projects(
    session: AsyncSession, ctx: Ctx, task_id: uuid.UUID
) -> list[tuple[TaskProject, Project, Section]]:
    """Every project this task's top-level ancestor is placed in that the caller can see —
    filtered the same way `list_other_placements` filters list-row chips, so a private
    co-placement is never revealed to someone who isn't a member of it (S2.4.1 AC)."""
    task, _, _ = await get_visible_task(session, ctx, task_id)
    ancestors = await task_ancestors(session, task)
    root = ancestors[-1] if ancestors else task
    rows = await session.execute(
        select(TaskProject, Project, Section)
        .join(Project, Project.id == TaskProject.project_id)
        .join(Section, Section.id == TaskProject.section_id)
        .where(TaskProject.task_id == root.id)
        .order_by(Project.name)
    )
    out = []
    for tp, project, section in rows.all():
        if await project_role(session, ctx, project) is not None:
            out.append((tp, project, section))
    return out


async def list_other_placements(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID
) -> list[tuple[uuid.UUID, Project]]:
    """For a project's own task list: every *other* project each of its tasks is also placed in,
    filtered to projects the caller can see — mirrors the fields/tags bulk-endpoint pattern (one
    round trip for the whole list, not one per row) and never leaks a private co-placement to a
    viewer who isn't a member of it."""
    await get_visible_project(session, ctx, project_id)
    in_this_project = select(TaskProject.task_id).where(TaskProject.project_id == project_id)
    rows = await session.execute(
        select(TaskProject.task_id, Project)
        .join(Project, Project.id == TaskProject.project_id)
        .where(
            TaskProject.project_id != project_id,
            TaskProject.task_id.in_(in_this_project),
            visible_projects_clause(ctx),
        )
    )
    return [(task_id, project) for task_id, project in rows.all()]


async def add_task_to_project(
    session: AsyncSession,
    ctx: Ctx,
    task_id: uuid.UUID,
    project_id: uuid.UUID,
    *,
    section_id: uuid.UUID | None = None,
    after_id: uuid.UUID | None = None,
    before_id: uuid.UUID | None = None,
    record_undo: bool = True,
) -> Mutation[tuple[TaskProject, Project, Section]]:
    """Place a task in another project too, independent of its other placements' section/order."""
    task, _, _ = await get_visible_task(session, ctx, task_id)
    if task.parent_id is not None:
        raise ValidationFailed("Subtasks can't be placed in a project directly")
    _, role = await get_visible_project(session, ctx, project_id)
    require_project_role(role, "editor", "add tasks to this project")
    if await session.get(TaskProject, (task_id, project_id)) is not None:
        raise Conflict("This task is already in that project", code="already_placed")
    section = await _section_for(session, project_id, section_id)
    (position,) = await _keys_for(
        session, project_id, section.id, 1, after_id=after_id, before_id=before_id
    )
    placement = TaskProject(
        task_id=task_id,
        project_id=project_id,
        section_id=section.id,
        position=position,
        added_by=ctx.actor.id,
    )
    session.add(placement)
    await session.flush()
    project = await session.get(Project, project_id)
    assert project is not None
    act = await record_activity(
        session,
        ctx,
        entity_type="task",
        entity_id=task_id,
        verb="task.added_to_project",
        changes={"project_id": (None, project_id)},
        undo=undo_op("tasks.remove_from_project", task_id=task_id, project_id=project_id)
        if record_undo
        else None,
    )
    await emit(
        session,
        ctx,
        type="task.added_to_project",
        entity_type="task",
        entity_id=task_id,
        data={"project_id": str(project_id), "section_id": str(section.id), "position": position},
        channels=[*channels(task, None), f"project:{project_id}"],
        activity_id=act.id,
    )
    return Mutation((placement, project, section), act.id)


async def remove_task_from_project(
    session: AsyncSession,
    ctx: Ctx,
    task_id: uuid.UUID,
    project_id: uuid.UUID,
    *,
    record_undo: bool = True,
) -> Mutation[None]:
    """Remove a task from one project, keeping it (and its other placements) untouched. A task
    must stay in at least one project — this isn't the same operation as deleting it."""
    task, _, _ = await get_visible_task(session, ctx, task_id)
    _, role = await get_visible_project(session, ctx, project_id)
    require_project_role(role, "editor", "remove tasks from this project")
    placement = await session.get(TaskProject, (task_id, project_id))
    if placement is None:
        raise NotFound("This task isn't in that project")
    count = (
        await session.execute(
            select(func.count()).select_from(TaskProject).where(TaskProject.task_id == task_id)
        )
    ).scalar_one()
    if count <= 1:
        raise ValidationFailed("A task must stay in at least one project", code="last_placement")
    section_id, position = placement.section_id, placement.position
    await session.delete(placement)
    await session.flush()
    act = await record_activity(
        session,
        ctx,
        entity_type="task",
        entity_id=task_id,
        verb="task.removed_from_project",
        changes={"project_id": (project_id, None)},
        undo=undo_op(
            "tasks.add_to_project",
            task_id=task_id,
            project_id=project_id,
            section_id=section_id,
            position=position,
        )
        if record_undo
        else None,
    )
    await emit(
        session,
        ctx,
        type="task.removed_from_project",
        entity_type="task",
        entity_id=task_id,
        data={"project_id": str(project_id)},
        channels=[*channels(task, None), f"project:{project_id}"],
        activity_id=act.id,
    )
    return Mutation(None, act.id)


# ---------- dependencies (S2.4.2) ----------


async def _has_incomplete_blockers(session: AsyncSession, task_id: uuid.UUID) -> bool:
    rows = await session.execute(
        select(TaskDependency.depends_on_id)
        .join(Task, Task.id == TaskDependency.depends_on_id)
        .where(
            TaskDependency.task_id == task_id,
            Task.completed_at.is_(None),
            Task.deleted_at.is_(None),
        )
        .limit(1)
    )
    return rows.first() is not None


async def _would_cycle(session: AsyncSession, task_id: uuid.UUID, depends_on_id: uuid.UUID) -> bool:
    """True if making `task_id` depend on `depends_on_id` would create a cycle — i.e.
    `depends_on_id` already (transitively) depends on `task_id`. A recursive CTE walks the
    existing chain of blockers starting at `depends_on_id`."""
    if task_id == depends_on_id:
        return True
    base = select(TaskDependency.depends_on_id).where(TaskDependency.task_id == depends_on_id)
    chain = base.cte(name="dep_chain", recursive=True)
    chain = chain.union_all(
        select(TaskDependency.depends_on_id).join(
            chain, TaskDependency.task_id == chain.c.depends_on_id
        )
    )
    rows = await session.execute(
        select(chain.c.depends_on_id).where(chain.c.depends_on_id == task_id).limit(1)
    )
    return rows.first() is not None


async def list_dependencies(
    session: AsyncSession, ctx: Ctx, task_id: uuid.UUID
) -> tuple[list[Task], list[Task]]:
    """(blocked_by, blocking): tasks this one depends on, and tasks that depend on this one, each
    filtered to what the caller can currently see. Dependency lists are small in practice, so this
    checks visibility per related task rather than building a bulk-visibility SQL clause."""
    await get_visible_task(session, ctx, task_id)
    blocked_by_ids = (
        (
            await session.execute(
                select(TaskDependency.depends_on_id).where(TaskDependency.task_id == task_id)
            )
        )
        .scalars()
        .all()
    )
    blocking_ids = (
        (
            await session.execute(
                select(TaskDependency.task_id).where(TaskDependency.depends_on_id == task_id)
            )
        )
        .scalars()
        .all()
    )

    async def _visible(ids: Sequence[uuid.UUID]) -> list[Task]:
        out = []
        for tid in ids:
            try:
                t, _, _ = await get_visible_task(session, ctx, tid)
                out.append(t)
            except NotFound:
                continue
        return out

    return await _visible(blocked_by_ids), await _visible(blocking_ids)


async def add_dependency(
    session: AsyncSession,
    ctx: Ctx,
    task_id: uuid.UUID,
    depends_on_id: uuid.UUID,
    *,
    record_undo: bool = True,
) -> Mutation[Task]:
    """Block `task_id` on `depends_on_id` completing first."""
    if task_id == depends_on_id:
        raise ValidationFailed("A task can't depend on itself")
    task, placement, role = await get_visible_task(session, ctx, task_id)
    require_project_role(role, "editor", "add a dependency")
    blocker, _, _ = await get_visible_task(session, ctx, depends_on_id)
    if await session.get(TaskDependency, (task_id, depends_on_id)) is not None:
        raise Conflict("This dependency already exists", code="already_exists")
    if await _would_cycle(session, task_id, depends_on_id):
        raise ValidationFailed("That would create a dependency cycle", code="cycle")
    session.add(
        TaskDependency(task_id=task_id, depends_on_id=depends_on_id, created_by=ctx.actor.id)
    )
    await session.flush()
    act = await record_activity(
        session,
        ctx,
        entity_type="task",
        entity_id=task_id,
        verb="task.dependency_added",
        changes={"depends_on_id": (None, depends_on_id)},
        undo=undo_op("tasks.remove_dependency", task_id=task_id, depends_on_id=depends_on_id)
        if record_undo
        else None,
    )
    await emit(
        session,
        ctx,
        type="task.dependency_added",
        entity_type="task",
        entity_id=task_id,
        data={"depends_on_id": str(depends_on_id)},
        channels=[*channels(task, placement), f"task:{depends_on_id}"],
        activity_id=act.id,
    )
    return Mutation(blocker, act.id)


async def remove_dependency(
    session: AsyncSession,
    ctx: Ctx,
    task_id: uuid.UUID,
    depends_on_id: uuid.UUID,
    *,
    record_undo: bool = True,
) -> Mutation[None]:
    task, placement, role = await get_visible_task(session, ctx, task_id)
    require_project_role(role, "editor", "remove a dependency")
    link = await session.get(TaskDependency, (task_id, depends_on_id))
    if link is None:
        raise NotFound("This dependency doesn't exist")
    await session.delete(link)
    await session.flush()
    act = await record_activity(
        session,
        ctx,
        entity_type="task",
        entity_id=task_id,
        verb="task.dependency_removed",
        changes={"depends_on_id": (depends_on_id, None)},
        undo=undo_op("tasks.add_dependency", task_id=task_id, depends_on_id=depends_on_id)
        if record_undo
        else None,
    )
    await emit(
        session,
        ctx,
        type="task.dependency_removed",
        entity_type="task",
        entity_id=task_id,
        data={"depends_on_id": str(depends_on_id)},
        channels=[*channels(task, placement), f"task:{depends_on_id}"],
        activity_id=act.id,
    )
    return Mutation(None, act.id)


async def search_project_tasks(
    session: AsyncSession,
    ctx: Ctx,
    project_id: uuid.UUID,
    q: str,
    *,
    exclude: uuid.UUID | None = None,
    limit: int = 20,
) -> list[Task]:
    """A minimal task finder for the "add a blocker" picker, scoped to one project (global search
    across projects is S2.6, not built yet — this is intentionally small)."""
    await get_visible_project(session, ctx, project_id)
    query = (
        select(Task)
        .join(TaskProject, TaskProject.task_id == Task.id)
        .where(
            TaskProject.project_id == project_id,
            Task.deleted_at.is_(None),
            Task.parent_id.is_(None),
        )
    )
    clean = q.strip()
    if clean:
        query = query.where(Task.title.ilike(f"%{clean}%"))
    if exclude is not None:
        query = query.where(Task.id != exclude)
    rows = await session.execute(
        query.order_by(Task.completed_at.is_not(None), Task.title).limit(limit)
    )
    return list(rows.scalars())


async def list_blocked_tasks(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID
) -> list[uuid.UUID]:
    """Task ids in this project with at least one incomplete blocker — for the list row's
    "waiting on" icon. One query for the whole list, not one per row."""
    await get_visible_project(session, ctx, project_id)
    Blocker = aliased(Task)
    rows = await session.execute(
        select(TaskDependency.task_id)
        .join(TaskProject, TaskProject.task_id == TaskDependency.task_id)
        .join(Blocker, Blocker.id == TaskDependency.depends_on_id)
        .where(
            TaskProject.project_id == project_id,
            Blocker.completed_at.is_(None),
            Blocker.deleted_at.is_(None),
        )
        .distinct()
    )
    return list(rows.scalars())


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


@undo_handler("tasks.parent_back")
async def _undo_parent_change(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    """Undo a subtask reorder or outdent (only if it hasn't moved again since)."""
    task, _, role = await get_visible_task(session, ctx, _tid(args))
    require_project_role(role, "editor", "move this subtask")
    expect_parent = _as_uuid(args.get("expect_parent_id"))
    if expect_parent is not None:
        current_pos = task.parent_position
    else:
        own = (
            await session.execute(select(TaskProject).where(TaskProject.task_id == task.id))
        ).scalar_one_or_none()
        current_pos = own.position if own else None
    if task.parent_id != expect_parent or current_pos != args.get("expect_position"):
        raise UndoConflict("This task was moved again since")
    parent = await session.get(Task, _as_uuid(args["parent_id"]))
    if parent is None or parent.deleted_at is not None:
        raise UndoConflict("The original parent task no longer exists")
    if args.get("placement"):
        await session.execute(delete(TaskProject).where(TaskProject.task_id == task.id))
        task.version += 1
    task.parent_id = parent.id
    task.parent_position = str(args["parent_position"])
    await emit(
        session,
        ctx,
        type="task.moved",
        entity_type="task",
        entity_id=task.id,
        data={"parent_id": str(parent.id), "position": task.parent_position},
        channels=[f"task:{task.id}", f"task:{parent.id}"],
    )


@undo_handler("tasks.follow")
async def _undo_follow(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    await set_following(
        session,
        ctx,
        _tid(args),
        uuid.UUID(str(args["user_id"])),
        bool(args["follow"]),
        record_undo=False,
    )


@undo_handler("tasks.remove_from_project")
async def _undo_add_to_project(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    await remove_task_from_project(
        session, ctx, _tid(args), uuid.UUID(str(args["project_id"])), record_undo=False
    )


@undo_handler("tasks.add_to_project")
async def _undo_remove_from_project(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    task_id = _tid(args)
    project_id = uuid.UUID(str(args["project_id"]))
    task, _, _ = await get_visible_task(session, ctx, task_id)
    _, role = await get_visible_project(session, ctx, project_id)
    require_project_role(role, "editor", "add tasks to this project")
    if await session.get(TaskProject, (task_id, project_id)) is not None:
        raise UndoConflict("This task is already back in that project")
    section_id = uuid.UUID(str(args["section_id"]))
    section = await session.get(Section, section_id)
    if section is None or section.deleted_at is not None or section.project_id != project_id:
        raise UndoConflict("The original section no longer exists")
    placement = TaskProject(
        task_id=task_id,
        project_id=project_id,
        section_id=section_id,
        position=str(args["position"]),
        added_by=ctx.actor.id,
    )
    session.add(placement)
    await session.flush()
    await emit(
        session,
        ctx,
        type="task.added_to_project",
        entity_type="task",
        entity_id=task_id,
        data={
            "project_id": str(project_id),
            "section_id": str(section_id),
            "position": placement.position,
        },
        channels=[*channels(task, None), f"project:{project_id}"],
    )


@undo_handler("tasks.remove_dependency")
async def _undo_add_dependency(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    await remove_dependency(
        session, ctx, _tid(args), uuid.UUID(str(args["depends_on_id"])), record_undo=False
    )


@undo_handler("tasks.add_dependency")
async def _undo_remove_dependency(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    await add_dependency(
        session, ctx, _tid(args), uuid.UUID(str(args["depends_on_id"])), record_undo=False
    )


@undo_handler("tasks.convert_type")
async def _undo_convert_type(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    await convert_task_type(session, ctx, _tid(args), str(args["new_type"]), record_undo=False)


@undo_handler("tasks.set_completed")
async def _undo_complete(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    await set_completed(
        session, ctx, _tid(args), bool(args["completed"]), record_undo=False, force=True
    )


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
