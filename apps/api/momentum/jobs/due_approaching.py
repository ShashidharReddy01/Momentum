"""Due-approaching scan job (S4.1.2): feeds the rules executor's ``task.due_approaching``."""

from __future__ import annotations

from momentum.core.settings import Settings
from momentum.jobs.tasks import blueprint, log


@blueprint.periodic(cron="0 * * * *", periodic_id="scan_due_approaching")
@blueprint.task(
    name="scan_due_approaching", queue="momentum_maintenance", queueing_lock="scan_due_approaching"
)
async def scan_due_approaching_job(timestamp: int) -> None:
    from momentum.domain.rules.due_scan import scan_due_approaching
    from momentum.jobs.db import job_session

    settings = Settings()
    async with job_session() as session:
        emitted = await scan_due_approaching(session, settings)
    if emitted:
        log.info("due_approaching_scanned", emitted=emitted, timestamp=timestamp)
