"""Compact, model-friendly views of domain objects for tool results.

Keys, titles and names rather than ORM dumps (ai-architecture §3). Built in a handful of
batched queries per call, never one query per row. Placement names are shown only for projects
the actor can see: a task multi-homed into a private project doesn't reveal that project.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import select

from momentum.ai.tools.base import ToolContext
from momentum.core.ids import task_key
from momentum.domain.access import visible_projects_clause
from momentum.domain.projects.models import Project
from momentum.domain.sections.models import Section
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.users.models import User

TEXT_LIMIT = 1500


def iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def clip(text: str | None, limit: int = TEXT_LIMIT) -> str | None:
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


async def user_names(tc: ToolContext, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = [i for i in ids if i is not None]
    if not wanted:
        return {}
    rows = await tc.session.execute(select(User.id, User.name).where(User.id.in_(wanted)))
    return {i: n for i, n in rows.all()}


async def task_briefs(tc: ToolContext, tasks: list[Task]) -> list[dict[str, Any]]:
    if not tasks:
        return []
    s = tc.session
    ids = [t.id for t in tasks]
    # subtasks show their parent; placements belong to top-level tasks
    parents = {t.parent_id for t in tasks if t.parent_id is not None}
    parent_rows = (
        (await s.execute(select(Task).where(Task.id.in_(parents)))).scalars().all()
        if parents
        else []
    )
    parent_of = {p.id: p for p in parent_rows}
    placed = (
        await s.execute(
            select(TaskProject.task_id, Project.name, Section.name)
            .join(Project, Project.id == TaskProject.project_id)
            .join(Section, Section.id == TaskProject.section_id)
            .where(TaskProject.task_id.in_(ids), visible_projects_clause(tc.ctx))
            .order_by(TaskProject.added_at)
        )
    ).all()
    where: dict[uuid.UUID, tuple[str, str]] = {}
    for task_id, pname, sname in placed:
        where.setdefault(task_id, (pname, sname))
    names = await user_names(tc, {t.assignee_id for t in tasks})
    out: list[dict[str, Any]] = []
    for t in tasks:
        b: dict[str, Any] = {
            "id": str(t.id),
            "key": task_key(t.number),
            "title": t.title,
            "status": "done" if t.completed_at is not None else "open",
        }
        if t.type != "task":
            b["type"] = t.type
        if t.assignee_id is not None:
            b["assignee"] = names.get(t.assignee_id, "unknown")
        if t.start_on is not None:
            b["start_on"] = iso(t.start_on)
        if t.due_on is not None:
            b["due_on"] = iso(t.due_on)
        if t.due_at is not None:
            b["due_at"] = iso(t.due_at)
        if t.priority is not None:
            b["priority"] = t.priority
        if t.id in where:
            b["project"], b["section"] = where[t.id]
        parent = parent_of.get(t.parent_id) if t.parent_id else None
        if parent is not None:
            b["parent"] = f"{task_key(parent.number)} {parent.title}"
        out.append(b)
    return out


async def task_brief(tc: ToolContext, task: Task) -> dict[str, Any]:
    return (await task_briefs(tc, [task]))[0]


def target(task: Task) -> dict[str, Any]:
    """An entry of ``ToolResult.targets`` for a task."""
    return {"type": "task", "id": str(task.id), "key": task_key(task.number), "title": task.title}
