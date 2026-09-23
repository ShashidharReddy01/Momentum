from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.api.deps import CtxDep, UowDep
from momentum.api.schemas import ListOut, MutationMeta, MutationOut, OkOut
from momentum.core.context import Ctx
from momentum.core.mutation import Mutation
from momentum.domain.access import project_role
from momentum.domain.projects import service
from momentum.domain.projects.models import Project
from momentum.domain.projects.schemas import (
    FavoriteIn,
    ProjectCreateIn,
    ProjectDetailOut,
    ProjectMemberOut,
    ProjectOut,
    ProjectPatchIn,
    SectionBrief,
)
from momentum.domain.users.schemas import UserOut

router = APIRouter(prefix="/projects", tags=["projects"])
favorites_router = APIRouter(prefix="/favorites", tags=["projects"])


def _out(p: Project, role: str, favs: set[uuid.UUID]) -> ProjectOut:
    return ProjectOut(
        id=p.id,
        team_id=p.team_id,
        name=p.name,
        color=p.color,
        privacy=p.privacy,
        default_view=p.default_view,
        status=p.status,
        archived_at=p.archived_at,
        owner_id=p.owner_id,
        my_role=role,
        is_favorite=p.id in favs,
        version=p.version,
    )


async def _detail(s: AsyncSession, ctx: Ctx, p: Project, role: str) -> ProjectDetailOut:
    favs = await service.favorite_ids(s, ctx)
    members = [
        ProjectMemberOut(user=UserOut.model_validate(u), role=r)
        for u, r in await service.project_members(s, p.id)
    ]
    sections = [SectionBrief.model_validate(x) for x in await service.project_sections(s, p.id)]
    return ProjectDetailOut(
        **_out(p, role, favs).model_dump(),
        team_name=await service.team_name(s, p.team_id),
        members=members,
        sections=sections,
    )


def _meta(m: Mutation[Project]) -> MutationMeta:
    return MutationMeta(activity_id=m.activity_id, version=m.version)


@router.get("", response_model=ListOut[ProjectOut], summary="Projects I can see")
async def list_projects(
    ctx: CtxDep,
    uow: UowDep,
    team_id: uuid.UUID | None = None,
    archived: bool = Query(default=False),
) -> ListOut[ProjectOut]:
    async with uow.transaction() as s:
        projects = await service.list_projects(s, ctx, team_id=team_id, archived=archived)
        favs = await service.favorite_ids(s, ctx)
        out = []
        for p in projects:
            role = await project_role(s, ctx, p)
            if role is not None:
                out.append(_out(p, role, favs))
        return ListOut(data=out)


@router.post(
    "",
    response_model=MutationOut[ProjectDetailOut],
    status_code=status.HTTP_201_CREATED,
    summary="Create a project in a team",
)
async def create_project(
    body: ProjectCreateIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[ProjectDetailOut]:
    async with uow.transaction() as s:
        m = await service.create_project(s, ctx, body)
        detail = await _detail(s, ctx, m.entity, "admin")
    return MutationOut(data=detail, meta=_meta(m))


@router.get(
    "/{project_id}", response_model=ProjectDetailOut, summary="Project with members and sections"
)
async def get_project(project_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> ProjectDetailOut:
    async with uow.transaction() as s:
        p, role = await service.get_project(s, ctx, project_id)
        return await _detail(s, ctx, p, role)


@router.patch("/{project_id}", response_model=MutationOut[ProjectOut], summary="Edit a project")
async def patch_project(
    project_id: uuid.UUID, body: ProjectPatchIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[ProjectOut]:
    async with uow.transaction() as s:
        m = await service.update_project(s, ctx, project_id, body)
        _, role = await service.get_project(s, ctx, project_id)
        out = _out(m.entity, role, await service.favorite_ids(s, ctx))
    return MutationOut(data=out, meta=_meta(m))


async def _archive(
    project_id: uuid.UUID, ctx: Ctx, uow: UowDep, flag: bool
) -> MutationOut[ProjectOut]:
    async with uow.transaction() as s:
        m = await service.set_archived(s, ctx, project_id, flag)
        _, role = await service.get_project(s, ctx, project_id)
        out = _out(m.entity, role, await service.favorite_ids(s, ctx))
    return MutationOut(data=out, meta=_meta(m))


@router.post("/{project_id}/archive", response_model=MutationOut[ProjectOut], summary="Archive")
async def archive(project_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> MutationOut[ProjectOut]:
    return await _archive(project_id, ctx, uow, True)


@router.post("/{project_id}/unarchive", response_model=MutationOut[ProjectOut], summary="Unarchive")
async def unarchive(project_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> MutationOut[ProjectOut]:
    return await _archive(project_id, ctx, uow, False)


@router.delete("/{project_id}", response_model=MutationOut[OkOut], summary="Delete (soft)")
async def delete_project(project_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await service.delete_project(s, ctx, project_id)
    return MutationOut(data=OkOut(), meta=_meta(m))


@favorites_router.get(
    "", response_model=ListOut[ProjectOut], summary="My starred projects, in order"
)
async def list_favorites(ctx: CtxDep, uow: UowDep) -> ListOut[ProjectOut]:
    async with uow.transaction() as s:
        projects = await service.list_favorites(s, ctx)
        out = []
        for p in projects:
            role = await project_role(s, ctx, p)
            if role is not None:
                out.append(_out(p, role, {x.id for x in projects}))
        return ListOut(data=out)


@favorites_router.put(
    "/projects/{project_id}",
    response_model=OkOut,
    summary="Star a project or move it among favorites",
)
async def put_favorite(
    project_id: uuid.UUID, ctx: CtxDep, uow: UowDep, body: FavoriteIn | None = None
) -> OkOut:
    async with uow.transaction() as s:
        await service.set_favorite(
            s,
            ctx,
            project_id,
            after_id=body.after_id if body else None,
            before_id=body.before_id if body else None,
        )
    return OkOut()


@favorites_router.delete("/projects/{project_id}", response_model=OkOut, summary="Unstar")
async def delete_favorite(project_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> OkOut:
    async with uow.transaction() as s:
        await service.unset_favorite(s, ctx, project_id)
    return OkOut()
