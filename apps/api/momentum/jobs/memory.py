"""Phase 7.6 S76-05 (spec §7.1-§7.2): entity profiles (nightly) and the daily skills digest."""

from __future__ import annotations

from datetime import UTC, datetime

from momentum.jobs.tasks import blueprint, log


@blueprint.periodic(cron="45 2 * * *", periodic_id="compute_entity_profiles")
@blueprint.task(
    name="compute_entity_profiles",
    queue="momentum_maintenance",
    queueing_lock="compute_entity_profiles",
)
async def compute_entity_profiles(timestamp: int) -> None:
    """Each pack's ``profile`` hook over each entity's approved records."""
    from momentum.agents.packs.profiles import compute_profiles
    from momentum.agents.packs.registry import PackRegistry
    from momentum.core.settings import Settings
    from momentum.jobs.db import job_session

    settings = Settings()
    async with job_session() as session:
        n = await compute_profiles(session, PackRegistry.load(settings))
    if n:
        log.info("entity_profiles", entities=n, timestamp=timestamp)


@blueprint.periodic(cron="30 7 * * *", periodic_id="skill_digest")
@blueprint.task(name="skill_digest", queue="momentum_maintenance", queueing_lock="skill_digest")
async def skill_digest(timestamp: int) -> None:
    """One ``skill_proposed`` line per pack to its stewards (or the admins)."""
    from momentum.core.settings import Settings
    from momentum.domain.skills.service import digest
    from momentum.jobs.db import job_session

    async with job_session() as session:
        sent = await digest(session, Settings(), datetime.fromtimestamp(timestamp, UTC))
    if sent:
        log.info("skill_digest", sent=sent, timestamp=timestamp)
