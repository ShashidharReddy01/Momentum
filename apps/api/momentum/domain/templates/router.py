"""S4.3.1/S4.3.2: templates API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from momentum.api.deps import CtxDep, UowDep
from momentum.api.schemas import ListOut, MutationOut, OkOut
from momentum.domain.templates import service
from momentum.domain.templates.schemas import (
    NewProjectFromTemplateIn,
    NewProjectOut,
    SaveProjectTemplateIn,
    TemplateOut,
)

router = APIRouter(tags=["templates"])


@router.get("/templates", response_model=ListOut[TemplateOut], summary="Templates (`?kind=`)")
async def list_templates(ctx: CtxDep, uow: UowDep, kind: str = "project") -> ListOut[TemplateOut]:
    async with uow.transaction() as s:
        rows = await service.list_templates(s, ctx, kind)
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
