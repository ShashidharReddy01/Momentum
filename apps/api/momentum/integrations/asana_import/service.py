"""The Asana importer's entry points (S2.7.1, rebuilt for S7.4.2: the full import).

The work itself is ``engine.py``: an import is a job whose queue of small steps lives in its own
``import_jobs`` row, so it runs in steps of ~40 s that each take the token from the caller and
never store it. This module creates jobs, finds them, and runs them (one step, or to the end).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.core.errors import Conflict, Forbidden, NotFound
from momentum.core.storage import StorageBackend
from momentum.domain.integrations.models import ImportJob
from momentum.integrations.asana_import.engine import Source, new_job, run_all, run_step

RECENT_JOBS = 20


async def start_import(
    session: AsyncSession,
    ctx: Ctx,
    *,
    workspace_gid: str,
    team_gid: str,
    team_name: str,
    project_gids: list[str] | None,
    dry_run: bool,
    invite_unmatched: bool = True,
) -> ImportJob:
    job = new_job(
        ctx,
        workspace_gid=workspace_gid,
        team_gid=team_gid,
        team_name=team_name,
        project_gids=project_gids,
        dry_run=dry_run,
        invite_unmatched=invite_unmatched,
    )
    session.add(job)
    await session.flush()
    return job


async def get_job(
    session: AsyncSession, ctx: Ctx, job_id: uuid.UUID, *, lock: bool = False
) -> ImportJob:
    """An import job of this workspace, started by the caller (or any job, for an admin). With
    ``lock``, the row is locked for this transaction: two tabs can't step the same job at once."""
    query = select(ImportJob).where(
        ImportJob.id == job_id, ImportJob.workspace_id == ctx.workspace_id
    )
    if lock:
        query = query.with_for_update(nowait=True)
    try:
        job = (await session.execute(query)).scalar_one_or_none()
    except DBAPIError as e:
        raise Conflict("This import is already running a step", code="import_busy") from e
    if job is None or job.source != "asana":
        raise NotFound("Import not found")
    if job.started_by != ctx.actor.id and not ctx.actor.is_admin:
        raise Forbidden("Only the person who started this import (or an admin) can run it")
    return job


async def list_jobs(session: AsyncSession, ctx: Ctx) -> list[ImportJob]:
    query = select(ImportJob).where(
        ImportJob.workspace_id == ctx.workspace_id, ImportJob.source == "asana"
    )
    if not ctx.actor.is_admin:
        query = query.where(ImportJob.started_by == ctx.actor.id)
    rows = await session.execute(query.order_by(ImportJob.created_at.desc()).limit(RECENT_JOBS))
    return list(rows.scalars())


async def step(
    session: AsyncSession,
    ctx: Ctx,
    source: Source,
    job_id: uuid.UUID,
    *,
    storage: StorageBackend | None,
    max_upload_bytes: int,
) -> ImportJob:
    job = await get_job(session, ctx, job_id, lock=True)
    return await run_step(
        session, ctx, source, job, storage=storage, max_upload_bytes=max_upload_bytes
    )


async def run_import(
    session: AsyncSession,
    ctx: Ctx,
    client: Source,
    *,
    workspace_gid: str,
    team_gid: str,
    team_name: str,
    project_gids: list[str] | None = None,
    dry_run: bool = False,
    storage: StorageBackend | None = None,
    max_upload_bytes: int = 50 * 1024 * 1024,
) -> ImportJob:
    """A whole import in one call (small imports, tests and the CLI)."""
    job = await start_import(
        session,
        ctx,
        workspace_gid=workspace_gid,
        team_gid=team_gid,
        team_name=team_name,
        project_gids=project_gids,
        dry_run=dry_run,
    )
    return await run_all(
        session, ctx, client, job, storage=storage, max_upload_bytes=max_upload_bytes
    )
