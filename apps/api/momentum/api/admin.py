"""S7.5.4: the admin's operations views: background jobs (what failed, retry it) and the audit
trail (who changed what, searchable). Admins only.

Jobs are the queue's own rows (Procrastinate, in the Momentum schema): read here and retried with
its own function. The audit trail is the ``activity`` table every change writes; it names tasks
and projects only when the admin can see them (private projects stay private even to admins).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select, text

from momentum.api.deps import CtxDep, UowDep
from momentum.api.schemas import ListOut
from momentum.core.activity import Activity, record_activity
from momentum.core.errors import NotFound
from momentum.core.permissions import Action, require
from momentum.domain.access import visible_projects_clause
from momentum.domain.projects.models import Project
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.users.models import User

router = APIRouter(prefix="/admin", tags=["admin"])
JOB_STATUSES = ("todo", "doing", "succeeded", "failed", "cancelled", "aborting", "aborted")


class JobOut(BaseModel):
    id: int
    task_name: str
    queue_name: str
    status: str
    attempts: int
    scheduled_at: datetime | None
    last_event_at: datetime | None = Field(description="When it last started, failed or finished")


class JobsOut(BaseModel):
    counts: dict[str, int] = Field(description="Jobs per status (the whole queue)")
    jobs: list[JobOut]


@router.get(
    "/jobs", response_model=JobsOut, summary="Background jobs: counts and the latest (admins)"
)
async def list_jobs(
    ctx: CtxDep,
    uow: UowDep,
    status: str = Query(
        default="failed", pattern="^(todo|doing|succeeded|failed|cancelled|aborting|aborted)$"
    ),
    limit: int = Query(default=50, ge=1, le=200),
) -> JobsOut:
    require(ctx, Action.WORKSPACE_ADMIN)
    async with uow.transaction() as s:
        counts = {
            str(k): int(n)
            for k, n in (
                await s.execute(
                    text("select status, count(*) from procrastinate_jobs group by status")
                )
            ).all()
        }
        rows = (
            await s.execute(
                text(
                    "select j.id, j.task_name, j.queue_name, j.status, j.attempts, j.scheduled_at, "
                    "(select max(at) from procrastinate_events e where e.job_id = j.id) "
                    "from procrastinate_jobs j "
                    "where j.status = cast(:st as procrastinate_job_status) "
                    "order by j.id desc limit :n"
                ),
                {"st": status, "n": limit},
            )
        ).all()
    return JobsOut(
        counts={k: counts.get(k, 0) for k in JOB_STATUSES},
        jobs=[
            JobOut(
                id=r[0],
                task_name=r[1],
                queue_name=r[2],
                status=str(r[3]),
                attempts=r[4],
                scheduled_at=r[5],
                last_event_at=r[6],
            )
            for r in rows
        ],
    )


@router.post(
    "/jobs/{job_id}/retry", response_model=JobOut, summary="Run a failed job again (admins)"
)
async def retry_job(job_id: int, ctx: CtxDep, uow: UowDep) -> JobOut:
    require(ctx, Action.WORKSPACE_ADMIN)
    async with uow.transaction() as s:
        row = (
            await s.execute(
                text("select task_name, status from procrastinate_jobs where id = :i"),
                {"i": job_id},
            )
        ).first()
        if row is None or str(row[1]) != "failed":
            raise NotFound("No failed job with that id")
        await s.execute(
            text("select procrastinate_retry_job_v2(:i, now(), null, null, null)"), {"i": job_id}
        )
        await record_activity(
            s,
            ctx,
            entity_type="job",
            entity_id=uuid.UUID(int=job_id),
            verb="job.retried",
            changes={"task_name": (None, row[0])},
        )
        r = (
            await s.execute(
                text(
                    "select id, task_name, queue_name, status, attempts, scheduled_at "
                    "from procrastinate_jobs where id = :i"
                ),
                {"i": job_id},
            )
        ).one()
    return JobOut(
        id=r[0],
        task_name=r[1],
        queue_name=r[2],
        status=str(r[3]),
        attempts=r[4],
        scheduled_at=r[5],
        last_event_at=None,
    )


class AuditEntry(BaseModel):
    id: uuid.UUID
    created_at: datetime
    actor_id: uuid.UUID | None
    actor_name: str | None
    actor_kind: str
    verb: str
    entity_type: str
    entity_id: uuid.UUID
    entity_label: str | None = Field(description="What it was, when the admin may see it")
    changes: list[str] = Field(description="The fields that changed")
    undone: bool


@router.get(
    "/activity",
    response_model=ListOut[AuditEntry],
    summary="The audit trail: every change, newest first, searchable (admins)",
)
async def audit(
    ctx: CtxDep,
    uow: UowDep,
    actor_id: uuid.UUID | None = Query(default=None),
    entity_type: str | None = Query(default=None, max_length=40, pattern=r"^[a-z_]+$"),
    verb: str | None = Query(
        default=None, max_length=80, description="A verb or its prefix (task.)"
    ),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    before: datetime | None = Query(default=None, description="Cursor: entries older than this"),
    limit: int = Query(default=50, ge=1, le=200),
) -> ListOut[AuditEntry]:
    require(ctx, Action.WORKSPACE_ADMIN)
    query = select(Activity).where(Activity.workspace_id == ctx.workspace_id)
    if actor_id:
        query = query.where(Activity.actor_id == actor_id)
    if entity_type:
        query = query.where(Activity.entity_type == entity_type)
    if verb:
        clean = verb.replace("\\", "").replace("%", "").replace("_", r"\_")
        query = query.where(
            or_(Activity.verb == verb, Activity.verb.like(f"{clean}%", escape="\\"))
        )
    if since:
        query = query.where(Activity.created_at >= since)
    if until:
        query = query.where(Activity.created_at <= until)
    if before:
        query = query.where(Activity.created_at < before)
    async with uow.transaction() as s:
        rows = list(
            (await s.execute(query.order_by(Activity.created_at.desc()).limit(limit))).scalars()
        )
        labels = await _labels(s, ctx, rows)
    return ListOut(
        data=[
            AuditEntry(
                id=a.id,
                created_at=a.created_at,
                actor_id=a.actor_id,
                actor_name=labels.get(("user", a.actor_id)) if a.actor_id else None,
                actor_kind=a.actor_kind,
                verb=a.verb,
                entity_type=a.entity_type,
                entity_id=a.entity_id,
                entity_label=labels.get((a.entity_type, a.entity_id)),
                changes=sorted((a.diff or {}).keys()),
                undone=a.undone_at is not None,
            )
            for a in rows
        ]
    )


async def _labels(s: Any, ctx: Any, rows: list[Activity]) -> dict[tuple[str, Any], str]:
    out: dict[tuple[str, Any], str] = {}
    users = {a.actor_id for a in rows if a.actor_id} | {
        a.entity_id for a in rows if a.entity_type == "user"
    }
    if users:
        for uid, name in (
            await s.execute(select(User.id, User.name).where(User.id.in_(users)))
        ).all():
            out[("user", uid)] = name
    tasks = {a.entity_id for a in rows if a.entity_type == "task"}
    if tasks:
        visible = (
            select(TaskProject.task_id)
            .join(Project, Project.id == TaskProject.project_id)
            .where(visible_projects_clause(ctx))
        )
        for tid, title in (
            await s.execute(
                select(Task.id, Task.title).where(
                    Task.id.in_(tasks),
                    # a top-level task in a project the admin sees, or a subtask of one
                    or_(Task.id.in_(visible), Task.parent_id.in_(visible)),
                )
            )
        ).all():
            out[("task", tid)] = title
    projects = {a.entity_id for a in rows if a.entity_type == "project"}
    if projects:
        for pid, name in (
            await s.execute(
                select(Project.id, Project.name).where(
                    Project.id.in_(projects), visible_projects_clause(ctx)
                )
            )
        ).all():
            out[("project", pid)] = name
    return out
