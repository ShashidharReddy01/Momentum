"""Phase 7.5 (spec §6.1): the facts builders read, always for projects the requester can see.

Callers resolve the scope first (``get_visible_project``, ``scope_projects``); every query here
then stays inside those projects. A task tagged ``internal`` (case-insensitive) is marked, so a
customer report can leave it out.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.core.ids import task_key
from momentum.domain.fields.models import FieldDef, FieldValue
from momentum.domain.sections.models import Section
from momentum.domain.tags.models import Tag, TaskTag
from momentum.domain.tasks.models import Task, TaskDependency, TaskProject
from momentum.domain.users.models import User

INTERNAL_TAG = "internal"


@dataclass
class TaskFact:
    id: uuid.UUID
    key: str
    title: str
    type: str
    assignee_id: uuid.UUID | None
    assignee: str | None
    due_on: date | None
    completed_at: datetime | None
    created_at: datetime
    project_id: uuid.UUID
    project: str
    section: str | None
    tags: list[str] = field(default_factory=list)

    @property
    def internal(self) -> bool:
        return any(t.lower() == INTERNAL_TAG for t in self.tags)

    @property
    def done(self) -> bool:
        return self.completed_at is not None

    def overdue(self, today: date) -> bool:
        return not self.done and self.due_on is not None and self.due_on < today


def today_for(ctx: Ctx) -> date:
    try:
        tz = ZoneInfo(ctx.actor.timezone)
    except (KeyError, ValueError):
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date()


def local_date(value: datetime | None, ctx: Ctx) -> date | None:
    if value is None:
        return None
    try:
        tz = ZoneInfo(ctx.actor.timezone)
    except (KeyError, ValueError):
        tz = ZoneInfo("UTC")
    return value.astimezone(tz).date()


async def project_tasks(
    session: AsyncSession, project_ids: list[uuid.UUID], names: dict[uuid.UUID, str]
) -> list[TaskFact]:
    """Top-level, live tasks placed in these (visible) projects, with assignee, section, tags."""
    if not project_ids:
        return []
    rows = (
        await session.execute(
            select(Task, TaskProject.project_id, Section.name, User.name)
            .join(TaskProject, TaskProject.task_id == Task.id)
            .outerjoin(Section, Section.id == TaskProject.section_id)
            .outerjoin(User, User.id == Task.assignee_id)
            .where(
                TaskProject.project_id.in_(project_ids),
                Task.deleted_at.is_(None),
                Task.parent_id.is_(None),
            )
            .order_by(Task.due_on.nulls_last(), Task.number)
        )
    ).all()
    ids = [t.id for t, *_ in rows]
    tags: dict[uuid.UUID, list[str]] = defaultdict(list)
    if ids:
        for tid, name in (
            await session.execute(
                select(TaskTag.task_id, Tag.name)
                .join(Tag, Tag.id == TaskTag.tag_id)
                .where(TaskTag.task_id.in_(ids), Tag.deleted_at.is_(None))
            )
        ).tuples():
            tags[tid].append(name)
    seen: set[uuid.UUID] = set()
    out: list[TaskFact] = []
    for t, pid, section, assignee in rows:
        if t.id in seen:  # a task in two of these projects counts once
            continue
        seen.add(t.id)
        out.append(
            TaskFact(
                id=t.id,
                key=task_key(t.number),
                title=t.title,
                type=t.type,
                assignee_id=t.assignee_id,
                assignee=assignee,
                due_on=t.due_on,
                completed_at=t.completed_at,
                created_at=t.created_at,
                project_id=pid,
                project=names.get(pid, ""),
                section=section,
                tags=sorted(tags.get(t.id, [])),
            )
        )
    return out


async def task_fields(
    session: AsyncSession, ctx: Ctx, task_ids: list[uuid.UUID]
) -> tuple[list[FieldDef], dict[tuple[uuid.UUID, uuid.UUID], Any]]:
    """The task fields these tasks have values for, and the values."""
    if not task_ids:
        return [], {}
    values = {
        (tid, fid): v
        for tid, fid, v in (
            await session.execute(
                select(FieldValue.task_id, FieldValue.field_id, FieldValue.value).where(
                    FieldValue.task_id.in_(task_ids)
                )
            )
        ).tuples()
    }
    fids = {fid for _t, fid in values}
    defs = list(
        (
            await session.execute(
                select(FieldDef)
                .where(
                    FieldDef.id.in_(fids),
                    FieldDef.workspace_id == ctx.workspace_id,
                    FieldDef.deleted_at.is_(None),
                )
                .order_by(FieldDef.name)
            )
        ).scalars()
    )
    return defs, values


def option_label(f: FieldDef, value: Any) -> str | None:
    for o in f.options or [] if isinstance(f.options, list) else []:
        if isinstance(o, dict) and o.get("id") == value:
            return str(o.get("label", ""))
    return None


async def waiting_on_customer(
    session: AsyncSession, ctx: Ctx, task_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """Open tasks whose "Waiting on" field is "Customer" (by name, like the portfolio column)."""
    defs, values = await task_fields(session, ctx, task_ids)
    waiting = next((f for f in defs if f.name.strip().lower() == "waiting on"), None)
    if waiting is None:
        return set()
    return {
        tid
        for (tid, fid), v in values.items()
        if fid == waiting.id and (option_label(waiting, v) or "").lower() == "customer"
    }


async def blockers(session: AsyncSession, task_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """How many of these tasks each task blocked (top blockers in a close-out)."""
    if not task_ids:
        return {}
    return {
        tid: int(n)
        for tid, n in (
            await session.execute(
                select(TaskDependency.depends_on_id, func.count())
                .where(TaskDependency.task_id.in_(task_ids))
                .group_by(TaskDependency.depends_on_id)
            )
        ).tuples()
    }


def in_period(value: datetime | None, start: date, end: date, ctx: Ctx) -> bool:
    d = local_date(value, ctx)
    return d is not None and start <= d <= end


def now_utc() -> datetime:
    return datetime.now(UTC)


def days(a: date, b: date) -> int:
    return (b - a) // timedelta(days=1)
