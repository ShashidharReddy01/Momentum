"""Procrastinate job queue, stored in the Momentum schema (ADR-0002)."""

from __future__ import annotations

import procrastinate

from momentum.core.settings import Settings
from momentum.jobs import attachments as _attachments  # noqa: F401 - registers `extract_text`
from momentum.jobs.tasks import blueprint

# Queue names are prefixed so they never collide with a host app using Procrastinate too.
QUEUES = [
    "momentum_default",
    "momentum_ai",
    "momentum_integrations",
    "momentum_maintenance",
]


def build_job_app(settings: Settings) -> procrastinate.App:
    connector = procrastinate.PsycopgConnector(
        conninfo=settings.psycopg_conninfo,
        kwargs={"options": f"-c search_path={settings.search_path}"},
        min_size=1,
        max_size=4,
    )
    app = procrastinate.App(connector=connector)
    app.add_tasks_from(blueprint, namespace="momentum")
    return app
