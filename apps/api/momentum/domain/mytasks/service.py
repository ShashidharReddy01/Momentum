"""My Tasks: everything assigned to me, in personal buckets (phase-1.md S1.5.1).

Placements are kept in sync lazily when the list is read (no background job to go wrong):
new assignments land at the top of "Recently assigned", rows for tasks no longer mine are
dropped, and once per day (in my timezone) unpinned tasks move by due date. Tasks I placed by
hand (pinned) stay where I put them.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import record_activity
from momentum.core.context import Ctx
from momentum.core.errors import NotFound, ValidationFailed
from momentum.core.mutation import Mutation
from momentum.core.ordering import even_keys, key_between, keys_between, needs_rebalance
from momentum.core.undo import UndoConflict, undo_handler, undo_op
from momentum.domain.access import task_ancestors
from momentum.domain.mytasks.models import BUCKETS, MyTaskPlacement
from momentum.domain.projects.models import Project
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.tasks.service import today_for
from momentum.domain.users.models import User

BUCKET_RANK = {b: i for i, b in enumerate(BUCKETS)}
COMPLETED_PAGE = 100


def target_bucket(due: date | None, today: date, current: str) -> str:
    """Where the daily pass puts an unpinned task. Due today or overdue → Today (from any bucket,
    so nothing urgent hides); otherwise tasks already sorted by date follow their due date;
    "Recently assigned" and undated tasks stay put."""
    if due is not None and due <= today:
        return "today"
    if due is not None and current in ("today", "this_week", "later"):
        week_end = today + timedelta(days=6 - today.weekday())
        return "this_week" if due <= week_end else "later"
    return current


async def _visible_mine(session: AsyncSession, ctx: Ctx, *, completed: bool) -> list[Task]:
    """Tasks assigned to me (assignees can always see them) whose ancestors aren't deleted."""
    query = select(Task).where(
        Task.workspace_id == ctx.workspace_id,
        Task.assignee_id == ctx.actor.id,
        Task.deleted_at.is_(None),
    )
    if completed:
        query = (
            query.where(Task.completed_at.is_not(None))
            .order_by(Task.completed_at.desc())
            .limit(COMPLETED_PAGE)
        )
    else:
        query = query.where(Task.completed_at.is_(None))
    tasks = list((await session.execute(query)).scalars())
    roots: dict[uuid.UUID, uuid.UUID] = {}
    for t in tasks:
        if t.parent_id is None:
            roots[t.id] = t.id
            continue
        chain = await task_ancestors(session, t)
        if not any(a.deleted_at is not None for a in chain):
            roots[t.id] = chain[-1].id if chain else t.id
    # tasks that only live in deleted projects are gone for now (back if the project is restored)
    placed = select(TaskProject.task_id).where(TaskProject.task_id.in_(set(roots.values())))
    any_placement = set((await session.execute(placed)).scalars()) if roots else set()
    live = (
        set(
            (
                await session.execute(
                    placed.join(Project, Project.id == TaskProject.project_id).where(
                        Project.deleted_at.is_(None)
                    )
                )
            ).scalars()
        )
        if roots
        else set()
    )
    return [
        t
        for t in tasks
        if t.id in roots and (roots[t.id] in live or roots[t.id] not in any_placement)
    ]


async def _placements(
    session: AsyncSession, user_id: uuid.UUID
) -> dict[uuid.UUID, MyTaskPlacement]:
    rows = await session.execute(select(MyTaskPlacement).where(MyTaskPlacement.user_id == user_id))
    return {p.task_id: p for p in rows.scalars()}


def _ordered(placements: dict[uuid.UUID, MyTaskPlacement], bucket: str) -> list[MyTaskPlacement]:
    return sorted(
        (p for p in placements.values() if p.bucket == bucket),
        key=lambda p: (p.position, str(p.task_id)),
    )


async def sync_my_tasks(session: AsyncSession, ctx: Ctx) -> None:
    assert ctx.actor.id is not None
    me = ctx.actor.id
    open_tasks = await _visible_mine(session, ctx, completed=False)
    open_ids = {t.id for t in open_tasks}
    still_mine = set(
        (
            await session.execute(
                select(Task.id).where(Task.assignee_id == me, Task.deleted_at.is_(None))
            )
        ).scalars()
    )
    placements = await _placements(session, me)
    # No longer mine (or deleted): drop. Completed or temporarily hidden ones (a deleted project
    # or parent, which can be restored) keep their spot.
    stale = [tid for tid in placements if tid not in still_mine]
    if stale:
        await session.execute(
            delete(MyTaskPlacement).where(
                MyTaskPlacement.user_id == me, MyTaskPlacement.task_id.in_(stale)
            )
        )
        for tid in stale:
            placements.pop(tid)
    # new assignments: top of "Recently assigned", newest first
    new = sorted(
        (t for t in open_tasks if t.id not in placements), key=lambda t: t.updated_at, reverse=True
    )
    if new:
        head = _ordered(placements, "recently_assigned")
        keys = keys_between(None, head[0].position if head else None, len(new))
        await session.execute(
            insert(MyTaskPlacement)
            .values(
                [
                    {
                        "user_id": me,
                        "task_id": t.id,
                        "bucket": "recently_assigned",
                        "position": k,
                        "pinned": False,
                    }
                    for t, k in zip(new, keys, strict=True)
                ]
            )
            .on_conflict_do_nothing(index_elements=["user_id", "task_id"])
        )
        placements = await _placements(session, me)
    # once a day (my timezone): move unpinned tasks by due date
    today = today_for(ctx)
    user = await session.get(User, me)
    if user is not None and (user.prefs or {}).get("my_tasks_day") != today.isoformat():
        due = {t.id: t.due_on for t in open_tasks}
        moves: dict[str, list[MyTaskPlacement]] = {b: [] for b in BUCKETS}
        for p in sorted(placements.values(), key=lambda p: (BUCKET_RANK[p.bucket], p.position)):
            if p.pinned or p.task_id not in open_ids:
                continue
            target = target_bucket(due.get(p.task_id), today, p.bucket)
            if target != p.bucket:
                moves[target].append(p)
        for bucket, rows in moves.items():
            if not rows:
                continue
            tail = [p for p in _ordered(placements, bucket) if p not in rows]
            rows.sort(key=lambda p: (due.get(p.task_id) or date.max, p.position))
            for p, key in zip(
                rows,
                keys_between(tail[-1].position if tail else None, None, len(rows)),
                strict=True,
            ):
                p.bucket, p.position = bucket, key
        await session.execute(
            text(
                "UPDATE users SET prefs = jsonb_set(coalesce(prefs, '{}'::jsonb), "
                "'{my_tasks_day}', cast(:day as jsonb)) WHERE id = :uid"
            ),
            {"day": json.dumps(today.isoformat()), "uid": me},
        )
    await session.flush()


