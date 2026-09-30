from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.api.deps import CtxDep, UowDep
from momentum.api.schemas import ListOut, MutationMeta, MutationOut, OkOut
from momentum.core.context import Ctx
from momentum.core.mutation import Mutation
from momentum.domain.portfolios import service
from momentum.domain.portfolios.models import Portfolio
from momentum.domain.portfolios.schemas import (
    PortfolioDetailOut,
    PortfolioIn,
    PortfolioItemIn,
    PortfolioOut,
    PortfolioPatchIn,
    PortfolioProjectRow,
    PortfolioStatusDraftOut,
)
from momentum.domain.status_updates.router import update_out
from momentum.domain.status_updates.schemas import StatusUpdateIn, StatusUpdateOut

router = APIRouter(prefix="/portfolios", tags=["portfolios"])


def _out(ctx: Ctx, p: Portfolio, count: int) -> PortfolioOut:
    return PortfolioOut(
        id=p.id,
        name=p.name,
        description=p.description,
        owner_id=p.owner_id,
        status=p.status,
        version=p.version,
        can_edit=service.can_edit(ctx, p),
        project_count=count,
        created_at=p.created_at,
    )


async def _detail(s: AsyncSession, ctx: Ctx, p: Portfolio) -> PortfolioDetailOut:
    rows, hidden = await service.portfolio_rows(s, ctx, p)
    return PortfolioDetailOut(
        **_out(ctx, p, len(rows)).model_dump(),
        projects=[
            PortfolioProjectRow(
                id=x.id,
                name=x.name,
                color=x.color,
                owner_id=x.owner_id,
                status=x.status,
                start_on=x.start_on,
                due_on=x.due_on,
                **facts,
            )
            for x, facts in rows
        ],
        hidden_projects=hidden,
    )


def _meta(m: Mutation[Portfolio]) -> MutationMeta:
    return MutationMeta(activity_id=m.activity_id, version=m.version)


@router.get("", response_model=ListOut[PortfolioOut], summary="Portfolios in this workspace")
async def list_portfolios(ctx: CtxDep, uow: UowDep) -> ListOut[PortfolioOut]:
    async with uow.transaction() as s:
        return ListOut(data=[_out(ctx, p, n) for p, n in await service.list_portfolios(s, ctx)])


@router.post(
    "",
    response_model=MutationOut[PortfolioDetailOut],
    status_code=status.HTTP_201_CREATED,
    summary="Create a portfolio",
)
async def create_portfolio(
    body: PortfolioIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[PortfolioDetailOut]:
    async with uow.transaction() as s:
        m = await service.create_portfolio(s, ctx, body)
        return MutationOut(data=await _detail(s, ctx, m.entity), meta=_meta(m))


@router.get(
    "/{portfolio_id}", response_model=PortfolioDetailOut, summary="A portfolio and its projects"
)
async def get_portfolio(portfolio_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> PortfolioDetailOut:
    async with uow.transaction() as s:
        return await _detail(s, ctx, await service.get_portfolio(s, ctx, portfolio_id))


@router.patch(
    "/{portfolio_id}", response_model=MutationOut[PortfolioDetailOut], summary="Rename or describe"
)
async def update_portfolio(
    portfolio_id: uuid.UUID, body: PortfolioPatchIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[PortfolioDetailOut]:
    async with uow.transaction() as s:
        m = await service.update_portfolio(s, ctx, portfolio_id, body)
        return MutationOut(data=await _detail(s, ctx, m.entity), meta=_meta(m))


@router.delete("/{portfolio_id}", response_model=MutationOut[OkOut], summary="Delete (undoable)")
async def delete_portfolio(portfolio_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await service.delete_portfolio(s, ctx, portfolio_id)
        return MutationOut(data=OkOut(), meta=_meta(m))


@router.post(
    "/{portfolio_id}/projects",
    response_model=MutationOut[PortfolioDetailOut],
    status_code=status.HTTP_201_CREATED,
    summary="Add a project you can see",
)
async def add_project(
    portfolio_id: uuid.UUID, body: PortfolioItemIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[PortfolioDetailOut]:
    async with uow.transaction() as s:
        m = await service.add_project(s, ctx, portfolio_id, body.project_id)
        return MutationOut(data=await _detail(s, ctx, m.entity), meta=_meta(m))


@router.delete(
    "/{portfolio_id}/projects/{project_id}",
    response_model=MutationOut[PortfolioDetailOut],
    summary="Remove a project",
)
async def remove_project(
    portfolio_id: uuid.UUID, project_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> MutationOut[PortfolioDetailOut]:
    async with uow.transaction() as s:
        m = await service.remove_project(s, ctx, portfolio_id, project_id)
        return MutationOut(data=await _detail(s, ctx, m.entity), meta=_meta(m))


@router.get(
    "/{portfolio_id}/status-draft",
    response_model=PortfolioStatusDraftOut,
    summary="A check-in drafted from the projects' statuses (nothing is saved)",
)
async def status_draft(
    portfolio_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> PortfolioStatusDraftOut:
    async with uow.transaction() as s:
        return PortfolioStatusDraftOut(draft=await service.draft_status(s, ctx, portfolio_id))


@router.get(
    "/{portfolio_id}/status-updates",
    response_model=ListOut[StatusUpdateOut],
    summary="A portfolio's status updates, newest first",
)
async def list_statuses(
    portfolio_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> ListOut[StatusUpdateOut]:
    async with uow.transaction() as s:
        rows = await service.list_statuses(s, ctx, portfolio_id)
        return ListOut(data=[await update_out(s, ctx, u) for u in rows])


@router.post(
    "/{portfolio_id}/status-updates",
    response_model=MutationOut[StatusUpdateOut],
    status_code=status.HTTP_201_CREATED,
    summary="Post a portfolio check-in (sets its status; undoable)",
)
async def post_status(
    portfolio_id: uuid.UUID, body: StatusUpdateIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[StatusUpdateOut]:
    async with uow.transaction() as s:
        m = await service.post_status(s, ctx, portfolio_id, body)
        await s.refresh(m.entity)
        return MutationOut(
            data=await update_out(s, ctx, m.entity),
            meta=MutationMeta(activity_id=m.activity_id, version=m.version),
        )
