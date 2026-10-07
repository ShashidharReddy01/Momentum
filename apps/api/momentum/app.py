"""Application factory (standalone) and mount helper (embedded in a host app).

See docs/architecture/embedding-and-portability.md.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, FastAPI
from sqlalchemy import text
from starlette.middleware.gzip import GZipMiddleware

from momentum.api.runtime import MomentumRuntime, RealtimeState
from momentum.api.system import VERSION, config_router, health_router
from momentum.auth.base import HostPrincipalResolver
from momentum.auth.factory import build_auth_provider
from momentum.core.db import create_engine, create_session_factory
from momentum.core.http import (
    CsrfMiddleware,
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
    StripNulMiddleware,
    install_error_handlers,
)
from momentum.core.settings import Settings
from momentum.core.telemetry import configure_logging, get_logger

if TYPE_CHECKING:
    from momentum.agents.extensions import Extensions

API_PREFIX = "/api/v1"
CSRF_EXEMPT = ("/api/v1/public/", "/webhooks/")


def _api_router(settings: Settings) -> APIRouter:
    from momentum.agents.router import router as agents_install_router
    from momentum.ai.forms_intake_router import public_router as forms_intake_public_router
    from momentum.ai.forms_intake_router import router as forms_intake_router
    from momentum.ai.insight_router import router as ai_insight_router
    from momentum.ai.router import router as ai_router
    from momentum.ai.templates_router import router as ai_templates_router
    from momentum.api.admin import router as admin_router
    from momentum.api.export import router as export_router
    from momentum.api.undo import router as undo_router
    from momentum.domain.agents.router import router as agents_router
    from momentum.domain.attachments.router import router as attachments_router
    from momentum.domain.comments.router import router as comments_router
    from momentum.domain.dashboards.router import router as dashboards_router
    from momentum.domain.fields.router import router as fields_router
    from momentum.domain.forecasts.router import router as forecasts_router
    from momentum.domain.forms.router import public_router as forms_public_router
    from momentum.domain.forms.router import router as forms_router
    from momentum.domain.goals.router import router as goals_router
    from momentum.domain.home.router import router as home_router
    from momentum.domain.mytasks.router import router as mytasks_router
    from momentum.domain.notifications.router import router as notifications_router
    from momentum.domain.portfolios.router import router as portfolios_router
    from momentum.domain.projects.router import favorites_router
    from momentum.domain.projects.router import router as projects_router
    from momentum.domain.reports.router import router as reports_router
    from momentum.domain.rules.router import router as rules_router
    from momentum.domain.search.router import router as search_router
    from momentum.domain.sections.router import router as sections_router
    from momentum.domain.status_updates.router import router as status_updates_router
    from momentum.domain.tags.router import router as tags_router
    from momentum.domain.tasks.csv_import_router import router as csv_import_router
    from momentum.domain.tasks.router import router as tasks_router
    from momentum.domain.teams.router import router as teams_router
    from momentum.domain.templates.router import router as templates_router
    from momentum.domain.users.router import dev_router
    from momentum.domain.users.router import router as users_router
    from momentum.domain.workload.router import router as workload_router
    from momentum.domain.workspace.router import router as workspace_router
    from momentum.integrations.asana_import.router import router as asana_router

    api = APIRouter(prefix=API_PREFIX)
    api.include_router(config_router)
    api.include_router(export_router)
    api.include_router(admin_router)
    api.include_router(users_router)
    api.include_router(workspace_router)
    api.include_router(teams_router)
    api.include_router(projects_router)
    api.include_router(favorites_router)
    api.include_router(sections_router)
    api.include_router(tasks_router)
    api.include_router(csv_import_router)
    api.include_router(comments_router)
    api.include_router(attachments_router)
    api.include_router(fields_router)
    api.include_router(tags_router)
    api.include_router(status_updates_router)
    api.include_router(portfolios_router)
    api.include_router(goals_router)
    api.include_router(workload_router)
    api.include_router(dashboards_router)
    api.include_router(reports_router)
    api.include_router(forecasts_router)
    api.include_router(rules_router)
    api.include_router(forms_router)
    api.include_router(forms_public_router)
    api.include_router(forms_intake_router)
    api.include_router(forms_intake_public_router)
    api.include_router(templates_router)
    api.include_router(mytasks_router)
    api.include_router(notifications_router)
    api.include_router(home_router)
    api.include_router(search_router)
    api.include_router(asana_router)
    api.include_router(undo_router)
    api.include_router(ai_router)
    api.include_router(ai_insight_router)
    api.include_router(ai_templates_router)
    api.include_router(agents_install_router)
    api.include_router(agents_router)
    if settings.is_dev_auth:
        api.include_router(dev_router)
    return api


async def _check_connection_budget(engine: Any, settings: Settings, log: Any) -> None:
    """Warn at startup when this deployment could open more Postgres connections than the
    server allows (Phase 7 load test: 4 web processes with the default pools hit "too many
    clients"). Each process can hold pool + overflow connections, plus the job worker's and
    the realtime listener's. Never blocks startup."""
    per_process = settings.db_pool_size + settings.db_max_overflow + 2
    worst = settings.web_workers * per_process
    try:
        async with engine.connect() as conn:
            limit = int((await conn.execute(text("show max_connections"))).scalar_one())
    except Exception:  # an unreachable or locked-down server: nothing to compare against
        return
    if worst > limit * 0.8:
        log.warning(
            "db_connection_budget",
            web_workers=settings.web_workers,
            per_process=per_process,
            worst_case=worst,
            max_connections=limit,
            hint="lower MOMENTUM_DB_POOL_SIZE / MOMENTUM_DB_MAX_OVERFLOW, or raise max_connections",
        )


def create_app(
    settings: Settings | None = None,
    *,
    resolve_principal: HostPrincipalResolver | None = None,
    agent_definition_dirs: Sequence[str | Path] = (),
    extensions: Extensions | None = None,
) -> FastAPI:
    """Build the Momentum ASGI app. Nothing is connected until the lifespan starts.

    ``agent_definition_dirs`` / ``extensions``: a host application's own agent definitions,
    tools and handler agents (ADR-0009, INTEGRATION_GUIDE §6.7). ``MOMENTUM_AGENT_EXTENSIONS``
    is loaded as well; that setting is how a separate worker process gets them too."""
    from momentum.agents.extensions import Extensions, load_extensions, merge
    from momentum.ai.tools.catalog import build_registry

    settings = settings or Settings()
    ext = merge(
        load_extensions(settings),
        extensions,
        Extensions(definition_dirs=list(agent_definition_dirs)),
    )
    configure_logging(settings)
    log = get_logger("app")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        from momentum.auth.tokens import with_api_tokens

        session_factory = create_session_factory(engine)
        runtime = MomentumRuntime(
            settings=settings,
            engine=engine,
            session_factory=session_factory,
            # S5.1.6: API tokens first, then the deployment's own provider
            auth=with_api_tokens(
                build_auth_provider(settings, resolve_principal), settings, session_factory
            ),
            agent_definition_dirs=tuple(Path(d) for d in ext.definition_dirs),
            tools=build_registry(*ext.tools),
            agent_handlers=dict(ext.handlers),
        )
        app.state.momentum = runtime
        from momentum.ai.llm import build_llm
        from momentum.ai.usage import DbUsageLog

        llm = build_llm(
            settings,
            DbUsageLog(
                runtime.session_factory,
                settings.ai_monthly_budget_usd,
                settings.ai_user_calls_per_hour,
            ),
        )
        runtime.llm = llm
        from momentum.ai.report_narrative import make_narrator

        runtime.report_narrator = make_narrator(llm, settings)
        if settings.db_auto_migrate:
            from momentum.migrations_runner import upgrade_head

            await asyncio.to_thread(upgrade_head, settings)
        listener_task: asyncio.Task[None] | None = None
        if settings.realtime_enabled:
            from momentum.realtime.hub import Hub
            from momentum.realtime.listener import run_listener

            hub = Hub()
            runtime.realtime = RealtimeState(hub=hub)
            listener_task = asyncio.create_task(
                run_listener(settings, runtime.session_factory, hub)
            )
        worker_task: asyncio.Task[None] | None = None
        job_app = None
        # A job app is opened whenever a worker exists anywhere ("embedded" or "separate"),
        # since even a web process running no worker of its own still needs to *defer* jobs
        # (e.g. S2.6.1's text-extraction job) onto the queue a separate worker process reads.
        # Only "off" (tests, by default) skips it entirely — deferring becomes a no-op then.
        if settings.worker_mode != "off":
            from momentum.jobs.app import QUEUES, build_job_app

            job_app = build_job_app(settings)
            await job_app.open_async()
            runtime.extras["job_app"] = job_app
            if settings.worker_mode == "embedded":
                worker_task = asyncio.create_task(
                    job_app.run_worker_async(
                        queues=QUEUES,
                        concurrency=settings.worker_concurrency,
                        install_signal_handlers=False,
                    )
                )
        log.info("momentum_started", env=settings.env, auth=settings.auth_mode, version=VERSION)
        await _check_connection_budget(engine, settings, log)
        try:
            yield
        finally:
            if listener_task is not None:
                listener_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await listener_task
            if worker_task is not None:
                worker_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await worker_task
            if job_app is not None:
                await job_app.close_async()
            await llm.aclose()
            await engine.dispose()

    app = FastAPI(
        title="Momentum",
        version=VERSION,
        lifespan=lifespan,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
    )
    app.add_middleware(CsrfMiddleware, api_prefix=API_PREFIX, exempt_prefixes=CSRF_EXEMPT)
    app.add_middleware(StripNulMiddleware, api_prefix=API_PREFIX)
    app.add_middleware(RequestIdMiddleware)
    # Large lists (e.g. 2,000 tasks ≈ 0.9 MB of JSON) compress ~8x; App Service containers
    # don't compress for us.
    # level 1: half the CPU of level 5 for ~20% more bytes (a 260 KB list: 26 KB in 3.6 ms vs
    # 21 KB in 7.4 ms; Phase 7 load test), and CPU is what runs out first under load
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=1)
    if settings.security_headers:
        app.add_middleware(SecurityHeadersMiddleware, api_prefix=API_PREFIX, settings=settings)
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(_api_router(settings))
    if settings.realtime_enabled:
        from momentum.realtime.router import router as realtime_router

        app.include_router(realtime_router)

    if settings.serve_spa:
        from momentum.web.spa import mount_spa, resolve_spa_dir

        spa_dir = resolve_spa_dir(settings)
        if spa_dir is not None:
            mount_spa(app, spa_dir)
    return app


