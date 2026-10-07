"""Phase 7.5 (spec §6.3): running a report run outside the request that asked for it (the job),
or right after it when there is no job worker (``worker_mode=off``: tests, a bare dev server)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Actor, Ctx
from momentum.core.settings import Settings
from momentum.core.storage import build_storage
from momentum.domain.reports.models import ReportRun
from momentum.domain.reports.service import execute
from momentum.domain.users.models import User
from momentum.reports.narrative import Narrator


def requester_ctx(user: User, settings: Settings, run: ReportRun) -> Ctx:
    """The requester's own context: the report sees exactly what they see."""
    return Ctx(
        actor=Actor(
            id=user.id,
            workspace_id=user.workspace_id,
            role=user.role,
            is_agent=user.is_agent,
            email=user.email,
            name=user.name,
            timezone=user.timezone,
        ),
        settings=settings,
        via="ai" if run.created_via == "ai" else "ui",
        request_id=f"report:{run.id}",
    )


async def run_report(
    session: AsyncSession, settings: Settings, run_id: uuid.UUID, narrator: Narrator | None
) -> ReportRun | None:
    run = (
        await session.execute(select(ReportRun).where(ReportRun.id == run_id).with_for_update())
    ).scalar_one_or_none()
    if run is None or run.status not in ("queued",):
        return run
    user = await session.get(User, run.requested_by)
    if user is None or user.status != "active":
        run.status, run.error = "failed", "The person who asked for this report is no longer active"
        return run
    return await execute(
        session,
        requester_ctx(user, settings, run),
        run,
        storage=build_storage(settings),
        narrator=narrator,
        timeout_s=settings.report_timeout_s,
    )
