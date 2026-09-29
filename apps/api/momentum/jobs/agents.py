"""Agent jobs (S5.1.2): turn triggers into queued runs, and run queued runs."""

from __future__ import annotations

from datetime import UTC, datetime

from momentum.jobs.tasks import blueprint, log


@blueprint.periodic(cron="* * * * *", periodic_id="agent_triggers")
@blueprint.task(name="agent_triggers", queue="momentum_default", queueing_lock="agent_triggers")
async def agent_triggers(timestamp: int) -> None:
    """Queue this minute's scheduled runs and the runs new outbox events call for."""
    from momentum.agents.triggers import consume_events, evaluate_schedules
    from momentum.core.settings import Settings
    from momentum.jobs.db import job_session

    settings = Settings()
    async with job_session() as session:
        scheduled = await evaluate_schedules(
            session, settings, datetime.fromtimestamp(timestamp, UTC)
        )
        events = await consume_events(session, settings)
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
    its own, so one slow agent never holds another's writes."""
    from momentum.agents.runtime import execute_run
    from momentum.ai.tools.catalog import build_registry
    from momentum.core.settings import Settings
    from momentum.domain.agents.runs import claim_runs
    from momentum.jobs.db import job_llm, job_session

    settings = Settings()
    if not settings.agents_enabled:
        return
    async with job_session() as session:
        claimed = await claim_runs(session, timeout_s=settings.agent_timeout_s)
    registry = build_registry()
    counts: dict[str, int] = {}
    for run_id in claimed.run_ids:
        async with job_session() as session:
            status = await execute_run(session, job_llm(), registry, settings, run_id)
        counts[status] = counts.get(status, 0) + 1
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
