"""Phase 7.5 (spec §5.7): one snapshot per live project per day, so trend widgets (value in
Implementation over time, overdue across onboarding per week) read the past instead of
recomputing it.

``data``: ``open``, ``completed``, ``overdue`` (top-level tasks), ``progress``, ``status``,
``fields`` (every project field value, stored form, so the stage is in there) and ``forecast``
(``p50``/``p80``). The nightly job writes today's row for every live project (computed data: no
activity, no events) and drops rows older than the retention. ``backfill`` reconstructs missing
past days from task dates, ``project_field_events`` and status updates, best effort, marked
``reconstructed: true``.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.domain.fields.models import FieldDef, ProjectFieldEvent, ProjectFieldValue
from momentum.domain.forecasts.models import Forecast
from momentum.domain.projects.models import Project, ProjectSnapshot
from momentum.domain.status_updates.models import StatusUpdate
from momentum.domain.tasks.models import Task, TaskProject

RETENTION_DAYS = 730  # spec §5.7
MAX_BACKFILL_DAYS = 730


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


async def _live_projects(session: AsyncSession) -> list[Project]:
    rows = await session.execute(
        select(Project).where(
            Project.deleted_at.is_(None),
            Project.archived_at.is_(None),
            Project.is_template.is_(False),
        )
    )
    return list(rows.scalars())


async def _live_field_ids(session: AsyncSession) -> set[uuid.UUID]:
    rows = await session.execute(
        select(FieldDef.id).where(FieldDef.applies_to == "project", FieldDef.deleted_at.is_(None))
    )
    return set(rows.scalars())


async def _upsert(
    session: AsyncSession, rows: list[dict[str, Any]], *, overwrite: bool = True
) -> None:
    if not rows:
        return
    stmt = insert(ProjectSnapshot).values(rows)
    stmt = (
        stmt.on_conflict_do_update(
            index_elements=["project_id", "day"], set_={"data": stmt.excluded.data}
        )
        if overwrite
        else stmt.on_conflict_do_nothing(index_elements=["project_id", "day"])
    )
    await session.execute(stmt)


async def snapshot_all(session: AsyncSession, day: date | None = None) -> int:
    """Today's snapshot for every live project in every workspace (re-running the same day
    replaces it), then retention. A fixed number of queries, however many projects."""
    day = day or datetime.now(UTC).date()
    projects = await _live_projects(session)
    if not projects:
        return 0
    ids = [p.id for p in projects]
    counts: dict[uuid.UUID, tuple[int, int, int]] = {}
    for pid, total, done, overdue in (
        await session.execute(
            select(
                TaskProject.project_id,
                func.count(),
                func.count(Task.completed_at),
                func.count().filter(Task.completed_at.is_(None), Task.due_on < day),
            )
            .join(Task, Task.id == TaskProject.task_id)
            .where(
                TaskProject.project_id.in_(ids),
                Task.parent_id.is_(None),
                Task.deleted_at.is_(None),
            )
            .group_by(TaskProject.project_id)
        )
    ).all():
        counts[pid] = (int(total), int(done), int(overdue))
    live_fields = await _live_field_ids(session)
    values: dict[uuid.UUID, dict[str, Any]] = defaultdict(dict)
    for pid, fid, value in (
        await session.execute(
            select(
                ProjectFieldValue.project_id, ProjectFieldValue.field_id, ProjectFieldValue.value
            ).where(ProjectFieldValue.project_id.in_(ids))
        )
    ).all():
        if fid in live_fields:
            values[pid][str(fid)] = value
    forecasts = {
        pid: (p50, p80)
        for pid, p50, p80 in (
            await session.execute(
                select(Forecast.project_id, Forecast.p50, Forecast.p80)
                .where(Forecast.project_id.in_(ids))
                .distinct(Forecast.project_id)
                .order_by(Forecast.project_id, Forecast.computed_at.desc())
            )
        ).all()
    }
    rows = []
    for p in projects:
        total, done, overdue = counts.get(p.id, (0, 0, 0))
        p50, p80 = forecasts.get(p.id, (None, None))
        rows.append(
            {
                "project_id": p.id,
                "day": day,
                "workspace_id": p.workspace_id,
                "data": {
                    "open": total - done,
                    "completed": done,
                    "overdue": overdue,
                    "progress": round(done / total, 4) if total else None,
                    "status": p.status,
                    "fields": values.get(p.id, {}),
                    "forecast": {"p50": _iso(p50), "p80": _iso(p80)},
                },
            }
        )
    for i in range(0, len(rows), 500):
        await _upsert(session, rows[i : i + 500])
    await session.execute(
        delete(ProjectSnapshot).where(ProjectSnapshot.day < day - timedelta(days=RETENTION_DAYS))
    )
    return len(rows)


async def backfill(session: AsyncSession, days: int, today: date | None = None) -> int:
    """Reconstruct the last ``days`` days (before today) where no snapshot exists. Best effort:
    a task counts as done from its ``completed_at`` (a reopened task's earlier completion is
    lost), project fields from their history, the status from the newest update by then; no
    forecast. Existing rows are never overwritten. Returns the number of rows written."""
    if not 1 <= days <= MAX_BACKFILL_DAYS:
        raise ValueError(f"days must be between 1 and {MAX_BACKFILL_DAYS}")
    today = today or datetime.now(UTC).date()
    first = today - timedelta(days=days)
    projects = await _live_projects(session)
    if not projects:
        return 0
    ids = [p.id for p in projects]
    tasks: dict[uuid.UUID, list[tuple[datetime, datetime | None, date | None]]] = defaultdict(list)
    for pid, created, completed, due in (
        await session.execute(
            select(TaskProject.project_id, Task.created_at, Task.completed_at, Task.due_on)
            .join(Task, Task.id == TaskProject.task_id)
            .where(
                TaskProject.project_id.in_(ids),
                Task.parent_id.is_(None),
                Task.deleted_at.is_(None),
            )
        )
    ).all():
        tasks[pid].append((created, completed, due))
    live_fields = await _live_field_ids(session)
    events: dict[uuid.UUID, list[tuple[datetime, str, Any]]] = defaultdict(list)
    for pid, fid, new, at in (
        await session.execute(
            select(
                ProjectFieldEvent.project_id,
                ProjectFieldEvent.field_id,
                ProjectFieldEvent.new,
                ProjectFieldEvent.at,
            )
            .where(ProjectFieldEvent.project_id.in_(ids))
            .order_by(ProjectFieldEvent.at, ProjectFieldEvent.id)
        )
    ).all():
        if fid in live_fields:
            events[pid].append((at, str(fid), new))
    statuses: dict[uuid.UUID, list[tuple[datetime, str]]] = defaultdict(list)
    for pid, at, status in (
        await session.execute(
            select(StatusUpdate.entity_id, StatusUpdate.created_at, StatusUpdate.status)
            .where(
                StatusUpdate.entity_type == "project",
                StatusUpdate.entity_id.in_(ids),
                StatusUpdate.deleted_at.is_(None),
            )
            .order_by(StatusUpdate.created_at)
        )
    ).all():
        statuses[pid].append((at, status))
    have = {
        (pid, d)
        for pid, d in (
            await session.execute(
                select(ProjectSnapshot.project_id, ProjectSnapshot.day).where(
                    ProjectSnapshot.project_id.in_(ids), ProjectSnapshot.day >= first
                )
            )
        ).all()
    }
    written = 0
    batch: list[dict[str, Any]] = []
    for p in projects:
        created_day = p.created_at.date()
        for n in range(days):
            day = first + timedelta(days=n)
            if day < created_day or (p.id, day) in have:
                continue
            end = datetime.combine(day, time.max, tzinfo=UTC)
            alive = [t for t in tasks[p.id] if t[0] <= end]
            done = sum(1 for t in alive if t[1] is not None and t[1] <= end)
            overdue = sum(
                1 for t in alive if (t[1] is None or t[1] > end) and t[2] is not None and t[2] < day
            )
            fields: dict[str, Any] = {}
            for at, fid, new in events[p.id]:
                if at > end:
                    break
                if new is None:
                    fields.pop(fid, None)
                else:
                    fields[fid] = new
            status = None
            for at, st in statuses[p.id]:
                if at > end:
                    break
                status = st
            batch.append(
                {
                    "project_id": p.id,
                    "day": day,
                    "workspace_id": p.workspace_id,
                    "data": {
                        "open": len(alive) - done,
                        "completed": done,
                        "overdue": overdue,
                        "progress": round(done / len(alive), 4) if alive else None,
                        "status": status,
                        "fields": fields,
                        "forecast": {"p50": None, "p80": None},
                        "reconstructed": True,
                    },
                }
            )
            if len(batch) >= 500:
                await _upsert(session, batch, overwrite=False)
                written += len(batch)
                batch = []
    await _upsert(session, batch, overwrite=False)
    return written + len(batch)


async def project_snapshots(
    session: AsyncSession, project_ids: list[uuid.UUID], start: date, end: date
) -> list[ProjectSnapshot]:
    """Snapshots of these projects between two days (callers check visibility first)."""
    if not project_ids:
        return []
    rows = await session.execute(
        select(ProjectSnapshot)
        .where(
            ProjectSnapshot.project_id.in_(project_ids),
            ProjectSnapshot.day >= start,
            ProjectSnapshot.day <= end,
        )
        .order_by(ProjectSnapshot.day, ProjectSnapshot.project_id)
    )
    return list(rows.scalars())
