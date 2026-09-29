from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.api.deps import CtxDep, UowDep
from momentum.api.schemas import ListOut, MutationMeta, MutationOut, OkOut
from momentum.domain.access import task_ancestors
from momentum.domain.mytasks import service
from momentum.domain.mytasks.models import MyTaskPlacement
from momentum.domain.mytasks.schemas import MyTaskMoveIn, MyTaskOut
from momentum.domain.projects.models import Project
from momentum.domain.tasks import service as tasks
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.tasks.router import task_out
from momentum.domain.tasks.schemas import ProjectRef

router = APIRouter(prefix="/me", tags=["my tasks"])


async def my_task_rows(
    s: AsyncSession, rows: list[tuple[Task, MyTaskPlacement | None]]
) -> list[MyTaskOut]:
    # project of each task (subtasks: of their top-level task), a few queries for the whole list
    roots: dict[uuid.UUID, uuid.UUID] = {}
    for t, _ in rows:
        chain = await task_ancestors(s, t) if t.parent_id else []
        roots[t.id] = chain[-1].id if chain else t.id
    # a task's first live project (a task can be in several; deleted ones are skipped)
    placements: dict[uuid.UUID, TaskProject] = {}
    projects: dict[uuid.UUID, Project] = {}
    if roots:
        live = await s.execute(
            select(TaskProject, Project)
            .join(Project, Project.id == TaskProject.project_id)
            .where(TaskProject.task_id.in_(set(roots.values())), Project.deleted_at.is_(None))
            .order_by(TaskProject.task_id, Project.created_at, Project.id)
        )
        for placed, proj in live.tuples():
            if placed.task_id not in placements:
                placements[placed.task_id] = placed
                projects[proj.id] = proj
    counts = await tasks.subtask_counts(s, [t.id for t, _ in rows])
    out = []
    for t, mine in rows:
        pl: TaskProject | None = placements.get(roots[t.id])
        project = projects.get(pl.project_id) if pl else None
        out.append(
            MyTaskOut(
                **task_out(t, pl, counts.get(t.id)).model_dump(),
                bucket=mine.bucket if mine else None,
                my_position=mine.position if mine else None,
                project=ProjectRef(id=project.id, name=project.name, color=project.color)
                if project
                else None,
            )
        )
    return out


@router.get(
    "/tasks", response_model=ListOut[MyTaskOut], summary="My Tasks (open in buckets, or completed)"
)
async def my_tasks(
    ctx: CtxDep, uow: UowDep, completed: bool = Query(default=False)
) -> ListOut[MyTaskOut]:
    async with uow.transaction() as s:
        rows = await service.list_my_tasks(s, ctx, completed=completed)
        return ListOut(data=await my_task_rows(s, rows))


@router.post(
    "/tasks/{task_id}/move",
    response_model=MutationOut[OkOut],
    summary="Move a task within My Tasks (pins it to that bucket)",
)
async def move_my_task(
    task_id: uuid.UUID, body: MyTaskMoveIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await service.move_my_task(
            s, ctx, task_id, body.bucket, after_id=body.after_id, before_id=body.before_id
        )
    return MutationOut(data=OkOut(), meta=MutationMeta(activity_id=m.activity_id))


class NudgeSnoozeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    until: date | None = Field(description="Leave the task alone until this date; null resumes")


@router.put(
    "/tasks/{task_id}/nudge-snooze",
    response_model=MutationOut[OkOut],
    summary="Snooze Nudge's reminders on one of my tasks until a date (S5.3.4)",
)
async def snooze_nudges(
    task_id: uuid.UUID, body: NudgeSnoozeIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await service.snooze_nudges(s, ctx, task_id, body.until)
    return MutationOut(data=OkOut(), meta=MutationMeta(activity_id=m.activity_id))
