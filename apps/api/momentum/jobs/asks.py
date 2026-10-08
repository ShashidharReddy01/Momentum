"""Phase 7.6 S76-03 (spec §5.4): reminders and expiry for agents' questions."""

from __future__ import annotations

from datetime import UTC, datetime

from momentum.jobs.tasks import blueprint, log


@blueprint.periodic(cron="*/5 * * * *", periodic_id="ask_timers")
@blueprint.task(name="ask_timers", queue="momentum_maintenance", queueing_lock="ask_timers")
async def ask_timers(timestamp: int) -> None:
    """Remind people of open asks and apply each expired ask's default (which may wake its job)."""
    from momentum.core.settings import Settings
    from momentum.domain.asks.service import ask_timers as run_timers
    from momentum.jobs.db import job_session

    settings = Settings()
    async with job_session() as session:
        stats = await run_timers(session, settings, datetime.fromtimestamp(timestamp, UTC))
    if stats["reminded"] or stats["expired"]:
        log.info("ask_timers", timestamp=timestamp, **stats)
