"""Schedule-based recurrence scan (S4.4.2): spawns the next instance of every due
`recurrence.mode == "on_schedule"` task. `on_complete` tasks spawn synchronously on completion
instead and never touch this job."""

from __future__ import annotations

from momentum.core.settings import Settings
from momentum.jobs.tasks import blueprint, log


@blueprint.periodic(cron="0 1 * * *", periodic_id="scan_scheduled_recurrences")
@blueprint.task(
    name="scan_scheduled_recurrences",
    queue="momentum_maintenance",
    queueing_lock="scan_scheduled_recurrences",
)
async def scan_scheduled_recurrences_job(timestamp: int) -> None:
    from momentum.domain.tasks.recurrence_scan import scan_scheduled_recurrences
    from momentum.jobs.db import job_session

    settings = Settings()
    async with job_session() as session:
        spawned = await scan_scheduled_recurrences(session, settings)
    if spawned:
        log.info("scheduled_recurrences_spawned", spawned=spawned, timestamp=timestamp)
