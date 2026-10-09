"""Agent jobs (S5.1.2): turn triggers into queued runs, and run queued runs."""

from __future__ import annotations

from datetime import UTC, datetime

from momentum.jobs.tasks import blueprint, log


@blueprint.periodic(cron="* * * * *", periodic_id="agent_triggers")
@blueprint.task(name="agent_triggers", queue="momentum_default", queueing_lock="agent_triggers")
async def agent_triggers(timestamp: int) -> None:
    """Queue this minute's scheduled runs and the runs new outbox events call for, and resume the
    jobs waiting for an event (Phase 7.6)."""
    from momentum.agents.jobs.engine import wake_on_events
    from momentum.agents.packs.registry import PackRegistry
    from momentum.agents.triggers import consume_events, evaluate_schedules
    from momentum.core.settings import Settings
    from momentum.jobs.db import job_session

    settings = Settings()
    packs = PackRegistry.load(settings)
    async with job_session() as session:
        scheduled = await evaluate_schedules(
            session, settings, datetime.fromtimestamp(timestamp, UTC), packs=packs
        )
        events = await consume_events(session, settings, packs=packs)
        woken = await wake_on_events(session, settings)
    if woken:
        log.info("agent_jobs_woken", by_events=woken, timestamp=timestamp)
    if scheduled.queued or events.queued:
        log.info(
            "agent_runs_queued",
            scheduled=scheduled.queued,
            from_events=events.queued,
            timestamp=timestamp,
        )


@blueprint.periodic(cron="* * * * *", periodic_id="run_agent_runs")
@blueprint.task(name="run_agent_runs", queue="momentum_ai", queueing_lock="run_agent_runs")
async def run_agent_runs(timestamp: int) -> None:
    """Run queued agent runs. Claiming and running are separate transactions, and each run gets
    its own, so one slow agent never holds another's writes. A pack's durable job (Phase 7.6)
    runs one pass through the job engine, each of its steps in its own transaction."""
    from momentum.agents.extensions import load_extensions
    from momentum.agents.jobs.engine import execute_job, tick_jobs
    from momentum.agents.packs.registry import PackRegistry
    from momentum.agents.runtime import execute_run
    from momentum.ai.tools.catalog import build_registry
    from momentum.core.settings import Settings
    from momentum.domain.agents.runs import claim_runs
    from momentum.jobs.db import job_llm, job_session

    settings = Settings()
    if not settings.agents_enabled:
        return
    async with job_session() as session:
        ticked = await tick_jobs(session, settings)
    async with job_session() as session:
        claimed = await claim_runs(
            session, timeout_s=settings.agent_timeout_s, packs_enabled=settings.packs_enabled
        )
    ext = load_extensions(settings)  # a host's tools and handler agents (S5.1.5)
    registry = build_registry(*ext.tools)
    packs = PackRegistry.load(settings) if claimed.jobs else None
    counts: dict[str, int] = {}
    for run_id in claimed.run_ids:
        if run_id in claimed.jobs:
            status = await execute_job(job_session, job_llm(), settings, packs, run_id)
        else:
            async with job_session() as session:
                status = await execute_run(
                    session, job_llm(), registry, settings, run_id, handlers=ext.handlers
                )
        counts[status] = counts.get(status, 0) + 1
    if ticked.woken or ticked.expired or ticked.requeued or ticked.failed:
        log.info(
            "agent_jobs_ticked",
            woken=ticked.woken,
            expired=ticked.expired,
            requeued=ticked.requeued,
            failed=ticked.failed,
            timestamp=timestamp,
        )
    if claimed.run_ids or claimed.timed_out:
        log.info("agent_runs_ran", timed_out=claimed.timed_out, timestamp=timestamp, **counts)


@blueprint.periodic(cron="20 3 * * *", periodic_id="demote_agents")
@blueprint.task(name="demote_agents", queue="momentum_maintenance", queueing_lock="demote_agents")
async def demote_agents(timestamp: int) -> None:
    """Daily: agents at `auto` whose changes were undone too often this week go back to
    `confirm` (S5.1.4)."""
    from momentum.agents.autonomy import run_demotions
    from momentum.core.settings import Settings
    from momentum.jobs.db import job_session

    async with job_session() as session:
        run = await run_demotions(session, Settings())
    if run.demoted:
        log.info("agents_demoted", agents=run.demoted, timestamp=timestamp)
