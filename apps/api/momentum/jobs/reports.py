"""Phase 7.5 (spec §6.3): the report job. Each run is generated as its requester, with the
worker's gateway for the narrative, capped by ``MOMENTUM_REPORT_TIMEOUT_S``."""

from __future__ import annotations

import uuid

from momentum.jobs.tasks import blueprint, log


@blueprint.task(name="generate_report", queue="momentum_default")
async def generate_report(run_id: str) -> None:
    from momentum.ai.report_narrative import make_narrator
    from momentum.core.settings import Settings
    from momentum.domain.reports.runner import run_report
    from momentum.jobs.db import job_llm, job_session

    settings = Settings()
    async with job_session() as session:
        run = await run_report(
            session, settings, uuid.UUID(run_id), make_narrator(job_llm(), settings)
        )
    if run is not None:
        log.info("report_generated", run_id=run_id, status=run.status)
