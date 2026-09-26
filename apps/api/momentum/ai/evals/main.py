"""``momentum evals``: rebuild the throwaway eval database, run the cases, write the report.

The database is dropped and recreated on every run (migrate → seed → eval workspace → search
index), so results never depend on leftovers. Its name must end in ``_evals`` (it can never be
pointed at a real database by mistake)."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import psycopg
from psycopg import sql

from momentum.ai.embeddings import reindex
from momentum.ai.evals.runner import latest, render, run_evals, save
from momentum.ai.evals.workspace import build_workspace
from momentum.ai.llm import build_llm
from momentum.ai.tools.catalog import build_registry
from momentum.ai.usage import DbUsageLog
from momentum.core.db import create_engine, create_session_factory
from momentum.core.settings import Settings


def evals_url(settings: Settings) -> str:
    if settings.evals_database_url:
        return settings.evals_database_url
    base, _, name = settings.database_url.rpartition("/")
    name = name.split("?")[0]
    return f"{base}/{name if name.endswith('_evals') else name + '_evals'}"


def reset_database(url: str) -> None:
    plain = url.replace("postgresql+psycopg://", "postgresql://", 1)
    name = str(psycopg.conninfo.conninfo_to_dict(plain).get("dbname", ""))
    if not name.endswith("_evals"):
        raise SystemExit(f"refusing to reset {name!r}: the eval database name must end in _evals")
    admin = psycopg.conninfo.make_conninfo(plain, dbname="postgres")
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
        )
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


async def run(
    base: Settings,
    *,
    live: bool,
    features: list[str],
    case: str | None,
    report_dir: Path,
    echo: Callable[[str], None],
    all_cases: bool = False,
) -> bool:
    from alembic import command

    from momentum.migrations_runner import alembic_config
    from momentum.seed import seed

    started = time.monotonic()
    settings = base.model_copy(
        update={
            "database_url": evals_url(base),
            "llm_mode": "gateway" if live else "mock",
            "ai_enabled": True,
            "ai_monthly_budget_usd": 0,
        }
    )
    if live and base.llm_mode != "gateway":
        echo("Live evals need MOMENTUM_LLM_MODE=gateway and the gateway settings.")
        return False
    echo(f"Resetting {settings.database_url.rpartition('@')[2]} …")
    reset_database(settings.database_url)
    command.upgrade(alembic_config(settings), "head")
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    llm = build_llm(settings, DbUsageLog(factory, 0))
    try:
        async with factory() as s, s.begin():
            await seed(s, settings)
        async with factory() as s, s.begin():
            world = await build_workspace(s, settings)
        async with factory() as s, s.begin():
            indexed = await reindex(s, llm)
        echo(f"Eval workspace ready ({indexed.entities} entities indexed). Running cases …")
        previous = latest(report_dir, "live" if live else "mock")
        report = await run_evals(
            factory,
            llm,
            build_registry(),
            settings,
            world,
            live=live,
            features=features or None,
            case_filter=case,
            previous=None if all_cases else previous,
            log=echo,
            all_cases=all_cases,
        )
    finally:
        await llm.aclose()
        await engine.dispose()
    path = save(report, report_dir)
    echo("")
    echo(render(report))
    echo(f"Report: {path} · {time.monotonic() - started:.0f}s")
    return report.ok
