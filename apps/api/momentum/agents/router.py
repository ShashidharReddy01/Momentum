"""S5.1.1: install agents from definition files (Momentum's starters plus any host directories
passed to ``create_app``). Same service as ``momentum agents install``."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field

from momentum.agents.loader import DefinitionError, load_definitions
from momentum.agents.triggers import request_run
from momentum.api.deps import CtxDep, RuntimeDep, UowDep
from momentum.core.errors import ValidationFailed
from momentum.domain.agents import service
from momentum.domain.agents.models import AgentRun
from momentum.domain.agents.schemas import InstallIn, InstallOut, InstallRowOut

router = APIRouter(tags=["agents"])


@router.post(
    "/agents/install",
    response_model=InstallOut,
    summary="Install or refresh agents from their definitions; new ones start disabled (admins)",
)
async def install_agents(
    body: InstallIn, ctx: CtxDep, uow: UowDep, runtime: RuntimeDep
) -> InstallOut:
    try:
        definitions = load_definitions(runtime.agent_definition_dirs)
    except DefinitionError as e:
        raise ValidationFailed(str(e)) from e
    async with uow.transaction() as s:
        results = await service.install_definitions(
            s, ctx, definitions, runtime.tools.names, keys=body.keys, force=body.force
        )
        return InstallOut(
            results=[
                InstallRowOut(key=r.key, outcome=r.outcome, agent_id=r.agent.id) for r in results
            ]
        )


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    text: str | None = Field(default=None, max_length=20_000)


class RunQueuedOut(BaseModel):
    run_id: uuid.UUID
    status: str


@router.post(
    "/agents/{agent_id}/run",
    response_model=RunQueuedOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run an agent now, on a task or project you can see; it starts within a minute",
)
async def run_agent(agent_id: uuid.UUID, body: RunIn, ctx: CtxDep, uow: UowDep) -> RunQueuedOut:
    async with uow.transaction() as s:
        agent = await service.get_agent(s, ctx, agent_id)
        run_id = await request_run(
            s, ctx, agent, task_id=body.task_id, project_id=body.project_id, text=body.text
        )
        run = await s.get(AgentRun, run_id)
        return RunQueuedOut(run_id=run_id, status=run.status if run else "queued")
