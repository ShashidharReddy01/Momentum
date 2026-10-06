"""Phase 7.5 S75-08: how long a 10-widget dashboard takes on the onboarding seed (AC: < 1.5 s p95).

Run from apps/api (it makes and uses its own scratch database, never your dev one):

    uv run python ../../tools/perf/dashboard_perf.py [--runs 30]

It seeds the base workspace and the 40-customer onboarding demo, builds a dashboard of the
Leadership template's 8 widgets plus the Implementation lead's "Control tower" table and RAID
stacked bar, then loads it the way the web app does (the dashboard, then every widget's data,
six requests at a time like a browser) as Ravi, in-process over ASGI (one app, one event loop,
like one server worker). "Cold" clears the 60 s result cache before each load; "warm" doesn't.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import tempfile
import time
from typing import Any

import httpx
import psycopg

from momentum.app import create_app
from momentum.core.db import UnitOfWork, create_engine, create_session_factory
from momentum.core.settings import Settings
from momentum.migrations_runner import upgrade_head
from momentum.seed_onboarding import seed_onboarding

ADMIN_URL = "postgresql://momentum:momentum@localhost:5432/postgres"
DB = "momentum_perf"
B = "/api/v1"


def settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        env="test",
        database_url=f"postgresql+psycopg://momentum:momentum@localhost:5432/{DB}",
        db_schema="momentum",
        worker_mode="off",
        realtime_enabled=False,
        serve_spa=False,
        auth_mode="dev",
        secret_key="perf-secret",
        allowed_email_domains="acme-demo.test",
        bootstrap_admin_emails="admin@acme-demo.test",
        storage_local_dir=tempfile.mkdtemp(prefix="momentum-perf-"),
        _env_file=None,
    )


def fresh_database() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {DB}")
    with psycopg.connect(ADMIN_URL.rsplit("/", 1)[0] + f"/{DB}", autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")


def pct(values: list[float], q: float) -> float:
    if len(values) < 2:
        return values[0]
    return statistics.quantiles(sorted(values), n=100, method="inclusive")[int(q * 100) - 1]


async def main(runs: int) -> None:
    fresh_database()
    s = settings()
    upgrade_head(s)
    engine = create_engine(s)
    uow = UnitOfWork(create_session_factory(engine)())
    t = time.perf_counter()
    async with uow.transaction() as session:
        await seed_onboarding(session, s, files=False, backfill_days=90, dashboards=False)
    await uow.close()
    await engine.dispose()
    print(f"seeded in {time.perf_counter() - t:.1f} s")

    app = create_app(s)
    async with app.router.lifespan_context(app):
        c = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://perf",
            headers={"X-Requested-With": "momentum"},
            timeout=60,
        )
        users = (await c.get(f"{B}/dev/users")).json()
        ravi = next(u for u in users if u["email"] == "ravi@acme-demo.test")
        await c.post(f"{B}/dev/login", json={"user_id": ravi["id"]})
        folio = next(
            p["id"]
            for p in (await c.get(f"{B}/portfolios")).json()["data"]
            if p["name"] == "Customer onboarding"
        )
        made = {}
        for key in ("leadership", "implementation_lead"):
            r = await c.post(
                f"{B}/dashboards/from-template", json={"template": key, "portfolio_id": folio}
            )
            r.raise_for_status()
            made[key] = r.json()["data"]["dashboard"]
        lead = {w["title"]: w for w in made["implementation_lead"]["widgets"]}
        board = made["leadership"]
        for title in ("Control tower", "Open RAID by customer, split by Severity"):
            w = lead[title]
            r = await c.post(
                f"{B}/dashboards/{board['id']}/widgets",
                json={
                    "kind": w["kind"],
                    "title": w["title"],
                    "query_spec": w["query_spec"],
                    "viz": w["viz"],
                },
            )
            r.raise_for_status()
        cache = app.state.momentum.dashboard_cache
        gate = asyncio.Semaphore(6)  # a browser's connections per host
        per_widget: dict[str, list[float]] = {}

        async def one(w: dict[str, Any]) -> None:
            async with gate:
                start = time.perf_counter()
                r = await c.get(f"{B}/dashboards/widgets/{w['id']}/data")
                r.raise_for_status()
                per_widget.setdefault(w["title"], []).append(time.perf_counter() - start)

        async def load(cold: bool) -> float:
            if cold:
                cache.clear()
            start = time.perf_counter()
            detail = (await c.get(f"{B}/dashboards/{board['id']}")).json()
            assert len(detail["widgets"]) == 10, len(detail["widgets"])
            await asyncio.gather(*(one(w) for w in detail["widgets"]))
            return time.perf_counter() - start

        await load(True)  # warm the connection pool and the planner
        per_widget.clear()
        cold = [await load(True) for _ in range(runs)]
        slow = {k: pct(v, 0.95) for k, v in per_widget.items()}
        warm = [await load(False) for _ in range(runs)]
        await c.aclose()

    print(f"10-widget dashboard, {runs} loads each (seconds):")
    print(f"  cold: p50 {pct(cold, 0.5):.3f}  p95 {pct(cold, 0.95):.3f}  max {max(cold):.3f}")
    print(f"  warm: p50 {pct(warm, 0.5):.3f}  p95 {pct(warm, 0.95):.3f}  max {max(warm):.3f}")
    print("  per widget, cold p95 (under 6-way concurrency):")
    for title, v in sorted(slow.items(), key=lambda x: -x[1]):
        print(f"    {v:.3f}  {title}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=30)
    asyncio.run(main(parser.parse_args().runs))
