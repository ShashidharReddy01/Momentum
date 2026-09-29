"""S5.1.1: agents admin API. Installing from definition files is ``momentum/agents/router.py``
(it reads the definitions, which the domain layer doesn't import)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from momentum.api.deps import CtxDep, RuntimeDep, UowDep
from momentum.api.schemas import ListOut, MutationMeta, MutationOut, OkOut
from momentum.core.mutation import Mutation
from momentum.domain.agents import service
from momentum.domain.agents.models import Agent
from momentum.domain.agents.schemas import (
    AgentDetailOut,
    AgentIn,
    AgentOut,
    AgentPatchIn,
    AgentProjectIn,
    AgentProjectOut,
    AgentStatsOut,
)
from momentum.domain.agents.stats import agent_stats
from momentum.domain.users import tokens as token_service
from momentum.domain.users.models import User
from momentum.domain.users.schemas import ApiTokenCreatedOut, ApiTokenIn, ApiTokenOut

router = APIRouter(tags=["agents"])


def agent_out(agent: Agent) -> AgentOut:
    return AgentOut.model_validate(agent).model_copy(update={"drifted": service.is_drifted(agent)})


def _mutation(m: Mutation[Agent]) -> MutationOut[AgentOut]:
    return MutationOut(
        data=agent_out(m.entity),
        meta=MutationMeta(activity_id=m.activity_id, batch_id=m.batch_id, version=m.version),
    )


@router.get("/agents", response_model=ListOut[AgentOut], summary="All agents in the workspace")
async def list_agents(ctx: CtxDep, uow: UowDep) -> ListOut[AgentOut]:
    async with uow.transaction() as s:
        return ListOut(data=[agent_out(a) for a in await service.list_agents(s, ctx)])


@router.post(
    "/agents",
    response_model=MutationOut[AgentOut],
    status_code=status.HTTP_201_CREATED,
    summary="Create a custom agent, disabled until enabled (workspace admins)",
)
async def create_agent(
    body: AgentIn, ctx: CtxDep, uow: UowDep, runtime: RuntimeDep
) -> MutationOut[AgentOut]:
    async with uow.transaction() as s:
        return _mutation(await service.create_agent(s, ctx, body, runtime.tools.names))


@router.get(
    "/agents/{agent_id}",
    response_model=AgentDetailOut,
    summary="One agent, with the projects it has access to that you can see",
)
async def get_agent(agent_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> AgentDetailOut:
    async with uow.transaction() as s:
        agent = await service.get_agent(s, ctx, agent_id)
        projects = await service.agent_projects(s, ctx, agent)
        return AgentDetailOut(
            **agent_out(agent).model_dump(),
            projects=[AgentProjectOut(id=p.id, name=p.name, role=role) for p, role in projects],
        )


@router.patch(
    "/agents/{agent_id}",
    response_model=MutationOut[AgentOut],
    summary="Edit, enable or disable an agent (workspace admins)",
)
async def patch_agent(
    agent_id: uuid.UUID, body: AgentPatchIn, ctx: CtxDep, uow: UowDep, runtime: RuntimeDep
) -> MutationOut[AgentOut]:
    async with uow.transaction() as s:
        return _mutation(await service.update_agent(s, ctx, agent_id, body, runtime.tools.names))


@router.post(
    "/agents/{agent_id}/projects",
    response_model=MutationOut[OkOut],
    status_code=status.HTTP_201_CREATED,
    summary="Give an agent access to a project (needs admin on that project, like sharing)",
)
async def add_agent_project(
    agent_id: uuid.UUID, body: AgentProjectIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await service.add_to_project(s, ctx, agent_id, body.project_id, body.role)
    return MutationOut(data=OkOut(), meta=MutationMeta(activity_id=m.activity_id))


@router.delete(
    "/agents/{agent_id}/projects/{project_id}",
    response_model=MutationOut[OkOut],
    summary="Remove an agent's access to a project",
)
async def remove_agent_project(
    agent_id: uuid.UUID, project_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await service.remove_from_project(s, ctx, agent_id, project_id)
    return MutationOut(data=OkOut(), meta=MutationMeta(activity_id=m.activity_id))


@router.get(
    "/agents/{agent_id}/stats",
    response_model=AgentStatsOut,
    summary="An agent's track record (for promotion to auto) and this month's spend (admins)",
)
async def get_agent_stats(
    agent_id: uuid.UUID, ctx: CtxDep, uow: UowDep, runtime: RuntimeDep
) -> AgentStatsOut:
    async with uow.transaction() as s:
        agent = await service.get_agent_for_admin(s, ctx, agent_id)
        stats = await agent_stats(s, agent)
    llm = runtime.llm
    priced = llm is not None and not llm.prices.unpriced([llm.model_for(agent.model_alias)])
    return AgentStatsOut(
        decided=stats.decided,
        accepted=stats.accepted,
        acceptance_rate=stats.acceptance_rate,
        undos_14d=stats.undos_14d,
        auto_applied_7d=stats.auto_applied_7d,
        auto_undone_7d=stats.auto_undone_7d,
        eligible_for_auto=stats.eligible_for_auto,
        reasons=stats.reasons,
        month_usd=stats.month_usd,
        month_tokens=stats.month_tokens,
        priced=priced,
    )


@router.get(
    "/agents/{agent_id}/tokens",
    response_model=ListOut[ApiTokenOut],
    summary="API tokens that act as this agent (admins)",
)
async def list_agent_tokens(agent_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> ListOut[ApiTokenOut]:
    async with uow.transaction() as s:
        agent = await service.get_agent_for_admin(s, ctx, agent_id)
        rows = await token_service.list_tokens(s, ctx, agent.user_id)
        return ListOut(data=[ApiTokenOut.model_validate(t) for t in rows])


@router.post(
    "/agents/{agent_id}/tokens",
    response_model=ApiTokenCreatedOut,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a token so an external script acts as this agent (admins; secret shown once)",
)
async def create_agent_token(
    agent_id: uuid.UUID, body: ApiTokenIn, ctx: CtxDep, uow: UowDep
) -> ApiTokenCreatedOut:
    async with uow.transaction() as s:
        agent = await service.get_agent_for_admin(s, ctx, agent_id)
        account = await s.get(User, agent.user_id)
        assert account is not None
        m, secret = await token_service.create_token(
            s,
            ctx,
            name=body.name,
            scopes=body.scopes,
            expires_in_days=body.expires_in_days,
            for_user=account,
        )
        return ApiTokenCreatedOut(data=ApiTokenOut.model_validate(m.entity), secret=secret)
