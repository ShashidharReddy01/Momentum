"""Phase 7.5 exit (S75-13): portfolio rows and report timings on the 40-customer onboarding seed.
(The 10-widget dashboard has its own script, ``dashboard_perf.py``.)

Run from apps/api (it makes and uses its own scratch database, never your dev one):

    uv run python ../../tools/perf/phase75_perf.py [--runs 30]

As Ravi, in-process over ASGI (one app, one event loop, like one server worker), mock AI:

- the portfolio table: ``GET /portfolios/{id}/rows`` (every built-in column, 40 projects), and
  the same grouped by stage;
- reports, made inline (no worker): a project status (docx, pdf), a customer update (docx), a
  close-out (docx), the portfolio status (xlsx, docx), each with Mo's narrative from the mock.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from dashboard_perf import B, fresh_database, pct, settings  # noqa: E402

from momentum.app import create_app  # noqa: E402
from momentum.core.db import UnitOfWork, create_engine, create_session_factory  # noqa: E402
from momentum.migrations_runner import upgrade_head  # noqa: E402
from momentum.seed_onboarding import seed_onboarding  # noqa: E402

REPORTS = [
    ("project_status", "docx", "project"),
    ("project_status", "pdf", "project"),
    ("customer_status", "docx", "project"),
    ("closeout", "docx", "project"),
    ("portfolio_status", "xlsx", "portfolio"),
    ("portfolio_status", "docx", "portfolio"),
]


async def main(runs: int, report_runs: int) -> None:
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
            timeout=120,
        )
        users = (await c.get(f"{B}/dev/users")).json()
        ravi = next(u for u in users if u["email"] == "ravi@acme-demo.test")
        await c.post(f"{B}/dev/login", json={"user_id": ravi["id"]})
        folio = next(
            p["id"]
            for p in (await c.get(f"{B}/portfolios")).json()["data"]
            if p["name"] == "Customer onboarding"
        )

        async def timed(method: str, url: str, **kw: object) -> float:
            start = time.perf_counter()
            r = await c.request(method, url, **kw)  # type: ignore[arg-type]
            r.raise_for_status()
            return time.perf_counter() - start

        rows_url = f"{B}/portfolios/{folio}/rows"
        first = (await c.get(rows_url)).json()
        count = len(first["rows"])
        project = first["rows"][0]["id"]
        flat = [await timed("GET", rows_url) for _ in range(runs)]
        grouped = [
            await timed("GET", rows_url, params={"group_by": "stage"}) for _ in range(runs)
        ]
        made: dict[str, list[float]] = {}
        for kind, fmt, where in REPORTS:
            scope = {"project_id": project} if where == "project" else {"portfolio_id": folio}
            spec = {"kind": kind, "format": fmt, "scope": scope}
            if kind in ("project_status", "customer_status", "portfolio_status"):
                spec["narrative"] = True
            for _ in range(report_runs):
                start = time.perf_counter()
                r = await c.post(f"{B}/reports", json={"spec": spec})
                r.raise_for_status()
                assert r.json()["status"] == "done", r.json()
                made.setdefault(f"{kind} ({fmt})", []).append(time.perf_counter() - start)
        await c.aclose()

    print(f"portfolio rows, {count} projects, {runs} requests each (seconds):")
    print(f"  table:    p50 {pct(flat, 0.5):.3f}  p95 {pct(flat, 0.95):.3f}  max {max(flat):.3f}")
    print(
        f"  by stage: p50 {pct(grouped, 0.5):.3f}  p95 {pct(grouped, 0.95):.3f}  "
        f"max {max(grouped):.3f}"
    )
    print(f"reports, {report_runs} each, request to finished file (seconds):")
    for name, v in made.items():
        print(f"  {name:28} median {statistics.median(v):.2f}  max {max(v):.2f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--report-runs", type=int, default=5)
    a = parser.parse_args()
    asyncio.run(main(a.runs, a.report_runs))
