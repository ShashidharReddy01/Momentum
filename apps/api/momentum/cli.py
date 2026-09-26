"""Momentum command line: ``momentum --help``."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Coroutine
from typing import Any

import typer

from momentum.core.settings import Settings

cli = typer.Typer(no_args_is_help=True, add_completion=False, help="Momentum operations CLI")

# psycopg's async mode can't run on Windows' default Proactor loop; use the selector loop there.
WINDOWS = sys.platform == "win32"


def run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop if WINDOWS else None)


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
        loop="asyncio:SelectorEventLoop" if WINDOWS else "auto",
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

    run_async(_run())


@cli.command()
def migrate(revision: str = "head") -> None:
    """Apply database migrations (in MOMENTUM_DB_SCHEMA)."""
    from alembic import command

    from momentum.migrations_runner import alembic_config

    command.upgrade(alembic_config(Settings()), revision)


@cli.command()
def seed(
    perf: bool = typer.Option(False, "--perf", help="Also add a 2,000-task project (performance)"),
) -> None:
    """Load the synthetic demo workspace (safe to re-run)."""
    from momentum.core.db import UnitOfWork, create_engine, create_session_factory
    from momentum.seed import seed as run_seed
    from momentum.seed import seed_perf

    settings = Settings()

    async def _run() -> dict[str, int]:
        engine = create_engine(settings)
        uow = UnitOfWork(create_session_factory(engine)())
        try:
            async with uow.transaction() as session:
                if perf:
                    return await seed_perf(session, settings)
                return await run_seed(session, settings)
        finally:
            await uow.close()
            await engine.dispose()

    typer.echo(run_async(_run()))


@cli.command()
def reindex(
    entity: list[str] = typer.Option(
        [], "--entity", help="task, comment, attachment or project (repeatable); default: all"
    ),
    since: str = typer.Option("", help="Only entities changed on/after this date (YYYY-MM-DD)"),
) -> None:
    """Rebuild the AI search index (embeddings). Unchanged content is skipped (S3.1.4)."""
    from datetime import UTC, datetime

    from momentum.ai.embeddings import INDEXED
    from momentum.ai.embeddings import reindex as run_reindex
    from momentum.ai.llm import build_llm
    from momentum.ai.usage import DbUsageLog
    from momentum.core.db import create_engine, create_session_factory

    kinds = entity or list(INDEXED)
    unknown = [k for k in kinds if k not in INDEXED]
    if unknown:
        raise typer.BadParameter(f"unknown entity type(s): {', '.join(unknown)}")
    start = datetime.fromisoformat(since).replace(tzinfo=UTC) if since else None
    settings = Settings()

    async def _run() -> str:
        engine = create_engine(settings)
        factory = create_session_factory(engine)
        llm = build_llm(settings, DbUsageLog(factory, settings.ai_monthly_budget_usd))
        try:
            async with factory() as session, session.begin():
                run = await run_reindex(session, llm, entity_types=kinds, since=start)  # type: ignore[arg-type]
        finally:
            await llm.aclose()
            await engine.dispose()
        return f"Indexed {run.entities} entities ({run.chunks} chunks re-embedded)"

    typer.echo(run_async(_run()))


@cli.command("llm-check")
def llm_check() -> None:
    """Verify the LLM gateway: chat, tool calls, streaming, embeddings, latency (S3.1.1)."""
    from momentum.ai.check import recommendations, render, run_llm_check
    from momentum.ai.llm import build_llm
    from momentum.core.telemetry import configure_logging

    settings = Settings()
    configure_logging(settings)
    if settings.llm_mode == "mock":
        header = (
            "Mode: mock (canned fixtures, no network). This checks the plumbing only; set "
            "MOMENTUM_LLM_MODE=gateway to check a real gateway."
        )
    else:
        header = f"Mode: {settings.llm_mode} · gateway {settings.llm_base_url}"
    aliases = (
        f"Aliases: fast={settings.llm_model_fast} · default={settings.llm_model_default} · "
        f"smart={settings.llm_model_smart} · embed={settings.llm_embed_model} "
        f"(dim {settings.llm_embed_dim})"
    )

    async def _run() -> tuple[str, bool]:
        # llm-check probes the gateway, so the master switch doesn't apply here.
        llm = build_llm(settings.model_copy(update={"ai_enabled": True}))
        try:
            results = await run_llm_check(llm)
        finally:
            await llm.aclose()
        text = render(results, recommendations(results), header=f"{header}\n{aliases}")
        return text, any(r.status == "fail" for r in results)

    text, failed = run_async(_run())
    typer.echo(text)
    if failed:
        raise typer.Exit(code=1)


@cli.command()
def evals(
    live: bool = typer.Option(
        False, "--live", help="Call the configured gateway (default: mock fixtures only)"
    ),
    feature: list[str] = typer.Option([], "--feature", help="Only these features (repeatable)"),
    case: str = typer.Option("", "--case", help="Only cases whose id contains this"),
    report_dir: str = typer.Option("reports/evals", help="Where to write the JSON report"),
    all_cases: bool = typer.Option(
        False, "--all", help="Mock mode: also run the live-only cases (a plumbing check)"
    ),
) -> None:
    """Run the AI evals on a throwaway *_evals database (S3.5.1). Exit code 1 on failure."""
    from pathlib import Path

    from momentum.ai.evals import main as evals_main

    ok = run_async(
        evals_main.run(
            Settings(),
            live=live or os.environ.get("EVALS_LIVE") == "1",
            features=feature,
            case=case or None,
            report_dir=Path(report_dir),
            echo=typer.echo,
            all_cases=all_cases,
        )
    )
    if not ok:
        raise typer.Exit(code=1)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
