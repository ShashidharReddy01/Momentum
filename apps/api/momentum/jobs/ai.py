"""AI maintenance jobs (S3.1.3)."""

from __future__ import annotations

from momentum.jobs.tasks import blueprint, log


@blueprint.periodic(cron="*/15 * * * *", periodic_id="expire_ai_actions")
@blueprint.task(
    name="expire_ai_actions", queue="momentum_maintenance", queueing_lock="expire_ai_actions"
)
async def expire_ai_actions(timestamp: int) -> None:
    """Mark AI proposals past their 24 h window expired (reads also expire them lazily)."""
    from momentum.ai.actions import expire_actions
    from momentum.jobs.db import job_session

    async with job_session() as session:
        n = await expire_actions(session)
    log.info("ai_actions_expired", count=n, timestamp=timestamp)


@blueprint.periodic(cron="* * * * *", periodic_id="index_embeddings")
@blueprint.task(name="index_embeddings", queue="momentum_ai", queueing_lock="index_embeddings")
async def index_embeddings(timestamp: int) -> None:
    """Keep the embeddings index in step with changes (S3.1.4): an outbox consumer run."""
    from momentum.ai.embeddings import index_changes
    from momentum.jobs.db import job_llm, job_session

    async with job_session() as session:
        run = await index_changes(session, job_llm())
    if run.events or run.stopped:
        log.info(
            "embeddings_indexed",
            events=run.events,
            entities=run.entities,
            chunks=run.chunks,
            stopped=run.stopped,
            timestamp=timestamp,
        )
