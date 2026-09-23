from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.api.deps import CtxDep, UowDep
from momentum.api.schemas import ListOut, MutationMeta, MutationOut, OkOut
from momentum.core.context import Ctx
from momentum.domain.teams import service
from momentum.domain.teams.models import Team
from momentum.domain.teams.schemas import (
    TeamCreateIn,
    TeamDetailOut,
    TeamMemberIn,
    TeamMemberOut,
    TeamMemberPatchIn,
    TeamOut,
    TeamPatchIn,
)
from momentum.domain.users.schemas import UserOut

router = APIRouter(prefix="/teams", tags=["teams"])


async def _out(session: AsyncSession, ctx: Ctx, team: Team) -> TeamOut:
    role, n = await service.team_summary(session, ctx, team)
    return TeamOut(
        id=team.id,
        name=team.name,
        description=team.description,
        color=team.color,
        my_role=role,
        member_count=n,
        version=team.version,
    )


async def _detail(session: AsyncSession, ctx: Ctx, team: Team) -> TeamDetailOut:
    base = await _out(session, ctx, team)
    members = [
        TeamMemberOut(user=UserOut.model_validate(u), role=r)
        for u, r in await service.list_members(session, team.id)
    ]
    return TeamDetailOut(**base.model_dump(), members=members)


@router.get("", response_model=ListOut[TeamOut], summary="Teams I belong to (admins: all)")
async def list_teams(ctx: CtxDep, uow: UowDep) -> ListOut[TeamOut]:
    async with uow.transaction() as s:
        rows = await service.list_teams(s, ctx)
        return ListOut(
            data=[
                TeamOut(
                    id=t.id,
                    name=t.name,
                    description=t.description,
                    color=t.color,
                    my_role=r,
                    member_count=n,
                    version=t.version,
                )
                for t, r, n in rows
            ]
        )


@router.post(
    "",
    response_model=MutationOut[TeamDetailOut],
    status_code=status.HTTP_201_CREATED,
    summary="Create a team (you become its lead)",
)
async def create_team(body: TeamCreateIn, ctx: CtxDep, uow: UowDep) -> MutationOut[TeamDetailOut]:
    async with uow.transaction() as s:
        m = await service.create_team(s, ctx, body)
        detail = await _detail(s, ctx, m.entity)
    return MutationOut(data=detail, meta=MutationMeta(activity_id=m.activity_id, version=m.version))


@router.get("/{team_id}", response_model=TeamDetailOut, summary="Team with members")
async def get_team(team_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> TeamDetailOut:
    async with uow.transaction() as s:
        return await _detail(s, ctx, await service.get_team(s, ctx, team_id))


@router.patch("/{team_id}", response_model=MutationOut[TeamOut], summary="Rename / edit a team")
async def patch_team(
    team_id: uuid.UUID, body: TeamPatchIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[TeamOut]:
    async with uow.transaction() as s:
        m = await service.update_team(s, ctx, team_id, body)
        out = await _out(s, ctx, m.entity)
    return MutationOut(data=out, meta=MutationMeta(activity_id=m.activity_id, version=m.version))


@router.delete("/{team_id}", response_model=MutationOut[OkOut], summary="Delete a team (soft)")
async def delete_team(team_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await service.delete_team(s, ctx, team_id)
    return MutationOut(data=OkOut(), meta=MutationMeta(activity_id=m.activity_id))


@router.post(
    "/{team_id}/members",
    response_model=MutationOut[OkOut],
    status_code=status.HTTP_201_CREATED,
    summary="Add a member",
)
async def add_member(
    team_id: uuid.UUID, body: TeamMemberIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await service.add_member(s, ctx, team_id, body.user_id, body.role)
    return MutationOut(data=OkOut(), meta=MutationMeta(activity_id=m.activity_id))


@router.patch(
    "/{team_id}/members/{user_id}",
    response_model=MutationOut[OkOut],
    summary="Change a member's role",
)
async def set_role(
    team_id: uuid.UUID, user_id: uuid.UUID, body: TeamMemberPatchIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await service.set_member_role(s, ctx, team_id, user_id, body.role)
    return MutationOut(data=OkOut(), meta=MutationMeta(activity_id=m.activity_id))


@router.delete(
    "/{team_id}/members/{user_id}",
    response_model=MutationOut[OkOut],
    summary="Remove a member (or leave)",
)
async def remove_member(
    team_id: uuid.UUID, user_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await service.remove_member(s, ctx, team_id, user_id)
    return MutationOut(data=OkOut(), meta=MutationMeta(activity_id=m.activity_id))
