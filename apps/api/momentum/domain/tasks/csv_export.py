"""E7.4 parity (P1): export a project's tasks to CSV, as in Asana's "Export → CSV".

One row per task and subtask the caller can see in the project, completed ones included, in
section and list order (each subtask after its parent). Columns follow Asana's export so a sheet
built on one keeps working: Task ID, Created At, Completed At, Name, Section/Column, Assignee,
Assignee Email, Start Date, Due Date, Tags, Notes, Parent task, then Priority, Estimate (minutes)
and one column per custom field. The file reimports through the CSV importer (S2.7.2).
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.core.richtext import plain_text
from momentum.domain.access import get_visible_project
from momentum.domain.fields.models import FieldDef, FieldValue, ProjectField
from momentum.domain.projects.models import Project
from momentum.domain.sections.models import Section
from momentum.domain.tags.models import Tag, TaskTag
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.users.models import User

HEADERS = [
    "Task ID",
    "Created At",
    "Completed At",
    "Name",
    "Section/Column",
    "Assignee",
    "Assignee Email",
    "Start Date",
    "Due Date",
    "Tags",
    "Notes",
    "Parent task",
    "Priority",
    "Estimate (minutes)",
]


async def export_project_csv(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID
) -> tuple[Project, str]:
    project, _role = await get_visible_project(session, ctx, project_id)
    sections = list(
        (
            await session.execute(
                select(Section)
                .where(Section.project_id == project.id, Section.deleted_at.is_(None))
                .order_by(Section.position)
            )
        ).scalars()
    )
    order = {s.id: i for i, s in enumerate(sections)}
    names = {s.id: s.name for s in sections}
    top = [
        (t, p)
        for t, p in (
            await session.execute(
                select(Task, TaskProject)
                .join(TaskProject, TaskProject.task_id == Task.id)
                .where(
                    TaskProject.project_id == project.id,
                    Task.deleted_at.is_(None),
                    Task.parent_id.is_(None),
                )
            )
        ).all()
        if p.section_id in order
    ]
    top.sort(key=lambda tp: (order[tp[1].section_id], tp[1].position))

    # subtasks, level by level (depth is capped), each listed after its parent
    children: dict[uuid.UUID, list[Task]] = {}
    frontier = [t.id for t, _ in top]
    while frontier:
        rows = list(
            (
                await session.execute(
                    select(Task)
                    .where(Task.parent_id.in_(frontier), Task.deleted_at.is_(None))
                    .order_by(Task.parent_position)
                )
            ).scalars()
        )
        for child in rows:
            assert child.parent_id is not None
            children.setdefault(child.parent_id, []).append(child)
        frontier = [c.id for c in rows]

    ordered: list[tuple[Task, str, Task | None]] = []

    def walk(task: Task, section: str, parent: Task | None) -> None:
        ordered.append((task, section, parent))
        for child in children.get(task.id, []):
            walk(child, section, task)

    for task, placement in top:
        walk(task, names[placement.section_id], None)

    ids = [t.id for t, _, _ in ordered]
    users = {
        u.id: u
        for u in (
            await session.execute(
                select(User).where(
                    User.id.in_({t.assignee_id for t, _, _ in ordered if t.assignee_id})
                )
            )
        ).scalars()
    }
    tags: dict[uuid.UUID, list[str]] = {}
    for task_id, name in (
        await session.execute(
            select(TaskTag.task_id, Tag.name)
            .join(Tag, Tag.id == TaskTag.tag_id)
            .where(TaskTag.task_id.in_(ids), Tag.deleted_at.is_(None))
            .order_by(Tag.name)
        )
    ).all():
        tags.setdefault(task_id, []).append(name)
    fields = list(
        (
            await session.execute(
                select(FieldDef)
                .join(ProjectField, ProjectField.field_id == FieldDef.id)
                .where(ProjectField.project_id == project.id, FieldDef.deleted_at.is_(None))
                .order_by(ProjectField.position)
            )
        ).scalars()
    )
    values: dict[tuple[uuid.UUID, uuid.UUID], Any] = {
        (v.task_id, v.field_id): v.value
        for v in (
            await session.execute(
                select(FieldValue).where(
                    FieldValue.task_id.in_(ids),
                    FieldValue.field_id.in_([f.id for f in fields]),
                )
            )
        ).scalars()
    }
    people = {
        u.id: u.name
        for u in (
            await session.execute(select(User).where(User.workspace_id == ctx.workspace_id))
        ).scalars()
    }

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([*HEADERS, *(f.name for f in fields)])
    for task, section, parent in ordered:
        assignee = users.get(task.assignee_id) if task.assignee_id else None
        writer.writerow(
            [
                task.number,
                _date(task.created_at),
                _date(task.completed_at),
                _safe(task.title),
                _safe(section),
                _safe(assignee.name) if assignee else "",
                assignee.email if assignee else "",
                task.start_on.isoformat() if task.start_on else "",
                task.due_on.isoformat() if task.due_on else "",
                _safe(", ".join(tags.get(task.id, []))),
                _safe(plain_text(task.description)),
                _safe(parent.title) if parent else "",
                task.priority or "",
                task.estimate_minutes if task.estimate_minutes is not None else "",
                *(_safe(_field_text(f, values.get((task.id, f.id)), people)) for f in fields),
            ]
        )
    return project, out.getvalue()


def _date(value: datetime | None) -> str:
    return value.date().isoformat() if value else ""


def _safe(text: str) -> str:
    """Spreadsheets run a cell that starts with = + - @ (or a tab / return) as a formula: prefix
    it so a task title can't become one (CSV injection, OWASP)."""
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _field_text(field: FieldDef, value: Any, people: dict[uuid.UUID, str]) -> str:
    if value is None:
        return ""
    options = {
        o.get("id"): o.get("label", "")
        for o in (field.options or [])
        if isinstance(field.options, list)
    }
    if field.type == "single_select":
        return str(options.get(value, ""))
    if field.type == "multi_select":
        return ", ".join(str(options.get(v, "")) for v in value)
    if field.type == "people":
        ids = value if isinstance(value, list) else [value]
        return ", ".join(people.get(uuid.UUID(str(i)), "") for i in ids)
    if field.type == "checkbox":
        return "Yes" if value else "No"
    return str(value)


# Phase 7.5: the portfolio view's CSV export uses the same cell rules
safe_cell = _safe
field_text = _field_text
