"""S2.7.1 / S7.4.2: Asana import endpoints. The token is sent with each call that talks to Asana
and is never stored (see ``engine.py``): browse (``discover``), create a job (dry run or real),
then call ``step`` until the job is done; each step works for up to ~40 s."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter

from momentum.api.deps import CtxDep, RuntimeDep, UowDep
from momentum.api.schemas import ListOut
from momentum.core.errors import ValidationFailed
from momentum.core.permissions import Action, require
from momentum.core.settings import Settings
from momentum.core.storage import build_storage
from momentum.integrations.asana_import import service
from momentum.integrations.asana_import.client import AsanaClient
from momentum.integrations.asana_import.schemas import (
    AsanaDiscoverIn,
    AsanaDiscoverOut,
    AsanaImportIn,
    AsanaJobIn,
    AsanaStepIn,
    AsanaThing,
    ImportJobOut,
)

router = APIRouter(tags=["integrations"])


@asynccontextmanager
async def _asana(pat: str, settings: Settings) -> AsyncIterator[AsanaClient]:
    client = AsanaClient(pat, base_url=settings.asana_base_url)
    try:
        yield client
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        reason = (
            "Asana didn't accept the token (check it, or make a new one)"
            if code in (401, 403)
            else f"Asana answered {code}"
        )
        raise ValidationFailed(reason, code="asana_error") from e
    except httpx.HTTPError as e:
        raise ValidationFailed(
            f"Couldn't reach Asana: {type(e).__name__}", code="asana_error"
        ) from e
    finally:
        await client.aclose()


def _things(rows: list[dict[str, object]]) -> list[AsanaThing]:
    return [
        AsanaThing(
            gid=str(r["gid"]), name=str(r.get("name") or ""), archived=bool(r.get("archived"))
        )
        for r in rows
    ]


@router.post(
    "/integrations/asana/discover",
    response_model=AsanaDiscoverOut,
    summary="Browse Asana: workspaces, then a workspace's teams, then a team's projects",
)
async def discover(body: AsanaDiscoverIn, ctx: CtxDep, rt: RuntimeDep) -> AsanaDiscoverOut:
    require(ctx, Action.TEAM_CREATE)
    async with _asana(body.pat, rt.settings) as asana:
        workspaces = _things(await asana.workspaces())
        teams = _things(await asana.teams(body.workspace_gid)) if body.workspace_gid else []
        projects = (
            _things(await asana.projects(body.team_gid, include_archived=True))
            if body.team_gid
            else []
        )
    return AsanaDiscoverOut(workspaces=workspaces, teams=teams, projects=projects)


@router.post(
    "/integrations/asana/imports",
    response_model=ImportJobOut,
    status_code=201,
    summary="Plan an import (or a dry run); then call its step endpoint until it's done",
)
async def create_import(body: AsanaJobIn, ctx: CtxDep, uow: UowDep) -> ImportJobOut:
    require(ctx, Action.TEAM_CREATE)
    async with uow.transaction() as s:
        job = await service.start_import(
            s,
            ctx,
            workspace_gid=body.workspace_gid,
            team_gid=body.team_gid,
            team_name=body.team_name,
            project_gids=body.project_gids,
            dry_run=body.dry_run,
            invite_unmatched=body.invite_unmatched,
        )
        return ImportJobOut.of(job)


@router.get(
    "/integrations/asana/imports",
    response_model=ListOut[ImportJobOut],
    summary="Recent Asana imports (yours; every one for an admin)",
)
async def list_imports(ctx: CtxDep, uow: UowDep) -> ListOut[ImportJobOut]:
    async with uow.transaction() as s:
        return ListOut(data=[ImportJobOut.of(j) for j in await service.list_jobs(s, ctx)])


@router.get(
    "/integrations/asana/imports/{job_id}", response_model=ImportJobOut, summary="An import"
)
async def get_import(job_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> ImportJobOut:
    async with uow.transaction() as s:
        return ImportJobOut.of(await service.get_job(s, ctx, job_id))


@router.post(
    "/integrations/asana/imports/{job_id}/step",
    response_model=ImportJobOut,
    summary="Run the import for up to ~40 s (send the token each time; it's never stored)",
)
async def step_import(
    job_id: uuid.UUID, body: AsanaStepIn, ctx: CtxDep, uow: UowDep, rt: RuntimeDep
) -> ImportJobOut:
    require(ctx, Action.TEAM_CREATE)
    async with _asana(body.pat, rt.settings) as asana, uow.transaction() as s:
        job = await service.step(
            s,
            ctx,
            asana,
            job_id,
            storage=build_storage(rt.settings),
            max_upload_bytes=rt.settings.max_upload_mb * 1024 * 1024,
        )
        return ImportJobOut.of(job)


@router.post(
    "/integrations/asana/import",
    response_model=ImportJobOut,
    summary="Import a team in one request (small imports; larger ones use /imports + steps)",
)
async def import_from_asana(
    body: AsanaImportIn, ctx: CtxDep, uow: UowDep, rt: RuntimeDep
) -> ImportJobOut:
    require(ctx, Action.TEAM_CREATE)
    async with _asana(body.pat, rt.settings) as asana, uow.transaction() as s:
        job = await service.run_import(
            s,
            ctx,
            asana,
            workspace_gid=body.workspace_gid,
            team_gid=body.team_gid,
            team_name=body.team_name,
            project_gids=body.project_gids,
            storage=build_storage(rt.settings),
            max_upload_bytes=rt.settings.max_upload_mb * 1024 * 1024,
        )
        return ImportJobOut.of(job)
