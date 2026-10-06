"""Nightly project snapshots (Phase 7.5, spec §5.7): one row per live project per day for trend
widgets, at 02:45 after the forecasts (02:30) so today's forecast is in it. Retention 730 days."""

from __future__ import annotations

from momentum.jobs.tasks import blueprint, log


@blueprint.periodic(cron="45 2 * * *", periodic_id="snapshot_projects")
@blueprint.task(
    name="snapshot_projects", queue="momentum_maintenance", queueing_lock="snapshot_projects"
)
async def snapshot_projects(timestamp: int) -> None:
    from momentum.domain.projects.snapshots import snapshot_all
    from momentum.jobs.db import job_session

    async with job_session() as session:
        n = await snapshot_all(session)
    log.info("projects_snapshotted", projects=n, timestamp=timestamp)
