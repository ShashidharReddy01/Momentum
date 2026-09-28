"""S5.1.1: install agents from definition files (Momentum's starters plus any host directories
passed to ``create_app``). Same service as ``momentum agents install``."""

from __future__ import annotations

from fastapi import APIRouter

from momentum.agents.loader import DefinitionError, load_definitions
from momentum.api.deps import CtxDep, RuntimeDep, UowDep
from momentum.core.errors import ValidationFailed
from momentum.domain.agents import service
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
