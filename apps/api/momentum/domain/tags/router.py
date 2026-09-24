from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from momentum.api.deps import CtxDep, UowDep
from momentum.api.schemas import ListOut, MutationOut, OkOut
from momentum.domain.tags import service
from momentum.domain.tags.schemas import TagCreateIn, TagOut, TagPatchIn, TaskTagIn, TaskTagOut
from momentum.domain.tasks.router import task_out
from momentum.domain.tasks.schemas import TaskOut

router = APIRouter(tags=["tags"])


@router.get("/tags", response_model=ListOut[TagOut], summary="The workspace's tag library")
async def list_tags(ctx: CtxDep, uow: UowDep) -> ListOut[TagOut]:
    async with uow.transaction() as s:
        tags = await service.list_tags(s, ctx)
        return ListOut(data=[TagOut.model_validate(t) for t in tags])


@router.post(
    "/tags",
    response_model=MutationOut[TagOut],
    status_code=status.HTTP_201_CREATED,
    summary="Create a tag",
)
async def create_tag(body: TagCreateIn, ctx: CtxDep, uow: UowDep) -> MutationOut[TagOut]:
    async with uow.transaction() as s:
        m = await service.create_tag(s, ctx, body)
        return MutationOut.of(m, TagOut)


@router.patch(
    "/tags/{tag_id}", response_model=MutationOut[TagOut], summary="Rename or recolor a tag"
)
async def patch_tag(
    tag_id: uuid.UUID, body: TagPatchIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[TagOut]:
    async with uow.transaction() as s:
        m = await service.patch_tag(s, ctx, tag_id, body)
        return MutationOut.of(m, TagOut)


@router.delete("/tags/{tag_id}", response_model=OkOut, summary="Delete a tag")
async def delete_tag(tag_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> OkOut:
    async with uow.transaction() as s:
        await service.delete_tag(s, ctx, tag_id)
    return OkOut()


@router.get(
    "/tags/{tag_id}/tasks",
    response_model=ListOut[TaskOut],
    summary="Tasks tagged with this tag, across every visible project",
)
async def list_tag_tasks(tag_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> ListOut[TaskOut]:
    async with uow.transaction() as s:
        rows = await service.list_tag_tasks(s, ctx, tag_id)
        return ListOut(data=[task_out(t, p) for t, p in rows])


@router.get(
    "/projects/{project_id}/task-tags",
    response_model=ListOut[TaskTagOut],
    summary="Every tag across a project's tasks, in one call",
)
async def list_project_task_tags(
    project_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> ListOut[TaskTagOut]:
    async with uow.transaction() as s:
        rows = await service.list_project_task_tags(s, ctx, project_id)
        return ListOut(
            data=[
                TaskTagOut(task_id=task_id, tag=TagOut.model_validate(tag)) for task_id, tag in rows
            ]
        )


@router.get("/tasks/{task_id}/tags", response_model=ListOut[TagOut], summary="A task's tags")
async def get_task_tags(task_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> ListOut[TagOut]:
    async with uow.transaction() as s:
        tags = await service.get_task_tags(s, ctx, task_id)
        return ListOut(data=[TagOut.model_validate(t) for t in tags])


@router.post(
    "/tasks/{task_id}/tags",
    response_model=MutationOut[TagOut],
    status_code=status.HTTP_201_CREATED,
    summary="Tag a task (attach an existing tag, or create one inline by name)",
)
async def add_task_tag(
    task_id: uuid.UUID, body: TaskTagIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[TagOut]:
    async with uow.transaction() as s:
        m = await service.add_task_tag(s, ctx, task_id, body.tag_id, body.name)
        return MutationOut.of(m, TagOut)


@router.delete(
    "/tasks/{task_id}/tags/{tag_id}", response_model=OkOut, summary="Remove a tag from a task"
)
async def remove_task_tag(task_id: uuid.UUID, tag_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> OkOut:
    async with uow.transaction() as s:
        await service.remove_task_tag(s, ctx, task_id, tag_id)
    return OkOut()
