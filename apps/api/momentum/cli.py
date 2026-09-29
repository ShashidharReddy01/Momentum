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

    # The report carries model text (translations, symbols); a legacy console codepage
    # (Windows cp1252) must not crash the summary after a paid run.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(errors="replace")

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


agents_cli = typer.Typer(no_args_is_help=True, help="Agents: install and inspect (Phase 5)")
cli.add_typer(agents_cli, name="agents")


@agents_cli.command("install")
def agents_install(
    only: list[str] = typer.Option([], "--only", help="Only these agent keys (repeatable)"),
    force: bool = typer.Option(
        False, "--force", help="Overwrite agents an admin has edited since they were installed"
    ),
    definitions_dir: list[str] = typer.Option(
        [], "--definitions-dir", help="A host application's own definitions (repeatable)"
    ),
) -> None:
    """Install or refresh agents from their definitions. New agents start disabled; an admin
    enables each one. Safe to re-run: unchanged agents are left alone, edited ones are reported
    as drifted and kept (unless --force)."""
    from momentum.agents.extensions import load_extensions
    from momentum.agents.loader import DefinitionError, load_definitions
    from momentum.ai.tools.catalog import build_registry
    from momentum.core.context import Actor, Ctx
    from momentum.core.db import UnitOfWork, create_engine, create_session_factory
    from momentum.domain.agents.service import install_definitions
    from momentum.domain.workspace.service import ensure_default_workspace

    settings = Settings()
    ext = load_extensions(settings)  # MOMENTUM_AGENT_EXTENSIONS (S5.1.5)
    try:
        definitions = load_definitions([*definitions_dir, *ext.definition_dirs])
    except DefinitionError as e:
        raise typer.BadParameter(str(e)) from e

    async def _run() -> list[str]:
        engine = create_engine(settings)
        uow = UnitOfWork(create_session_factory(engine)())
        try:
            async with uow.transaction() as session:
                ws = await ensure_default_workspace(session, settings)
                # the operator running the CLI acts as the system, with admin rights
                ctx = Ctx(
                    actor=Actor(id=None, workspace_id=ws.id, role="admin"),
                    settings=settings,
                    via="system",
                )
                results = await install_definitions(
                    session,
                    ctx,
                    definitions,
                    build_registry(*ext.tools).names,
                    keys=only or None,
                    force=force,
                )
                return [f"{r.outcome:<10} {r.key}  ({r.agent.name})" for r in results]
        finally:
            await uow.close()
            await engine.dispose()

    for line in run_async(_run()):
        typer.echo(line)


@agents_cli.command("list")
def agents_list() -> None:
    """The workspace's agents: key, enabled, autonomy, monthly budget."""
    from sqlalchemy import select

    from momentum.core.db import create_engine, create_session_factory
    from momentum.domain.agents.models import Agent
    from momentum.domain.agents.service import is_drifted

    settings = Settings()

    async def _run() -> list[str]:
        engine = create_engine(settings)
        try:
            async with create_session_factory(engine)() as session:
                rows = (await session.execute(select(Agent).order_by(Agent.key))).scalars()
                return [
                    f"{a.key:<18} {'on ' if a.enabled else 'off'}  {a.autonomy:<8} "
                    f"${a.budget_monthly_usd}/mo  {a.source}{'  (edited)' if is_drifted(a) else ''}"
                    for a in rows
                ]
        finally:
            await engine.dispose()

    lines = run_async(_run())
    typer.echo("\n".join(lines) if lines else "No agents installed. Run: momentum agents install")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
