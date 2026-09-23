"""Momentum command line: ``momentum --help``."""

from __future__ import annotations

import asyncio
import os

import typer

from momentum.core.settings import Settings

cli = typer.Typer(no_args_is_help=True, add_completion=False, help="Momentum operations CLI")


@cli.command()
def serve(
    host: str = "0.0.0.0",  # noqa: S104 - container entrypoint
    port: int = typer.Option(int(os.environ.get("PORT", "8000"))),
    reload: bool = False,
    workers: int = 1,
) -> None:
    """Run the web app (API + SPA + embedded worker)."""
    import uvicorn

    uvicorn.run(
        "momentum.asgi:app",
        host=host,
        port=port,
        reload=reload,
        workers=None if reload else workers,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


@cli.command()
def worker() -> None:
    """Run a standalone background worker (WORKER_MODE=separate)."""
    from momentum.jobs.app import QUEUES, build_job_app

    settings = Settings()

    async def _run() -> None:
        app = build_job_app(settings)
        async with app.open_async():
            await app.run_worker_async(queues=QUEUES, concurrency=settings.worker_concurrency)

    asyncio.run(_run())


@cli.command()
def migrate(revision: str = "head") -> None:
    """Apply database migrations (in MOMENTUM_DB_SCHEMA)."""
    from alembic import command

    from momentum.migrations_runner import alembic_config

    command.upgrade(alembic_config(Settings()), revision)


@cli.command()
def seed() -> None:
    """Load the synthetic demo workspace (safe to re-run)."""
    from momentum.core.db import UnitOfWork, create_engine, create_session_factory
    from momentum.seed import seed as run_seed

    settings = Settings()

    async def _run() -> dict[str, int]:
        engine = create_engine(settings)
        uow = UnitOfWork(create_session_factory(engine)())
        try:
            async with uow.transaction() as session:
                return await run_seed(session, settings)
        finally:
            await uow.close()
            await engine.dispose()

    typer.echo(asyncio.run(_run()))


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
