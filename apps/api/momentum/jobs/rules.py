"""Rules executor job (S4.1.1)."""

from __future__ import annotations

from momentum.core.settings import Settings
from momentum.jobs.tasks import blueprint, log


@blueprint.periodic(cron="* * * * *", periodic_id="run_rules")
@blueprint.task(name="run_rules", queue="momentum_default", queueing_lock="run_rules")
async def run_rules_job(timestamp: int) -> None:
    """Fire the rules that match new outbox events: an outbox consumer run."""
    from momentum.domain.rules.engine import run_rules
    from momentum.jobs.db import job_session

    settings = Settings()
    async with job_session() as session:
        stats = await run_rules(session, settings)
    if stats.success or stats.skipped or stats.failed:
        log.info(
            "rules_ran",
            events=stats.events,
            success=stats.success,
            skipped=stats.skipped,
            failed=stats.failed,
            timestamp=timestamp,
        )