async def list_my_tasks(
    session: AsyncSession, ctx: Ctx, *, completed: bool = False
) -> list[tuple[Task, MyTaskPlacement | None]]:
    """Open tasks in bucket order, or my recently completed tasks (newest first)."""
    await sync_my_tasks(session, ctx)
    assert ctx.actor.id is not None
    placements = await _placements(session, ctx.actor.id)
    if completed:
        return [
            (t, placements.get(t.id)) for t in await _visible_mine(session, ctx, completed=True)
        ]
    tasks = await _visible_mine(session, ctx, completed=False)
    rows = [(t, placements.get(t.id)) for t in tasks]
    rows.sort(
        key=lambda r: (
            (BUCKET_RANK[r[1].bucket], r[1].position, str(r[0].id)) if r[1] else (9, "", "")
        )
    )
    return rows


async def move_my_task(
    session: AsyncSession,
    ctx: Ctx,
    task_id: uuid.UUID,
    bucket: str,
    *,
    after_id: uuid.UUID | None = None,
    before_id: uuid.UUID | None = None,
    record_undo: bool = True,
) -> Mutation[MyTaskPlacement]:
    """Put a task in a bucket (pinned: the daily pass leaves it there)."""
    if bucket not in BUCKETS:
        raise ValidationFailed("Unknown bucket", code="invalid_bucket")
    if task_id in (after_id, before_id):
        raise ValidationFailed("A task can't be moved next to itself", code="invalid_anchor")
    await sync_my_tasks(session, ctx)
    assert ctx.actor.id is not None
    placements = await _placements(session, ctx.actor.id)
    placement = placements.get(task_id)
    if placement is None:
        raise NotFound("That task isn't in your My Tasks")
    old = (placement.bucket, placement.position, placement.pinned)
    a: str | None
    b: str | None
    key = placement.position
    for attempt in range(2):
        items = [p for p in _ordered(placements, bucket) if p.task_id != task_id]
        ids = [p.task_id for p in items]
        if after_id is not None:
            if after_id not in ids:
                raise NotFound("Neighbor task not found in that bucket")
            i = ids.index(after_id)
            a, b = items[i].position, items[i + 1].position if i + 1 < len(items) else None
        elif before_id is not None:
            if before_id not in ids:
                raise NotFound("Neighbor task not found in that bucket")
            i = ids.index(before_id)
            a, b = items[i - 1].position if i > 0 else None, items[i].position
        else:
            a, b = (items[-1].position if items else None), None
        key = key_between(a, b)
        if attempt == 1 or not needs_rebalance(key):
            break
        everyone = _ordered(placements, bucket)
        for p, k in zip(everyone, even_keys(len(everyone)), strict=True):
            p.position = k
        await session.flush()
    placement.bucket, placement.position, placement.pinned = bucket, key, True
    act = await record_activity(
        session,
        ctx,
        entity_type="my_task",  # personal: never shown in task feeds
        entity_id=task_id,
        verb="my_task.moved",
        changes={"bucket": (old[0], bucket)},
        undo=undo_op(
            "mytasks.move_back",
            task_id=task_id,
            bucket=old[0],
            position=old[1],
            pinned=old[2],
            expect_bucket=bucket,
            expect_position=key,
        )
        if record_undo
        else None,
    )
    await session.flush()
    return Mutation(placement, act.id)


@undo_handler("mytasks.move_back")
async def _undo_move(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    assert ctx.actor.id is not None
    placement = await session.get(MyTaskPlacement, (ctx.actor.id, uuid.UUID(str(args["task_id"]))))
    if (
        placement is None
        or placement.bucket != args["expect_bucket"]
        or placement.position != args["expect_position"]
    ):
        raise UndoConflict("This task was moved again since")
    placement.bucket = str(args["bucket"])
    placement.position = str(args["position"])
    placement.pinned = bool(args["pinned"])
