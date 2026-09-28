"""S4.3.1/S4.3.2: templates API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from momentum.api.deps import CtxDep, UowDep
from momentum.api.schemas import ListOut, MutationMeta, MutationOut, OkOut
from momentum.domain.tasks.router import task_out
from momentum.domain.tasks.schemas import TaskOut
from momentum.domain.templates import service
from momentum.domain.templates.schemas import (
    NewProjectFromTemplateIn,
    NewProjectOut,
    NewTaskFromTemplateIn,
    SaveProjectTemplateIn,
    SaveTaskTemplateIn,
    TemplateOut,
)

router = APIRouter(tags=["templates"])


@router.get(
    "/templates",
    response_model=ListOut[TemplateOut],
    summary="Templates (`?kind=`, `?project_id=`)",
)
async def list_templates(
    ctx: CtxDep, uow: UowDep, kind: str = "project", project_id: uuid.UUID | None = None
) -> ListOut[TemplateOut]:
    async with uow.transaction() as s:
        rows = await service.list_templates(s, ctx, kind, project_id)
        return ListOut(data=[TemplateOut.model_validate(t) for t in rows])


@router.post(
    "/templates/from-project",
    response_model=MutationOut[TemplateOut],
    status_code=status.HTTP_201_CREATED,
    summary="Save a project as a reusable template (project admins)",
)
async def save_project_template(
    body: SaveProjectTemplateIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[TemplateOut]:
    async with uow.transaction() as s:
        m = await service.save_project_template(s, ctx, body)
        return MutationOut.of(m, TemplateOut)


@router.get("/templates/{template_id}", response_model=TemplateOut, summary="One template")
async def get_template(template_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> TemplateOut:
    async with uow.transaction() as s:
        return TemplateOut.model_validate(await service.get_template(s, ctx, template_id))


@router.delete("/templates/{template_id}", response_model=OkOut, summary="Delete a template")
async def delete_template(template_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> OkOut:
    async with uow.transaction() as s:
        await service.delete_template(s, ctx, template_id)
    return OkOut()


@router.post(
    "/templates/{template_id}/new-project",
    response_model=MutationOut[NewProjectOut],
    status_code=status.HTTP_201_CREATED,
    summary="Create a new project from a template",
)
async def new_project_from_template(
    template_id: uuid.UUID, body: NewProjectFromTemplateIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[NewProjectOut]:
    async with uow.transaction() as s:
        m = await service.create_project_from_template(s, ctx, template_id, body)
        return MutationOut.of(m, NewProjectOut)


@router.post(
    "/templates/from-task",
    response_model=MutationOut[TemplateOut],
    status_code=status.HTTP_201_CREATED,
    summary="Save a task template (project editors)",
)
async def save_task_template(
    body: SaveTaskTemplateIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[TemplateOut]:
    async with uow.transaction() as s:
        m = await service.save_task_template(s, ctx, body)
        return MutationOut.of(m, TemplateOut)


@router.post(
    "/templates/{template_id}/new-task",
    response_model=MutationOut[TaskOut],
    status_code=status.HTTP_201_CREATED,
    summary="Create a task from a task template",
)
async def new_task_from_template(
    template_id: uuid.UUID, body: NewTaskFromTemplateIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[TaskOut]:
    async with uow.transaction() as s:
        m = await service.create_task_from_template(s, ctx, template_id, body)
        t, p = m.entity
        return MutationOut(
            data=task_out(t, p),
            meta=MutationMeta(activity_id=m.activity_id, version=m.version),
        )
