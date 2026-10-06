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
    workers: int | None = typer.Option(
        None, help="Web processes (default MOMENTUM_WEB_WORKERS, 1 if unset)"
    ),
) -> None:
    """Run the web app (API + SPA + embedded worker)."""
    import uvicorn

    # S5.0.2: trust X-Forwarded-* only when the deployment says a proxy is in front; otherwise
    # any visitor could set their own address (rate limits use ``api.deps.client_ip``)
    settings = Settings()
    behind_proxy = settings.trusted_proxy_hops > 0
    uvicorn.run(
        "momentum.asgi:app",
        host=host,
        port=port,
        reload=reload,
        workers=None if reload else (workers or settings.web_workers),
        proxy_headers=behind_proxy,
        forwarded_allow_ips="*" if behind_proxy else None,
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
    perf: bool = typer.Option(
        False, "--perf", help="Also add the load-test projects (2k list, 500-task timeline)"
    ),
    history: bool = typer.Option(
        False, "--history", help="Also add ~20 finished projects for the forecast backtest"
    ),
    showcase: bool = typer.Option(
        False, "--showcase", help="Also add a workspace that exercises every screen (UI reviews)"
    ),
    scale: bool = typer.Option(
        False, "--scale", help="Also add the load-test workspace (~150 people, 50k tasks)"
    ),
    onboarding: bool = typer.Option(
        False,
        "--onboarding",
        help="Also add the customer lifecycle demo (template, 40 customers, portfolio; P7.5)",
    ),
    small: bool = typer.Option(
        False, "--small", help="With --onboarding: 12 customers, 30 days of snapshots (e2e, evals)"
    ),
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
                if onboarding:
                    from momentum.seed_onboarding import SMALL_DISTRIBUTION, seed_onboarding

                    if small:
                        return await seed_onboarding(
                            session, settings, distribution=SMALL_DISTRIBUTION, backfill_days=30
                        )
                    return await seed_onboarding(session, settings)
                if scale:
                    from momentum.seed_scale import seed_scale

                    return await seed_scale(session, settings)
                if showcase:
                    from momentum.seed_showcase import seed_showcase

                    return await seed_showcase(session, settings)
                if history:
                    from momentum.seed_history import seed_history

                    return await seed_history(session, settings)
                if perf:
                    return await seed_perf(session, settings)
                return await run_seed(session, settings)
        finally:
            await uow.close()
            await engine.dispose()

    typer.echo(run_async(_run()))


@cli.command("forecast-backtest")
def forecast_backtest(
    runs: int = typer.Option(0, help="Monte Carlo runs per forecast (default: the setting)"),
) -> None:
    """Replay every finished project's forecast from its midpoint (S6.5.3). Pass: 70-90% of
    them finished on or before their P80 date. Seed the history first: seed --history."""
    from momentum.core.db import UnitOfWork, create_engine, create_session_factory
    from momentum.domain.forecasts.backtest import backtest

    settings = Settings()

    async def _run() -> bool:
        engine = create_engine(settings)
        uow = UnitOfWork(create_session_factory(engine)())
        try:
            async with uow.transaction() as session:
                report = await backtest(session, runs=runs or settings.forecast_runs)
        finally:
            await uow.close()
            await engine.dispose()
        for line in report.lines():
            typer.echo(line)
        return report.passed

    if not run_async(_run()):
        raise typer.Exit(1)


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
        llm = build_llm(
            settings,
            DbUsageLog(factory, settings.ai_monthly_budget_usd, settings.ai_user_calls_per_hour),
        )
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


@cli.command("export")
def export_cmd(
    out: str = typer.Option(..., "--out", help="A new directory, or a path ending in .zip"),
    files: bool = typer.Option(False, "--with-files", help="Include every attachment's file"),
) -> None:
    """Export the whole database to a versioned bundle (S7.5.1): every table as JSON lines with
    counts and checksums, ids kept; with --with-files, the stored files too."""
    import tempfile
    from pathlib import Path

    from momentum.core.db import UnitOfWork, create_engine, create_session_factory
    from momentum.core.storage import build_storage
    from momentum.portability import cleanup, export_to, zip_bundle

    settings = Settings()
    target = Path(out)

    async def _run() -> None:
        engine = create_engine(settings)
        try:
            async with UnitOfWork(create_session_factory(engine)()).transaction() as s:
                folder = Path(tempfile.mkdtemp()) / "bundle" if target.suffix == ".zip" else target
                manifest = await export_to(
                    s, folder, storage=build_storage(settings) if files else None, with_files=files
                )
            if target.suffix == ".zip":
                zip_bundle(folder, target)
                cleanup(folder.parent)
            rows = sum(t.rows for t in manifest.tables.values())
            typer.echo(
                f"exported {rows} rows in {len(manifest.tables)} tables"
                f"{f' and {manifest.files} files' if files else ''} at migration "
                f"{manifest.revision} to {target}"
            )
        finally:
            await engine.dispose()

    run_async(_run())


@cli.command("import")
def import_cmd(
    bundle: str = typer.Argument(..., help="A bundle directory or .zip from `momentum export`"),
) -> None:
    """Import a bundle into this empty database (S7.5.1; same migration revision). Every table's
    checksum is verified before anything is committed."""
    from pathlib import Path

    from momentum.core.db import UnitOfWork, create_engine, create_session_factory
    from momentum.core.storage import build_storage
    from momentum.portability import PortabilityError, import_from

    settings = Settings()

    async def _run() -> None:
        engine = create_engine(settings)
        try:
            async with UnitOfWork(create_session_factory(engine)()).transaction() as s:
                manifest = await import_from(s, Path(bundle), storage=build_storage(settings))
            rows = sum(t.rows for t in manifest.tables.values())
            typer.echo(f"imported {rows} rows in {len(manifest.tables)} tables, checksums verified")
        except PortabilityError as e:
            raise typer.BadParameter(str(e)) from e
        finally:
            await engine.dispose()

    run_async(_run())


@cli.command("asana-import")
def asana_import(
    workspace: str = typer.Option(..., "--workspace", help="Asana workspace gid"),
    team: str = typer.Option(..., "--team", help="Asana team gid"),
    team_name: str = typer.Option(..., "--team-name", help="The team's name in Momentum"),
    acting_as: str = typer.Option(..., "--as", help="Email of the Momentum admin importing"),
    project: list[str] = typer.Option([], "--project", help="Only these project gids"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report only; write nothing"),
    no_invite: bool = typer.Option(
        False, "--no-invite", help="Don't invite Asana people who have no account yet"
    ),
    resume: str | None = typer.Option(None, "--resume", help="Continue this import job id"),
) -> None:
    """Import an Asana team (S7.4.2): projects, sections, tasks and subtasks, custom fields and
    values, comments, files, followers, likes, dependencies and status updates. The token is read
    from the ASANA_PAT environment variable (or asked for) and never stored. Safe to re-run; an
    interrupted import continues with --resume <job id>."""
    import os
    import uuid as _uuid

    from sqlalchemy import func, select

    from momentum.core.context import Actor, Ctx
    from momentum.core.db import UnitOfWork, create_engine, create_session_factory
    from momentum.core.storage import build_storage
    from momentum.domain.users.models import User
    from momentum.integrations.asana_import import service
    from momentum.integrations.asana_import.client import AsanaClient
    from momentum.integrations.asana_import.engine import run_step

    settings = Settings()
    pat = os.environ.get("ASANA_PAT") or typer.prompt(
        "Asana personal access token", hide_input=True
    )

    async def _run() -> None:
        engine = create_engine(settings)
        factory = create_session_factory(engine)
        client = AsanaClient(pat, base_url=settings.asana_base_url)
        try:
            async with UnitOfWork(factory()).transaction() as s:
                user = (
                    await s.execute(select(User).where(func.lower(User.email) == acting_as.lower()))
                ).scalar_one_or_none()
                if user is None or user.role != "admin":
                    raise typer.BadParameter(f"{acting_as} isn't an admin in this workspace")
                ctx = Ctx(
                    actor=Actor(
                        id=user.id,
                        workspace_id=user.workspace_id,
                        role=user.role,
                        email=user.email,
                        name=user.name,
                    ),
                    settings=settings,
                    via="import",
                )
                if resume:
                    job = await service.get_job(s, ctx, _uuid.UUID(resume))
                else:
                    job = await service.start_import(
                        s,
                        ctx,
                        workspace_gid=workspace,
                        team_gid=team,
                        team_name=team_name,
                        project_gids=project or None,
                        dry_run=dry_run,
                        invite_unmatched=not no_invite,
                    )
                job_id = job.id
            typer.echo(f"import {job_id} ({'dry run' if dry_run else 'import'})")
            while True:
                async with UnitOfWork(factory()).transaction() as s:
                    job = await service.get_job(s, ctx, job_id, lock=True)
                    await run_step(
                        s,
                        ctx,
                        client,
                        job,
                        storage=build_storage(settings),
                        max_upload_bytes=settings.max_upload_mb * 1024 * 1024,
                    )
                    stats, status = dict(job.stats or {}), job.status
                typer.echo(
                    f"  {status}: {stats.get('projects', 0)} projects, {stats.get('tasks', 0)} "
                    f"tasks, {stats.get('comments', 0)} comments, {stats.get('remaining', 0)} left"
                )
                if status in ("done", "failed"):
                    break
            for key, value in sorted(stats.items()):
                if key not in ("skipped_items", "remaining", "steps_done"):
                    typer.echo(f"{key:>20}: {value}")
            for reason in stats.get("skipped_items", []):
                typer.echo(f"  skipped: {reason}")
        finally:
            await client.aclose()
            await engine.dispose()

    run_async(_run())


agents_cli = typer.Typer(no_args_is_help=True, help="Agents: install and inspect (Phase 5)")
cli.add_typer(agents_cli, name="agents")

snapshots_cli = typer.Typer(help="Project snapshots for trends (Phase 7.5)", no_args_is_help=True)
cli.add_typer(snapshots_cli, name="snapshots")


@snapshots_cli.command("backfill")
def snapshots_backfill(
    days: int = typer.Option(180, help="How many past days to reconstruct (1-730)"),
) -> None:
    """Reconstruct missing daily snapshots from task dates, project field history and status
    updates (best effort, marked reconstructed). Existing snapshots are kept."""
    from momentum.core.db import UnitOfWork, create_engine, create_session_factory
    from momentum.domain.projects.snapshots import MAX_BACKFILL_DAYS, backfill

    if not 1 <= days <= MAX_BACKFILL_DAYS:
        raise typer.BadParameter(f"--days must be between 1 and {MAX_BACKFILL_DAYS}")
    settings = Settings()

    async def _run() -> int:
        engine = create_engine(settings)
        uow = UnitOfWork(create_session_factory(engine)())
        try:
            async with uow.transaction() as session:
                return await backfill(session, days)
        finally:
            await uow.close()
            await engine.dispose()

    typer.echo(f"{run_async(_run())} snapshots reconstructed")


@snapshots_cli.command("today")
def snapshots_today() -> None:
    """Write today's snapshot for every live project now (what the nightly job does)."""
    from momentum.core.db import UnitOfWork, create_engine, create_session_factory
    from momentum.domain.projects.snapshots import snapshot_all

    settings = Settings()

    async def _run() -> int:
        engine = create_engine(settings)
        uow = UnitOfWork(create_session_factory(engine)())
        try:
            async with uow.transaction() as session:
                return await snapshot_all(session)
        finally:
            await uow.close()
            await engine.dispose()

    typer.echo(f"{run_async(_run())} projects snapshotted")


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
