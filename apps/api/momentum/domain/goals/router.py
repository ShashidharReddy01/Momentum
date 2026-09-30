from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, status
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.api.deps import CtxDep, UowDep
from momentum.api.schemas import ListOut, MutationMeta, MutationOut, OkOut
from momentum.core.context import Ctx
from momentum.core.mutation import Mutation
from momentum.domain.goals import service
from momentum.domain.goals.models import Goal
from momentum.domain.goals.schemas import (
    GoalCheckInIn,
    GoalDetailOut,
    GoalIn,
    GoalLinkIn,
    GoalLinkOut,
    GoalMetric,
    GoalOut,
    GoalPatchIn,
)
from momentum.domain.status_updates.router import update_out
from momentum.domain.status_updates.schemas import StatusUpdateOut

router = APIRouter(prefix="/goals", tags=["goals"])


def _out(ctx: Ctx, g: Goal, progress: service.Progress) -> GoalOut:
    return GoalOut(
        id=g.id,
        name=g.name,
        description=g.description,
        owner_id=g.owner_id,
        parent_id=g.parent_id,
        period_start=g.period_start,
        period_end=g.period_end,
        period_label=g.period_label,
        metric=GoalMetric.model_validate(g.metric) if g.metric else None,
        progress_source=g.progress_source,
        status=g.status,
        version=g.version,
        can_edit=service.can_edit(ctx, g),
        progress=progress.by_goal.get(g.id),
        created_at=g.created_at,
    )


async def _detail(s: AsyncSession, ctx: Ctx, g: Goal) -> GoalDetailOut:
    progress = await service.compute_progress(s, ctx)
    goals, _ = await service.list_goals(s, ctx)
    links, hidden = await service.link_views(s, ctx, g, progress)
    return GoalDetailOut(
        **_out(ctx, g, progress).model_dump(),
        links=[GoalLinkOut(**x) for x in links],
        hidden_links=hidden,
        children=[_out(ctx, c, progress) for c in goals if c.parent_id == g.id],
    )


def _meta(m: Mutation[Goal]) -> MutationMeta:
    return MutationMeta(activity_id=m.activity_id, version=m.version)


@router.get("", response_model=ListOut[GoalOut], summary="Every goal, with progress for you")
async def list_goals(ctx: CtxDep, uow: UowDep) -> ListOut[GoalOut]:
    async with uow.transaction() as s:
        goals, progress = await service.list_goals(s, ctx)
        return ListOut(data=[_out(ctx, g, progress) for g in goals])


@router.post(
    "",
    response_model=MutationOut[GoalDetailOut],
    status_code=status.HTTP_201_CREATED,
    summary="Create a goal",
)
async def create_goal(body: GoalIn, ctx: CtxDep, uow: UowDep) -> MutationOut[GoalDetailOut]:
    async with uow.transaction() as s:
        m = await service.create_goal(s, ctx, body)
        return MutationOut(data=await _detail(s, ctx, m.entity), meta=_meta(m))


@router.get("/{goal_id}", response_model=GoalDetailOut, summary="A goal, its links and sub-goals")
async def get_goal(goal_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> GoalDetailOut:
    async with uow.transaction() as s:
        return await _detail(s, ctx, await service.get_goal(s, ctx, goal_id))


@router.patch("/{goal_id}", response_model=MutationOut[GoalDetailOut], summary="Edit a goal")
async def update_goal(
    goal_id: uuid.UUID, body: GoalPatchIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[GoalDetailOut]:
    async with uow.transaction() as s:
        m = await service.update_goal(s, ctx, goal_id, body)
        return MutationOut(data=await _detail(s, ctx, m.entity), meta=_meta(m))


@router.delete("/{goal_id}", response_model=MutationOut[OkOut], summary="Delete a goal (undoable)")
async def delete_goal(goal_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await service.delete_goal(s, ctx, goal_id)
        return MutationOut(data=OkOut(), meta=_meta(m))


@router.post(
    "/{goal_id}/links",
    response_model=MutationOut[GoalDetailOut],
    status_code=status.HTTP_201_CREATED,
    summary="Link a project or portfolio that moves this goal",
)
async def link(
    goal_id: uuid.UUID, body: GoalLinkIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[GoalDetailOut]:
    async with uow.transaction() as s:
        m = await service.link(s, ctx, goal_id, body.entity_type, body.entity_id)
        return MutationOut(data=await _detail(s, ctx, m.entity), meta=_meta(m))


@router.delete(
    "/{goal_id}/links/{entity_type}/{entity_id}",
    response_model=MutationOut[GoalDetailOut],
    summary="Unlink a project or portfolio",
)
async def unlink(
    goal_id: uuid.UUID,
    entity_type: Literal["project", "portfolio"],
    entity_id: uuid.UUID,
    ctx: CtxDep,
    uow: UowDep,
) -> MutationOut[GoalDetailOut]:
    async with uow.transaction() as s:
        m = await service.unlink(s, ctx, goal_id, entity_type, entity_id)
        return MutationOut(data=await _detail(s, ctx, m.entity), meta=_meta(m))


@router.get(
    "/{goal_id}/check-ins",
    response_model=ListOut[StatusUpdateOut],
    summary="A goal's check-ins, newest first",
)
async def list_check_ins(goal_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> ListOut[StatusUpdateOut]:
    async with uow.transaction() as s:
        return ListOut(
            data=[
                await update_out(s, ctx, u) for u in await service.list_check_ins(s, ctx, goal_id)
            ]
        )


@router.post(
    "/{goal_id}/check-ins",
    response_model=MutationOut[StatusUpdateOut],
    status_code=status.HTTP_201_CREATED,
    summary="Check in: status, notes, and optionally the metric's new value (undoable)",
)
async def check_in(
    goal_id: uuid.UUID, body: GoalCheckInIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[StatusUpdateOut]:
    async with uow.transaction() as s:
        m = await service.check_in(s, ctx, goal_id, body)
        await s.refresh(m.entity)
        return MutationOut(
            data=await update_out(s, ctx, m.entity),
            meta=MutationMeta(activity_id=m.activity_id, version=m.version),
        )
