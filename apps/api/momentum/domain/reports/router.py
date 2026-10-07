"""Phase 7.5 (spec §6.3): ``POST /reports/preview``, ``POST /reports``, ``GET /reports/jobs/{id}``,
``POST /attachments/{id}/regenerate``."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.api.deps import CtxDep, RuntimeDep, UowDep
from momentum.api.runtime import MomentumRuntime
from momentum.core.activity import Activity
from momentum.domain.attachments.models import Attachment
from momentum.domain.reports import service
from momentum.domain.reports.models import ReportRun
from momentum.domain.reports.runner import run_report
from momentum.domain.reports.schemas import ReportIn, ReportPreviewOut, ReportRunOut

router = APIRouter(tags=["reports"])


async def _out(s: AsyncSession, run: ReportRun) -> ReportRunOut:
    att = await s.get(Attachment, run.attachment_id) if run.attachment_id else None
    activity = None
    if att is not None:
        activity = (
            await s.execute(
                select(Activity.id)
                .where(
                    Activity.entity_type == "attachment",
                    Activity.entity_id == att.id,
                    Activity.verb == "report.generated",
                )
                .limit(1)
            )
        ).scalar_one_or_none()
    return ReportRunOut(
        id=run.id,
        kind=run.kind,
        status=run.status,
        attachment_id=run.attachment_id,
        filename=att.filename if att else None,
        project_id=att.project_id if att else None,
        portfolio_id=att.portfolio_id if att else None,
        error=run.error,
        activity_id=activity,
        created_at=run.created_at,
        finished_at=run.finished_at,
    )


async def _start(runtime: MomentumRuntime, uow: UowDep, run_id: uuid.UUID) -> None:
    """Queue the run for the worker, or (no worker) run it now in its own transaction."""
    job_app = runtime.extras.get("job_app")
    if job_app is not None:
        task = (
            job_app.tasks.get("momentum:generate_report")
            or job_app.tasks["momentum.generate_report"]
        )
        await task.defer_async(run_id=str(run_id))
        return
    async with uow.transaction() as s:
        await run_report(s, runtime.settings, run_id, runtime.report_narrator)


@router.post(
    "/reports/preview",
    response_model=ReportPreviewOut,
    summary="What a report would hold (an outline and its length), as you; no file",
)
async def preview(body: ReportIn, ctx: CtxDep, uow: UowDep) -> ReportPreviewOut:
    async with uow.transaction() as s:
        return ReportPreviewOut.model_validate(await service.preview(s, ctx, body.spec))


@router.post(
    "/reports",
    response_model=ReportRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Make a report (a job; poll GET /reports/jobs/{id})",
)
async def create_report(
    body: ReportIn, ctx: CtxDep, uow: UowDep, runtime: RuntimeDep
) -> ReportRunOut:
    async with uow.transaction() as s:
        run = await service.request_report(s, ctx, body.spec)
        run_id = run.id
    await _start(runtime, uow, run_id)
    async with uow.transaction() as s:
        return await _out(s, await service.get_run(s, ctx, run_id))


@router.get("/reports/jobs/{run_id}", response_model=ReportRunOut, summary="A report job")
async def get_job(run_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> ReportRunOut:
    async with uow.transaction() as s:
        return await _out(s, await service.get_run(s, ctx, run_id))


@router.post(
    "/attachments/{attachment_id}/regenerate",
    response_model=ReportRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run a generated report's spec again, as a new version of the file",
)
async def regenerate(
    attachment_id: uuid.UUID, ctx: CtxDep, uow: UowDep, runtime: RuntimeDep
) -> ReportRunOut:
    async with uow.transaction() as s:
        run, _att = await service.regenerate(s, ctx, attachment_id)
        run_id = run.id
    await _start(runtime, uow, run_id)
    async with uow.transaction() as s:
        return await _out(s, await service.get_run(s, ctx, run_id))