def mount_momentum(
    host_app: FastAPI,
    *,
    settings: Settings,
    resolve_principal: HostPrincipalResolver | None = None,
    agent_definition_dirs: Sequence[str | Path] = (),
    extensions: Extensions | None = None,
) -> FastAPI:
    """Mount Momentum under ``settings.base_path`` in a host FastAPI app.

    Momentum runs as a sub-application with its own lifespan, middleware and error handlers,
    so the host's configuration is untouched. The host must run the sub-app lifespan; with
    Starlette this happens via ``host_app.router.lifespan_context`` composition, which
    :func:`momentum_lifespan` provides.
    """
    if not settings.base_path:
        raise ValueError("mount_momentum requires settings.base_path (e.g. '/momentum')")
    sub = create_app(
        settings.model_copy(update={"serve_spa": False}),
        resolve_principal=resolve_principal,
        agent_definition_dirs=agent_definition_dirs,
        extensions=extensions,
    )
    host_app.mount(settings.base_path, sub)
    host_app.state.momentum_subapp = sub
    return sub


@asynccontextmanager
async def momentum_lifespan(sub_app: FastAPI) -> AsyncIterator[None]:
    """Run a mounted Momentum sub-app's lifespan from the host's lifespan."""
    async with sub_app.router.lifespan_context(sub_app):
        yield
