"""Background tasks. Defined on a Blueprint so no global Procrastinate app exists at import."""

from __future__ import annotations

import procrastinate

from momentum.core.telemetry import get_logger

blueprint = procrastinate.Blueprint()
log = get_logger("jobs")


@blueprint.periodic(cron="*/5 * * * *", periodic_id="heartbeat")
@blueprint.task(name="heartbeat", queue="momentum_maintenance", queueing_lock="heartbeat")
async def heartbeat(timestamp: int) -> None:
    log.info("worker_heartbeat", timestamp=timestamp)
