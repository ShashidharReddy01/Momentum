"""Application factory (standalone) and mount helper (embedded in a host app).

See docs/architecture/embedding-and-portability.md.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from starlette.middleware.gzip import GZipMiddleware

from momentum.api.runtime import MomentumRuntime, RealtimeState
from momentum.api.system import VERSION, config_router, health_router
from momentum.auth.base import HostPrincipalResolver
from momentum.auth.factory import build_auth_provider
from momentum.core.db import create_engine, create_session_factory
from momentum.core.http import (
    CsrfMiddleware,
    RequestIdMiddleware,
    install_error_handlers,
)
from momentum.core.settings import Settings
from momentum.core.telemetry import configure_logging, get_logger

API_PREFIX = "/api/v1"
CSRF_EXEMPT = ("/api/v1/public/", "/webhooks/")


def _api_router(settings: Settings) -> APIRouter:
    from momentum.api.undo import router as undo_router
    from momentum.domain.attachments.router import router as attachments_router
    from momentum.domain.comments.router import router as comments_router
    from momentum.domain.fields.router import router as fields_router
    from momentum.domain.home.router import router as home_router
    from momentum.domain.mytasks.router import router as mytasks_router
    from momentum.domain.notifications.router import router as notifications_router
    from momentum.domain.projects.router import favorites_router
    from momentum.domain.projects.router import router as projects_router
    from momentum.domain.search.router import router as search_router
    from momentum.domain.sections.router import router as sections_router
    from momentum.domain.tags.router import router as tags_router
    from momentum.domain.tasks.router import router as tasks_router
    from momentum.domain.teams.router import router as teams_router
    from momentum.domain.users.router import dev_router
    from momentum.domain.users.router import router as users_router

    api = APIRouter(prefix=API_PREFIX)
    api.include_router(config_router)
    api.include_router(users_router)
    api.include_router(teams_router)
    api.include_router(projects_router)
    api.include_router(favorites_router)
    api.include_router(sections_router)
    api.include_router(tasks_router)
    api.include_router(comments_router)
    api.include_router(attachments_router)
    api.include_router(fields_router)
    api.include_router(tags_router)
    api.include_router(mytasks_router)
    api.include_router(notifications_router)
    api.include_router(home_router)
    api.include_router(search_router)
    api.include_router(undo_router)
    if settings.is_dev_auth:
        api.include_router(dev_router)
    return api


def create_app(
    settings: Settings | None = None,
    *,
    resolve_principal: HostPrincipalResolver | None = None,
) -> FastAPI:
    """Build the Momentum ASGI app. Nothing is connected until the lifespan starts."""
    settings = settings or Settings()
    configure_logging(settings)
    log = get_logger("app")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        runtime = MomentumRuntime(
            settings=settings,
            engine=engine,
            session_factory=create_session_factory(engine),
            auth=build_auth_provider(settings, resolve_principal),
        )
        app.state.momentum = runtime
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
    app.add_middleware(RequestIdMiddleware)
    # Large lists (e.g. 2,000 tasks ≈ 0.9 MB of JSON) compress ~8x; App Service containers
    # don't compress for us.
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)
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
        settings.model_copy(update={"serve_spa": False}), resolve_principal=resolve_principal
    )
    host_app.mount(settings.base_path, sub)
    host_app.state.momentum_subapp = sub
    return sub


@asynccontextmanager
async def momentum_lifespan(sub_app: FastAPI) -> AsyncIterator[None]:
    """Run a mounted Momentum sub-app's lifespan from the host's lifespan."""
    async with sub_app.router.lifespan_context(sub_app):
        yield
