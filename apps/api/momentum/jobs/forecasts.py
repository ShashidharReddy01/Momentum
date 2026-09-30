"""Nightly project forecasts (S6.5.3): a fresh Monte Carlo forecast and risk score for every
active project. ``MOMENTUM_FORECASTS_ENABLED=false`` switches it off (the kill switch); forecasts
can still be refreshed from a project's overview."""

from __future__ import annotations

from momentum.core.settings import Settings
from momentum.jobs.tasks import blueprint, log


@blueprint.periodic(cron="30 2 * * *", periodic_id="compute_forecasts")
@blueprint.task(
    name="compute_forecasts", queue="momentum_maintenance", queueing_lock="compute_forecasts"
)
async def compute_forecasts(timestamp: int) -> None:
    from momentum.domain.forecasts.service import run_all
    from momentum.jobs.db import job_session

    settings = Settings()
    if not settings.forecasts_enabled:
        return
    async with job_session() as session:
        n = await run_all(session, settings)
    log.info("forecasts_computed", projects=n, timestamp=timestamp)
