"""Project risk signals, computed in code (moved here from Radar in S6.5.3 so the forecast's risk
score and Radar share one definition per signal; Radar calls ``signals()`` unchanged).

- **overdue**: a quarter or more of the open tasks with a due date are overdue (at least 2);
- **blocked**: open tasks waiting on an open blocker that is itself overdue or blocked (a chain);
- **unassigned**: open tasks with nobody assigned, due within 3 days;
- **scope growth**: in the last 7 days, at least 5 tasks added and more than twice as many added
  as completed.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from momentum.core.ids import task_key
from momentum.domain.tasks.models import Task, TaskDependency, TaskProject

OVERDUE_SHARE = 0.25
OVERDUE_MIN = 2
NEAR_DUE_DAYS = 3
GROWTH_WINDOW = timedelta(days=7)
GROWTH_MIN = 5
LISTED = 5  # task keys named per signal


def _keys(tasks: list[Task]) -> list[str]:
    return [f"{task_key(t.number)} {t.title}" for t in tasks[:LISTED]]


async def signals(
    session: AsyncSession, project_id: uuid.UUID, today: date, now: datetime
) -> list[dict[str, Any]]:
    """``[{kind, text, tasks, weight}]`` for one project, all of its tasks (the project's own
    view: whoever sees the project sees these)."""
    open_tasks = list(
        (
            await session.execute(
                select(Task)
                .join(TaskProject, TaskProject.task_id == Task.id)
                .where(
                    TaskProject.project_id == project_id,
                    Task.deleted_at.is_(None),
                    Task.completed_at.is_(None),
                )
                .order_by(Task.due_on.asc().nulls_last(), Task.number)
            )
        ).scalars()
    )
    found: list[dict[str, Any]] = []
    dated = [t for t in open_tasks if t.due_on is not None]
    overdue = [t for t in dated if t.due_on is not None and t.due_on < today]
    if len(overdue) >= OVERDUE_MIN and len(overdue) >= OVERDUE_SHARE * len(dated):
        found.append(
            {
                "kind": "overdue",
                "text": f"{len(overdue)} of {len(dated)} dated open tasks are overdue",
                "tasks": _keys(overdue),
                "weight": 2 if len(overdue) >= 0.5 * len(dated) else 1,
            }
        )
    ids = {t.id for t in open_tasks}
    blocker = aliased(Task)
    edges = (
        await session.execute(
            select(TaskDependency.task_id, blocker)
            .join(blocker, blocker.id == TaskDependency.depends_on_id)
            .where(
                TaskDependency.task_id.in_(ids),
                blocker.deleted_at.is_(None),
                blocker.completed_at.is_(None),
            )
        )
    ).all()
    blocked_ids = {tid for tid, _b in edges}
    chains = [
        tid
        for tid, b in edges
        if b.id in blocked_ids or (b.due_on is not None and b.due_on < today)
    ]
    if chains:
        chained = [t for t in open_tasks if t.id in set(chains)]
        found.append(
            {
                "kind": "blocked",
                "text": f"{len(chained)} task(s) wait on work that is itself overdue or blocked",
                "tasks": _keys(chained),
                "weight": 2 if len(chained) >= 3 else 1,
            }
        )
    near = [
        t
        for t in dated
        if t.assignee_id is None
        and t.due_on is not None
        and today <= t.due_on <= today + timedelta(days=NEAR_DUE_DAYS)
    ]
    if near:
        found.append(
            {
                "kind": "unassigned",
                "text": f"{len(near)} task(s) due within {NEAR_DUE_DAYS} days have no one assigned",
                "tasks": _keys(near),
                "weight": 1,
            }
        )
    since = now - GROWTH_WINDOW
    in_project = select(TaskProject.task_id).where(TaskProject.project_id == project_id)
    added = int(
        await session.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.id.in_(in_project), Task.deleted_at.is_(None), Task.created_at >= since)
        )
        or 0
    )
    done = int(
        await session.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.id.in_(in_project), Task.completed_at >= since)
        )
        or 0
    )
    if added >= GROWTH_MIN and added > 2 * done:
        found.append(
            {
                "kind": "scope",
                "text": f"{added} tasks added this week and {done} completed",
                "tasks": [],
                "weight": 1,
            }
        )
    return found


def level(found: list[dict[str, Any]]) -> str:
    """Radar's level from signal weights alone (used when there's no stored forecast)."""
    score = sum(int(s["weight"]) for s in found)
    return "high" if score >= 4 else "medium" if score >= 2 else "low" if score else "none"
