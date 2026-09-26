from __future__ import annotations

import httpx
from fastapi import APIRouter

from momentum.api.deps import CtxDep, RuntimeDep, UowDep
from momentum.core.errors import ValidationFailed
from momentum.core.permissions import Action, require
from momentum.integrations.asana_import.client import AsanaClient
from momentum.integrations.asana_import.schemas import AsanaImportIn, ImportJobOut
from momentum.integrations.asana_import.service import run_import

router = APIRouter(tags=["integrations"])


@router.post(
    "/integrations/asana/import",
    response_model=ImportJobOut,
    summary="Import a team's projects/tasks from Asana (synchronous; the PAT is never stored)",
)
async def import_from_asana(
    body: AsanaImportIn, ctx: CtxDep, uow: UowDep, rt: RuntimeDep
) -> ImportJobOut:
    require(ctx, Action.TEAM_CREATE)
    client = AsanaClient(body.pat, base_url=rt.settings.asana_base_url)
    try:
        async with uow.transaction() as s:
            job = await run_import(
                s,
                ctx,
                client,
                workspace_gid=body.workspace_gid,
                team_gid=body.team_gid,
                team_name=body.team_name,
                project_gids=body.project_gids,
            )
            return ImportJobOut.model_validate(job)
    except httpx.HTTPError as e:
        raise ValidationFailed(f"Couldn't reach Asana: {e}", code="asana_error") from e
    finally:
        await client.aclose()
