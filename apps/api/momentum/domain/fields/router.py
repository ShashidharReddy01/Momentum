from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from momentum.api.deps import CtxDep, UowDep
from momentum.api.schemas import ListOut, MutationOut, OkOut
from momentum.domain.fields import service
from momentum.domain.fields.schemas import (
    FieldAttachIn,
    FieldCreateIn,
    FieldOut,
    FieldPatchIn,
    FieldValueIn,
    FieldValueOut,
    ProjectFieldMoveIn,
    ProjectFieldOut,
    ProjectFieldVisibilityIn,
)

router = APIRouter(tags=["fields"])


@router.get("/fields", response_model=ListOut[FieldOut], summary="The workspace's field library")
async def list_fields(ctx: CtxDep, uow: UowDep) -> ListOut[FieldOut]:
    async with uow.transaction() as s:
        fields = await service.list_workspace_fields(s, ctx)
        return ListOut(data=[FieldOut.model_validate(f) for f in fields])


@router.get(
    "/projects/{project_id}/fields",
    response_model=ListOut[ProjectFieldOut],
    summary="Fields attached to a project, in order",
)
async def list_project_fields(
    project_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> ListOut[ProjectFieldOut]:
    async with uow.transaction() as s:
        rows = await service.list_project_fields(s, ctx, project_id)
        return ListOut(
            data=[
                ProjectFieldOut(
                    field=FieldOut.model_validate(f), position=pf.position, is_visible=pf.is_visible
                )
                for pf, f in rows
            ]
        )


@router.post(
    "/projects/{project_id}/fields",
    response_model=MutationOut[FieldOut],
    status_code=status.HTTP_201_CREATED,
    summary="Create a field and attach it to this project",
)
async def create_field(
    project_id: uuid.UUID, body: FieldCreateIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[FieldOut]:
    async with uow.transaction() as s:
        m = await service.create_field(s, ctx, project_id, body)
        return MutationOut.of(m, FieldOut)


@router.post(
    "/projects/{project_id}/fields/attach",
    response_model=MutationOut[FieldOut],
    summary="Attach an existing library field to this project",
)
async def attach_field(
    project_id: uuid.UUID, body: FieldAttachIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[FieldOut]:
    async with uow.transaction() as s:
        m = await service.attach_field(
            s, ctx, project_id, body.field_id, body.after_id, body.before_id
        )
        return MutationOut.of(m, FieldOut)


@router.patch(
    "/projects/{project_id}/fields/{field_id}",
    response_model=MutationOut[FieldOut],
    summary="Edit a field's name, description, or options",
)
async def patch_field(
    project_id: uuid.UUID, field_id: uuid.UUID, body: FieldPatchIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[FieldOut]:
    async with uow.transaction() as s:
        m = await service.patch_field(s, ctx, project_id, field_id, body)
        return MutationOut.of(m, FieldOut)


@router.post(
    "/projects/{project_id}/fields/{field_id}/archive",
    response_model=MutationOut[FieldOut],
    summary="Archive a field (hides it everywhere; values are kept)",
)
async def archive_field(
    project_id: uuid.UUID, field_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> MutationOut[FieldOut]:
    async with uow.transaction() as s:
        m = await service.archive_field(s, ctx, project_id, field_id)
        return MutationOut.of(m, FieldOut)


@router.delete(
    "/projects/{project_id}/fields/{field_id}",
    response_model=OkOut,
    summary="Remove a field from this project only",
)
async def detach_field(
    project_id: uuid.UUID, field_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> OkOut:
    async with uow.transaction() as s:
        await service.detach_field(s, ctx, project_id, field_id)
    return OkOut()


@router.post(
    "/projects/{project_id}/fields/{field_id}/move",
    response_model=MutationOut[FieldOut],
    summary="Reorder a field within this project",
)
async def move_field(
    project_id: uuid.UUID,
    field_id: uuid.UUID,
    body: ProjectFieldMoveIn,
    ctx: CtxDep,
    uow: UowDep,
) -> MutationOut[FieldOut]:
    async with uow.transaction() as s:
        m = await service.move_project_field(
            s, ctx, project_id, field_id, body.after_id, body.before_id
        )
        return MutationOut.of(m, FieldOut)


@router.patch(
    "/projects/{project_id}/fields/{field_id}/visibility",
    response_model=MutationOut[FieldOut],
    summary="Show or hide a field in this project's views",
)
async def set_field_visibility(
    project_id: uuid.UUID,
    field_id: uuid.UUID,
    body: ProjectFieldVisibilityIn,
    ctx: CtxDep,
    uow: UowDep,
) -> MutationOut[FieldOut]:
    async with uow.transaction() as s:
        m = await service.set_field_visibility(s, ctx, project_id, field_id, body.is_visible)
        return MutationOut.of(m, FieldOut)


@router.get(
    "/tasks/{task_id}/fields",
    response_model=ListOut[FieldValueOut],
    summary="A task's custom field values",
)
async def get_task_field_values(
    task_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> ListOut[FieldValueOut]:
    async with uow.transaction() as s:
        values = await service.get_task_field_values(s, ctx, task_id)
        return ListOut(data=[FieldValueOut.model_validate(v) for v in values])


@router.put(
    "/tasks/{task_id}/fields/{field_id}",
    response_model=FieldValueOut,
    summary="Set (or clear, with value: null) a task's value for a field",
)
async def set_task_field_value(
    task_id: uuid.UUID, field_id: uuid.UUID, body: FieldValueIn, ctx: CtxDep, uow: UowDep
) -> FieldValueOut:
    async with uow.transaction() as s:
        row = await service.set_task_field_value(s, ctx, task_id, field_id, body.value)
        return FieldValueOut(field_id=field_id, value=row.value if row else None)
