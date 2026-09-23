from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Header, Query, status

from momentum.api.deps import CtxDep, UowDep
from momentum.api.schemas import ListOut, MutationMeta, MutationOut, OkOut
from momentum.core.ids import task_key
from momentum.domain.tasks import service
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.tasks.schemas import TaskBatchCreateIn, TaskCreateIn, TaskOut, TaskPatchIn

router = APIRouter(tags=["tasks"])


def task_out(t: Task, p: TaskProject | None) -> TaskOut:
    return TaskOut(
        id=t.id,
        number=t.number,
        key=task_key(t.number),
        title=t.title,
        type=t.type,
        project_id=p.project_id if p else None,
        section_id=p.section_id if p else None,
        position=p.position if p else None,
        assignee_id=t.assignee_id,
        start_on=t.start_on,
        due_on=t.due_on,
        due_at=t.due_at,
        completed_at=t.completed_at,
        parent_id=t.parent_id,
        priority=t.priority,
        version=t.version,
        created_at=t.created_at,
    )


@router.get(
    "/projects/{project_id}/tasks",
    response_model=ListOut[TaskOut],
    summary="Top-level tasks of a project (incomplete in order, or completed paged)",
)
async def list_tasks(
    project_id: uuid.UUID,
    ctx: CtxDep,
    uow: UowDep,
    completed: bool = Query(default=False),
    before: datetime | None = Query(default=None, description="Completed-at cursor"),
) -> ListOut[TaskOut]:
    async with uow.transaction() as s:
        rows = await service.list_project_tasks(
            s, ctx, project_id, completed=completed, before=before
        )
        return ListOut(data=[task_out(t, p) for t, p in rows])


@router.post(
    "/projects/{project_id}/tasks",
    response_model=MutationOut[TaskOut],
    status_code=status.HTTP_201_CREATED,
    summary="Create a task",
)
async def create_task(
    project_id: uuid.UUID, body: TaskCreateIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[TaskOut]:
    async with uow.transaction() as s:
        m = await service.create_task(
            s,
            ctx,
            project_id,
            body.title,
            section_id=body.section_id,
            after_id=body.after_id,
            before_id=body.before_id,
        )
        t, p = m.entity
        return MutationOut(
            data=task_out(t, p), meta=MutationMeta(activity_id=m.activity_id, version=m.version)
        )


@router.post(
    "/projects/{project_id}/tasks/batch",
    response_model=MutationOut[ListOut[TaskOut]],
    status_code=status.HTTP_201_CREATED,
    summary="Create several tasks in order (one undoable batch)",
)
async def create_tasks(
    project_id: uuid.UUID, body: TaskBatchCreateIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[ListOut[TaskOut]]:
    async with uow.transaction() as s:
        m = await service.create_tasks(
            s, ctx, project_id, body.titles, section_id=body.section_id, after_id=body.after_id
        )
        return MutationOut(
            data=ListOut(data=[task_out(t, p) for t, p in m.entity]),
            meta=MutationMeta(batch_id=m.batch_id),
        )


@router.get("/tasks/{task_id}", response_model=TaskOut, summary="A task")
async def get_task(task_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> TaskOut:
    async with uow.transaction() as s:
        t, p, _ = await service.get_task(s, ctx, task_id)
        return task_out(t, p)


@router.patch("/tasks/{task_id}", response_model=MutationOut[TaskOut], summary="Edit a task")
async def patch_task(
    task_id: uuid.UUID,
    body: TaskPatchIn,
    ctx: CtxDep,
    uow: UowDep,
    if_match: int | None = Header(default=None),
) -> MutationOut[TaskOut]:
    async with uow.transaction() as s:
        m = await service.update_task(
            s, ctx, task_id, body.model_dump(exclude_unset=True), expected_version=if_match
        )
        _, p, _ = await service.get_task(s, ctx, task_id)
        return MutationOut(
            data=task_out(m.entity, p),
            meta=MutationMeta(activity_id=m.activity_id, version=m.version),
        )


async def _complete(
    task_id: uuid.UUID, ctx: CtxDep, uow: UowDep, flag: bool
) -> MutationOut[TaskOut]:
    async with uow.transaction() as s:
        m = await service.set_completed(s, ctx, task_id, flag)
        _, p, _ = await service.get_task(s, ctx, task_id)
        return MutationOut(
            data=task_out(m.entity, p),
            meta=MutationMeta(activity_id=m.activity_id, version=m.version),
        )


@router.post("/tasks/{task_id}/complete", response_model=MutationOut[TaskOut], summary="Complete")
async def complete(task_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> MutationOut[TaskOut]:
    return await _complete(task_id, ctx, uow, True)


@router.post(
    "/tasks/{task_id}/uncomplete", response_model=MutationOut[TaskOut], summary="Mark incomplete"
)
async def uncomplete(task_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> MutationOut[TaskOut]:
    return await _complete(task_id, ctx, uow, False)


@router.delete("/tasks/{task_id}", response_model=MutationOut[OkOut], summary="Delete (soft)")
async def delete_task(task_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await service.delete_task(s, ctx, task_id)
    return MutationOut(data=OkOut(), meta=MutationMeta(activity_id=m.activity_id))
