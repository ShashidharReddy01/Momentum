from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Query, status

from momentum.api.deps import CtxDep, UowDep
from momentum.api.schemas import ListOut, MutationMeta, MutationOut, OkOut
from momentum.core.mutation import Mutation
from momentum.domain.access import get_visible_project
from momentum.domain.sections import service
from momentum.domain.sections.models import Section
from momentum.domain.sections.schemas import (
    SectionCreateIn,
    SectionMoveIn,
    SectionOut,
    SectionPatchIn,
)

router = APIRouter(tags=["sections"])


def _meta(m: Mutation[Section]) -> MutationMeta:
    return MutationMeta(activity_id=m.activity_id, batch_id=m.batch_id, version=m.version)


@router.get(
    "/projects/{project_id}/sections",
    response_model=ListOut[SectionOut],
    summary="Sections of a project, in order",
)
async def list_sections(project_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> ListOut[SectionOut]:
    async with uow.transaction() as s:
        await get_visible_project(s, ctx, project_id)
        return ListOut(
            data=[SectionOut.model_validate(x) for x in await service.list_sections(s, project_id)]
        )


@router.post(
    "/projects/{project_id}/sections",
    response_model=MutationOut[SectionOut],
    status_code=status.HTTP_201_CREATED,
    summary="Add a section",
)
async def create_section(
    project_id: uuid.UUID, body: SectionCreateIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[SectionOut]:
    async with uow.transaction() as s:
        m = await service.create_section(
            s, ctx, project_id, body.name, body.after_id, body.before_id
        )
        return MutationOut(data=SectionOut.model_validate(m.entity), meta=_meta(m))


@router.patch(
    "/sections/{section_id}", response_model=MutationOut[SectionOut], summary="Rename a section"
)
async def rename_section(
    section_id: uuid.UUID, body: SectionPatchIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[SectionOut]:
    async with uow.transaction() as s:
        m = await service.rename_section(s, ctx, section_id, body.name)
        return MutationOut(data=SectionOut.model_validate(m.entity), meta=_meta(m))


@router.post(
    "/sections/{section_id}/move",
    response_model=MutationOut[SectionOut],
    summary="Move a section before/after another",
)
async def move_section(
    section_id: uuid.UUID, body: SectionMoveIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[SectionOut]:
    async with uow.transaction() as s:
        m = await service.move_section(s, ctx, section_id, body.after_id, body.before_id)
        return MutationOut(data=SectionOut.model_validate(m.entity), meta=_meta(m))


@router.delete(
    "/sections/{section_id}",
    response_model=MutationOut[OkOut],
    summary="Delete a section (tasks moved or deleted)",
)
async def delete_section(
    section_id: uuid.UUID,
    ctx: CtxDep,
    uow: UowDep,
    tasks: Literal["move_to", "delete"] = Query(default="move_to"),
    target_section_id: uuid.UUID | None = None,
) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await service.delete_section(
            s, ctx, section_id, tasks=tasks, target_section_id=target_section_id
        )
    return MutationOut(data=OkOut(), meta=_meta(m))
