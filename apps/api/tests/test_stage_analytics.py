"""Phase 7.5 S75-08 (spec §11.2): known answers for every stage analysis.

Five projects with a stage history written at known offsets (days before now; "now" is when the
history is written, a second before the query):

    P1  Pre-sales 100 → Discovery 80 → Contracts 60            (in Contracts 60 days)
    P2  Pre-sales 50 → Discovery 40 → Contracts 30 → Impl 10   (in Implementation 10 days)
    P3  Pre-sales 20                                           (in Pre-sales 20 days)
    P4  Pre-sales 300 → Discovery 250 → Contracts 170          (in Contracts 170 days)
    P5  Contracts 200 → Implementation 190                     (in Implementation 190 days)

Targets: Pre-sales 30, Contracts 14, Implementation 90. Window: 180 days.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.domain.fields.models import ProjectFieldEvent, ProjectFieldValue
from momentum.domain.projects.models import Project
from tests.helpers import Clients

SessionFactory = async_sessionmaker[AsyncSession]
B = "/api/v1"
STAGES = ["Pre-sales", "Discovery", "Contracts", "Implementation", "Go-live", "Hypercare"]
HISTORY = {
    "P1": [("Pre-sales", 100), ("Discovery", 80), ("Contracts", 60)],
    "P2": [("Pre-sales", 50), ("Discovery", 40), ("Contracts", 30), ("Implementation", 10)],
    "P3": [("Pre-sales", 20)],
    "P4": [("Pre-sales", 300), ("Discovery", 250), ("Contracts", 170)],
    "P5": [("Contracts", 200), ("Implementation", 190)],
}


async def _world(
    c: httpx.AsyncClient, session_factory: SessionFactory
) -> tuple[str, dict[str, str], dict[str, str]]:
    """(portfolio id, stage label → option id, project name → id)."""
    projects = (await c.get(f"{B}/projects")).json()["data"]
    team_id = projects[0]["team_id"]
    r = await c.post(
        f"{B}/project-fields",
        json={"name": "Stage", "type": "single_select", "options": [{"label": s} for s in STAGES]},
    )
    assert r.status_code == 201, r.text
    field = r.json()["data"]
    opt = {o["label"]: o["id"] for o in field["options"]}
    pids: dict[str, str] = {}
    for name in HISTORY:
        r = await c.post(f"{B}/projects", json={"name": name, "team_id": team_id})
        assert r.status_code == 201, r.text
        pids[name] = r.json()["data"]["id"]
    r = await c.post(f"{B}/portfolios", json={"name": "Lifecycle"})
    folio = r.json()["data"]["id"]
    for pid in pids.values():
        r = await c.post(f"{B}/portfolios/{folio}/projects", json={"project_id": pid})
        assert r.status_code == 201, r.text
    r = await c.patch(
        f"{B}/portfolios/{folio}/settings",
        json={
            "stage_field_id": field["id"],
            "stage_targets": {
                opt["Pre-sales"]: 30,
                opt["Contracts"]: 14,
                opt["Implementation"]: 90,
            },
        },
    )
    assert r.status_code == 200, r.text
    now = datetime.now(UTC)
    async with session_factory() as s, s.begin():
        for name, steps in HISTORY.items():
            pid = uuid.UUID(pids[name])
            project = await s.get(Project, pid)
            assert project is not None
            prev: str | None = None
            for label, days in steps:
                s.add(
                    ProjectFieldEvent(
                        workspace_id=project.workspace_id,
                        project_id=pid,
                        field_id=uuid.UUID(field["id"]),
                        old=prev,
                        new=opt[label],
                        at=now - timedelta(days=days),
                    )
                )
                prev = opt[label]
            s.add(
                ProjectFieldValue(
                    project_id=pid,
                    field_id=uuid.UUID(field["id"]),
                    workspace_id=project.workspace_id,
                    value=prev,
                )
            )
    return folio, opt, pids


async def _q(c: httpx.AsyncClient, kind: str, **spec: Any) -> dict[str, Any]:
    r = await c.post(
        f"{B}/dashboards/query",
        json={"kind": kind, "query_spec": {"version": 2, "entity": "stage_events", **spec}},
    )
    assert r.status_code == 200, r.text
    return dict(r.json())


def _by_label(out: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {st["label"]: st for st in out["stages"]}


async def test_funnel_known_answer(as_user: Clients, session_factory: SessionFactory) -> None:
    ravi = await as_user("ravi")
    folio, _opt, _p = await _world(ravi, session_factory)
    out = await _q(ravi, "funnel", portfolio_id=folio, analysis="funnel", window_days=180)
    st = _by_label(out)
    assert [s["label"] for s in out["stages"]] == STAGES  # lifecycle order
    assert {k: v["count"] for k, v in st.items()} == {
        "Pre-sales": 3,  # P1, P2, P3 (P4 entered 300 days ago)
        "Discovery": 2,  # P1, P2
        "Contracts": 3,  # P1, P2, P4
        "Implementation": 1,  # P2 (P5 entered 190 days ago)
        "Go-live": 0,
        "Hypercare": 0,
    }
    assert st["Pre-sales"]["conversion"] is None
    assert st["Discovery"]["conversion"] == round(2 / 3, 4)
    assert st["Contracts"]["conversion"] == 1.5
    assert st["Implementation"]["conversion"] == round(1 / 3, 4)
    assert st["Go-live"]["conversion"] == 0
    assert st["Hypercare"]["conversion"] is None  # nothing reached the stage before


async def test_time_in_stage_known_answer(
    as_user: Clients, session_factory: SessionFactory
) -> None:
    ravi = await as_user("ravi")
    folio, opt, _p = await _world(ravi, session_factory)
    out = await _q(
        ravi, "stage_time", portfolio_id=folio, analysis="time_in_stage", window_days=180
    )
    st = _by_label(out)
    # stays that ended inside the window
    assert st["Pre-sales"]["count"] == 2  # P1 20 days, P2 10 days (P4's ended 250 days ago)
    assert st["Pre-sales"]["median_days"] == 15.0
    assert st["Pre-sales"]["p75_days"] == 17.5
    assert st["Pre-sales"]["p90_days"] == 19.0
    assert st["Pre-sales"]["target_days"] == 30
    assert st["Discovery"]["count"] == 3  # 20, 10, 80
    assert st["Discovery"]["median_days"] == 20.0
    assert st["Discovery"]["p75_days"] == 50.0
    assert st["Discovery"]["p90_days"] == 68.0
    assert st["Contracts"]["count"] == 1  # P2's 20 days (P5's ended 190 days ago)
    assert st["Contracts"]["median_days"] == 20.0
    assert st["Contracts"]["target_days"] == 14
    assert st["Implementation"]["count"] == 0
    assert st["Implementation"]["median_days"] is None
    kpi = await _q(
        ravi,
        "kpi",
        portfolio_id=folio,
        analysis="time_in_stage",
        window_days=180,
        stages=[opt["Discovery"]],
    )
    assert kpi["value"] == 20.0


async def test_throughput_known_answer(as_user: Clients, session_factory: SessionFactory) -> None:
    ravi = await as_user("ravi")
    folio, opt, _p = await _world(ravi, session_factory)
    out = await _q(
        ravi,
        "kpi",
        portfolio_id=folio,
        analysis="throughput",
        window_days=180,
        stages=[opt["Contracts"]],
        compare_previous=True,
    )
    assert out["value"] == 3  # P1 60, P2 30, P4 170
    assert out["previous"] == 1  # P5 200 days ago (180..360)
    line = await _q(
        ravi,
        "line",
        portfolio_id=folio,
        analysis="throughput",
        window_days=180,
        stages=[opt["Contracts"]],
        time_bucket="month",
    )
    assert sum(p["value"] for p in line["series"]) == 3


async def test_throughput_kpi_drills_into_its_own_stage_and_period(
    as_user: Clients, session_factory: SessionFactory
) -> None:
    """A KPI tile drills with no key (live check, "Went live this quarter"): a one-stage
    throughput KPI drills into that stage, over the same window or calendar period it counts."""
    ravi = await as_user("ravi")
    folio, opt, _p = await _world(ravi, session_factory)
    for extra in ({"window_days": 180}, {"period": "this_quarter"}, {"period": "this_month"}):
        spec = {
            "version": 2,
            "entity": "stage_events",
            "portfolio_id": folio,
            "analysis": "throughput",
            "stages": [opt["Contracts"]],
            **extra,
        }
        args = {k: v for k, v in spec.items() if k not in ("version", "entity")}
        kpi = await _q(ravi, "kpi", **args)
        r = await ravi.post(f"{B}/dashboards/drill", json={"query_spec": spec})
        assert r.status_code == 200, (extra, r.text)
        assert r.json()["total"] == kpi["value"], extra
        assert r.json()["label"] == "Contracts"


async def test_aging_known_answer(as_user: Clients, session_factory: SessionFactory) -> None:
    ravi = await as_user("ravi")
    folio, _opt, _p = await _world(ravi, session_factory)
    out = await _q(ravi, "aging", portfolio_id=folio, analysis="aging")
    st = _by_label(out)
    # buckets: 0-7, 8-14, 15-30, 31-60, 61+
    assert st["Pre-sales"]["buckets"] == [0, 0, 1, 0, 0]  # P3 20 days
    assert st["Pre-sales"]["breaches"] == 0
    assert st["Contracts"]["buckets"] == [0, 0, 0, 1, 1]  # P1 60, P4 170
    assert st["Contracts"]["breaches"] == 2  # target 14
    assert st["Implementation"]["buckets"] == [0, 1, 0, 0, 1]  # P2 10, P5 190
    assert st["Implementation"]["breaches"] == 1  # target 90
    assert st["Discovery"]["count"] == 0


async def test_stage_drill_and_projects_by_stage(
    as_user: Clients, session_factory: SessionFactory
) -> None:
    ravi = await as_user("ravi")
    folio, opt, pids = await _world(ravi, session_factory)
    spec = {
        "version": 2,
        "entity": "stage_events",
        "portfolio_id": folio,
        "analysis": "funnel",
        "window_days": 180,
    }
    r = await ravi.post(f"{B}/dashboards/drill", json={"query_spec": spec, "key": opt["Contracts"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entity"] == "projects"
    assert body["label"] == "Contracts"
    assert {p["name"] for p in body["projects"]} == {"P1", "P2", "P4"}
    # the projects entity agrees with the current stage
    r = await ravi.post(
        f"{B}/dashboards/query",
        json={
            "kind": "bar",
            "query_spec": {
                "version": 2,
                "entity": "projects",
                "group_by": "stage",
                "filters": {"portfolio_id": folio},
            },
        },
    )
    assert r.status_code == 200, r.text
    groups = {g["label"]: g["value"] for g in r.json()["groups"]}
    assert groups["Pre-sales"] == 1
    assert groups["Contracts"] == 2
    assert groups["Implementation"] == 2
    assert groups["Discovery"] == 0
    assert set(pids)  # every project accounted for: 1 + 2 + 2
    assert sum(groups.values()) == 5
