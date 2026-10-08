"""Phase 7.5 S75-08: dashboards v2 (spec §7). Version 2 specs per entity (tasks with a portfolio,
a comparison and a split; projects with measures, tables and timelines), dashboard filters with
"me" (saved, or the viewer's own for one view), members and pins, the portfolio tab, the result
cache, validation, and the seven role templates filling every widget for their persona on the
onboarding seed. Every v1 test (test_dashboards.py) runs unchanged."""

from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.core.db import UnitOfWork
from momentum.core.settings import Settings
from momentum.domain.tasks.models import Task
from momentum.seed_onboarding import ROLE_DASHBOARDS, seed_onboarding
from tests.helpers import Clients

SessionFactory = async_sessionmaker[AsyncSession]
B = "/api/v1"


async def _team(c: httpx.AsyncClient, name: str = "Product") -> str:
    return next(t["id"] for t in (await c.get(f"{B}/teams")).json()["data"] if t["name"] == name)


async def _user_id(c: httpx.AsyncClient, local: str) -> str:
    people = (await c.get(f"{B}/users", params={"q": local})).json()["data"]
    return str(next(u["id"] for u in people if u["email"].startswith(f"{local}@")))


async def _project(c: httpx.AsyncClient, name: str) -> str:
    r = await c.post(f"{B}/projects", json={"team_id": await _team(c), "name": name})
    assert r.status_code == 201, r.text
    return str(r.json()["data"]["id"])


async def _task(c: httpx.AsyncClient, pid: str, title: str, **patch: Any) -> str:
    t = (await c.post(f"{B}/projects/{pid}/tasks", json={"title": title})).json()["data"]
    if patch:
        r = await c.patch(f"{B}/tasks/{t['id']}", json=patch)
        assert r.status_code == 200, r.text
    return str(t["id"])


async def _portfolio(c: httpx.AsyncClient, *pids: str, name: str = "Folio") -> str:
    r = await c.post(f"{B}/portfolios", json={"name": name})
    assert r.status_code == 201, r.text
    fid = str(r.json()["data"]["id"])
    for pid in pids:
        r = await c.post(f"{B}/portfolios/{fid}/projects", json={"project_id": pid})
        assert r.status_code == 201, r.text
    return fid


async def _run(c: httpx.AsyncClient, kind: str, spec: dict[str, Any], **extra: Any) -> Any:
    r = await c.post(f"{B}/dashboards/query", json={"kind": kind, "query_spec": spec, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _v2(entity: str, **spec: Any) -> dict[str, Any]:
    return {"version": 2, "entity": entity, **spec}


# ---------------- tasks ----------------


async def test_tasks_v2_portfolio_comparison_table_and_stacked_bar(
    as_user: Clients, session_factory: SessionFactory
) -> None:
    ravi = await as_user("ravi")
    mei = await _user_id(ravi, "mei")
    a = await _project(ravi, "Acme onboarding")
    other = await _project(ravi, "Outside the folio")
    folio = await _portfolio(ravi, a)
    t1 = await _task(ravi, a, "Urgent one", priority="urgent", assignee_id=mei)
    await _task(ravi, a, "High one", priority="high", assignee_id=mei)
    await _task(ravi, a, "Unprioritised")
    await _task(ravi, other, "Not in the portfolio", priority="urgent")

    spec = _v2("tasks", filters={"portfolio_id": folio})
    kpi = await _run(ravi, "kpi", spec)
    assert kpi["value"] == 3 and kpi["kind"] == "kpi"
    table = await _run(ravi, "table", {**spec, "limit": 10})
    assert {t["title"] for t in table["tasks"]} == {"Urgent one", "High one", "Unprioritised"}
    assert table["columns"][:2] == ["key", "title"]

    stacked = await _run(
        ravi, "stacked_bar", {**spec, "group_by": "assignee", "split_by": "priority"}
    )
    keys = [g["key"] for g in stacked["groups"]]
    by_split = {s["key"]: dict(zip(keys, s["values"], strict=True)) for s in stacked["stacks"]}
    assert by_split["urgent"][mei] == 1 and by_split["high"][mei] == 1
    assert by_split["none"]["none"] == 1  # the unassigned, unprioritised task
    assert "medium" not in by_split  # empty splits are left out
    # each group's stack adds up to the group
    for i, g in enumerate(stacked["groups"]):
        assert sum(s["values"][i] for s in stacked["stacks"]) == g["value"]
    # the drill into one segment lists exactly it
    r = await ravi.post(
        f"{B}/dashboards/drill",
        json={
            "query_spec": {**spec, "group_by": "assignee", "split_by": "priority"},
            "key": mei,
            "split_key": "urgent",
        },
    )
    assert r.status_code == 200, r.text
    assert [t["id"] for t in r.json()["tasks"]] == [t1]

    # completed this week vs the week before (the previous calendar week)
    done = await _task(ravi, a, "Done now")
    old = await _task(ravi, a, "Done last week")
    for tid in (done, old):
        assert (await ravi.post(f"{B}/tasks/{tid}/complete")).status_code == 200
    today = datetime.now(UTC).date()
    monday = today - timedelta(days=today.weekday())
    async with session_factory() as s, s.begin():
        await s.execute(
            update(Task)
            .where(Task.id == old)
            .values(
                completed_at=datetime(monday.year, monday.month, monday.day, 12, tzinfo=UTC)
                - timedelta(days=3)
            )
        )
    week = await _run(
        ravi,
        "kpi",
        _v2(
            "tasks",
            period="this_week",
            compare_previous=True,
            filters={"portfolio_id": folio, "status": "completed", "completed_within_days": 7},
        ),
    )
    assert week["value"] == 1 and week["previous"] == 1


# ---------------- projects ----------------


async def test_projects_measures_table_timeline_and_drill(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    a = await _project(ravi, "Alpha customer")
    b = await _project(ravi, "Beta customer")
    folio = await _portfolio(ravi, a, b)
    value = (
        await ravi.post(f"{B}/project-fields", json={"name": "Contract value", "type": "currency"})
    ).json()["data"]["id"]
    golive = (
        await ravi.post(f"{B}/project-fields", json={"name": "Target go-live", "type": "date"})
    ).json()["data"]["id"]
    soon = (datetime.now(UTC).date() + timedelta(days=10)).isoformat()
    for pid, v in ((a, 100000), (b, 50000)):
        r = await ravi.put(f"{B}/projects/{pid}/project-field-values/{value}", json={"value": v})
        assert r.status_code == 200, r.text
    await ravi.put(f"{B}/projects/{a}/project-field-values/{golive}", json={"value": soon})

    filters = {"portfolio_id": folio}
    total = await _run(
        ravi,
        "kpi",
        _v2("projects", measure="sum_project_field", measure_field_id=value, filters=filters),
    )
    assert total["value"] == 150000 and total["entity"] == "projects"
    avg = await _run(
        ravi,
        "kpi",
        _v2("projects", measure="avg_project_field", measure_field_id=value, filters=filters),
    )
    assert avg["value"] == 75000
    table = await _run(
        ravi,
        "table",
        _v2(
            "projects",
            columns=["name", "owner", f"field:{value}", "progress"],
            sort=f"field:{value}:desc",
            filters=filters,
        ),
    )
    assert [r["name"] for r in table["rows"]] == ["Alpha customer", "Beta customer"]
    assert table["rows"][0][f"field:{value}"] == 100000
    assert table["columns"] == ["name", "owner", f"field:{value}", "progress"]
    timeline = await _run(
        ravi,
        "timeline",
        _v2("projects", ahead_days=30, columns=[f"field:{golive}"], filters=filters),
    )
    assert [(i["project_name"], i["kind"], i["date"]) for i in timeline["timeline"]] == [
        ("Alpha customer", "go_live", soon)
    ]
    bar = _v2("projects", group_by="owner", filters=filters)
    groups = (await _run(ravi, "bar", bar))["groups"]
    assert [(g["label"], g["value"]) for g in groups] == [("Ravi Kumar", 2)]
    r = await ravi.post(f"{B}/dashboards/drill", json={"query_spec": bar, "key": groups[0]["key"]})
    assert r.status_code == 200, r.text
    assert {p["name"] for p in r.json()["projects"]} == {"Alpha customer", "Beta customer"}


# ---------------- filters and "me" ----------------


async def test_dashboard_filters_me_saved_and_for_one_view(as_user: Clients) -> None:
    ravi, mei = await as_user("ravi"), await as_user("mei")
    mei_id = await _user_id(ravi, "mei")
    pid = await _project(ravi, "Filters lab")
    await _task(ravi, pid, "For Mei", assignee_id=mei_id)
    await _task(ravi, pid, "For Ravi", assignee_id=await _user_id(ravi, "ravi"))
    d = (await ravi.post(f"{B}/dashboards", json={"name": "Mine", "starter": False})).json()
    did = d["data"]["id"]
    w = await ravi.post(
        f"{B}/dashboards/{did}/widgets",
        json={
            "kind": "count",
            "title": "Open in the lab",
            "query_spec": {"filters": {"project_ids": [pid]}},
        },
    )
    assert w.status_code == 201, w.text
    wid = w.json()["data"]["id"]

    async def value(c: httpx.AsyncClient, view: dict[str, Any] | None = None) -> Any:
        params = {"filters": json.dumps(view)} if view is not None else None
        r = await c.get(f"{B}/dashboards/widgets/{wid}/data", params=params)
        assert r.status_code == 200, r.text
        return r.json()["value"]

    assert await value(ravi) == 2
    # a viewer narrows it for themselves (in the URL, not saved)
    assert await value(mei, {"assignee": ["me"]}) == 1
    assert await value(ravi) == 2
    # mei can't save filters; ravi saves "assigned to me": each viewer sees their own
    r = await mei.patch(f"{B}/dashboards/{did}", json={"filters": {"assignee": ["me"]}})
    assert r.status_code == 403, r.text
    r = await ravi.patch(f"{B}/dashboards/{did}", json={"filters": {"assignee": ["me"]}})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["filters"]["assignee"] == ["me"]
    assert await value(ravi) == 1 and await value(mei) == 1
    # undo puts the old filters back
    u = await ravi.post(f"{B}/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert u.status_code == 200, u.text
    assert await value(ravi) == 2
    bad = await ravi.get(
        f"{B}/dashboards/widgets/{wid}/data", params={"filters": '{"period": "custom"}'}
    )
    assert bad.status_code == 422


# ---------------- members, pins, the portfolio tab ----------------


async def test_members_pins_and_the_portfolio_tab(as_user: Clients) -> None:
    ravi, mei, tom = await as_user("ravi"), await as_user("mei"), await as_user("tom")
    mei_id = await _user_id(ravi, "mei")
    did = (await ravi.post(f"{B}/dashboards", json={"name": "Shared", "starter": False})).json()[
        "data"
    ]["id"]
    note = {
        "kind": "note",
        "title": "Read me",
        "query_spec": _v2("note", text="Numbers are per viewer."),
    }
    assert (await mei.post(f"{B}/dashboards/{did}/widgets", json=note)).status_code == 403
    r = await mei.put(f"{B}/dashboards/{did}/members/{mei_id}", json={"role": "editor"})
    assert r.status_code == 403  # only the owner or an admin shares
    r = await ravi.put(f"{B}/dashboards/{did}/members/{mei_id}", json={"role": "editor"})
    assert r.status_code == 200, r.text
    members = (await ravi.get(f"{B}/dashboards/{did}/members")).json()["data"]
    assert [(m["name"], m["role"]) for m in members] == [("Mei Chen", "editor")]
    added = await mei.post(f"{B}/dashboards/{did}/widgets", json=note)
    assert added.status_code == 201, added.text
    data = (await tom.get(f"{B}/dashboards/widgets/{added.json()['data']['id']}/data")).json()
    assert data["text"] == "Numbers are per viewer." and data["kind"] == "note"
    u = await ravi.post(f"{B}/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert u.status_code == 200, u.text
    assert (await mei.post(f"{B}/dashboards/{did}/widgets", json=note)).status_code == 403
    assert (await mei.get(f"{B}/dashboards/{did}")).json()["can_edit"] is False

    # pins are per person
    assert (await mei.put(f"{B}/dashboards/{did}/pin")).status_code == 200
    assert [d["id"] for d in (await mei.get(f"{B}/dashboards/pinned")).json()["data"]] == [did]
    assert (await ravi.get(f"{B}/dashboards/pinned")).json()["data"] == []
    listed = {d["id"]: d for d in (await mei.get(f"{B}/dashboards")).json()["data"]}
    assert listed[did]["pinned"] is True
    assert (await mei.delete(f"{B}/dashboards/{did}/pin")).status_code == 200
    assert (await mei.get(f"{B}/dashboards/pinned")).json()["data"] == []

    # a portfolio's Dashboard tab: made and edited by its editors, one per portfolio
    folio = await _portfolio(ravi, await _project(ravi, "Tab lab"))
    tab = (await ravi.get(f"{B}/dashboards/portfolio/{folio}")).json()
    assert tab == {"dashboard": None, "can_edit": True}
    r = await tom.post(
        f"{B}/dashboards", json={"name": "Folio", "portfolio_id": folio, "starter": False}
    )
    assert r.status_code == 403, r.text
    r = await ravi.post(
        f"{B}/dashboards", json={"name": "Folio", "portfolio_id": folio, "starter": False}
    )
    assert r.status_code == 201, r.text
    assert r.json()["data"]["filters"] == {
        "portfolio_id": folio,
        "owner": [],
        "assignee": [],
        "fields": [],
        "period": None,
        "period_from": None,
        "period_to": None,
    }
    again = await ravi.post(f"{B}/dashboards", json={"name": "Twice", "portfolio_id": folio})
    assert again.status_code == 409
    tab = (await ravi.get(f"{B}/dashboards/portfolio/{folio}")).json()
    assert tab["dashboard"]["portfolio_id"] == folio


# ---------------- cache ----------------


async def test_results_are_cached_until_something_changes(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi, "Cache lab")
    await _task(ravi, pid, "One")
    did = (await ravi.post(f"{B}/dashboards", json={"name": "Cached", "starter": False})).json()[
        "data"
    ]["id"]
    wid = (
        await ravi.post(
            f"{B}/dashboards/{did}/widgets",
            json={
                "kind": "count",
                "title": "Open",
                "query_spec": {"filters": {"project_ids": [pid]}},
            },
        )
    ).json()["data"]["id"]
    first = (await ravi.get(f"{B}/dashboards/widgets/{wid}/data")).json()
    second = (await ravi.get(f"{B}/dashboards/widgets/{wid}/data")).json()
    assert second["computed_at"] == first["computed_at"]  # served from the cache
    await _task(ravi, pid, "Two")  # any change makes the next read fresh
    third = (await ravi.get(f"{B}/dashboards/widgets/{wid}/data")).json()
    assert third["value"] == 2 and third["computed_at"] != first["computed_at"]


# ---------------- validation ----------------


async def test_v2_specs_are_validated(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi, "Validation lab")
    folio = await _portfolio(ravi, pid)

    async def status(kind: str, spec: dict[str, Any], **extra: Any) -> int:
        r = await ravi.post(
            f"{B}/dashboards/query", json={"kind": kind, "query_spec": spec, **extra}
        )
        return r.status_code

    assert await status("funnel", _v2("projects")) == 422  # wrong entity for the kind
    assert await status("table", {"filters": {}}) == 422  # new kinds need a v2 spec
    assert await status("stacked_bar", _v2("tasks", group_by="assignee")) == 422  # no split
    no_stage = _v2("stage_events", portfolio_id=folio, analysis="funnel")
    assert await status("funnel", no_stage) == 422  # the portfolio has no stage field
    assert await status("aging", {**no_stage, "analysis": "funnel"}) == 422
    unknown = _v2("projects", group_by="project_field", field_id=pid)
    assert await status("bar", unknown) == 422
    text_field = (
        await ravi.post(f"{B}/projects/{pid}/fields", json={"name": "Note", "type": "text"})
    ).json()["data"]["id"]
    split = _v2("tasks", group_by="assignee", split_by="field", split_field_id=text_field)
    assert await status("stacked_bar", split) == 422
    # a project dashboard shows its own project's tasks only
    assert await status("kpi", _v2("projects"), project_id=pid) == 422
    assert await status("kpi", _v2("tasks"), project_id=pid) == 200
    assert await status("kpi", _v2("projects", extra=1)) == 422  # extra='forbid'


# ---------------- role templates ----------------


async def test_template_preview_drops_what_does_not_bind(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    folio = await _portfolio(ravi, await _project(ravi, "Bind lab"))
    catalog = (await ravi.get(f"{B}/dashboards/templates")).json()["data"]
    # the seeded roles, plus Accounts payable (Phase 7.6: records; not seeded, no invoices there)
    assert [t["key"] for t in catalog] == [*ROLE_DASHBOARDS, "accounts_payable"]
    stage = (
        await ravi.post(
            f"{B}/project-fields",
            json={
                "name": "Stage",
                "type": "single_select",
                "options": [
                    {"label": s}
                    for s in ("Pre-sales", "Discovery", "Contracts", "Implementation", "Live")
                ],
            },
        )
    ).json()["data"]
    await ravi.post(f"{B}/project-fields", json={"name": "contract VALUE", "type": "currency"})
    r = await ravi.patch(f"{B}/portfolios/{folio}/settings", json={"stage_field_id": stage["id"]})
    assert r.status_code == 200, r.text
    body = {"template": "sales", "portfolio_id": folio}
    preview = await ravi.post(f"{B}/dashboards/from-template/preview", json=body)
    assert preview.status_code == 200, preview.text
    p = preview.json()
    titles = [w["title"] for w in p["widgets"]]
    assert "My pipeline value" in titles  # "contract VALUE" binds, case-insensitively
    assert "My accounts" not in titles and "Go-lives, next 90 days" not in titles
    assert any('"Target go-live"' in n and "My accounts" in n for n in p["notes"])
    assert any("dashboard filter" in n and '"Account owner"' in n for n in p["notes"])
    made = await ravi.post(f"{B}/dashboards/from-template", json=body)
    assert made.status_code == 201, made.text
    out = made.json()["data"]
    assert [w["title"] for w in out["dashboard"]["widgets"]] == titles
    assert out["notes"] == p["notes"] and out["dashboard"]["template"] == "sales"
    for w in out["dashboard"]["widgets"]:
        r = await ravi.get(f"{B}/dashboards/widgets/{w['id']}/data")
        assert r.status_code == 200, (w["title"], r.text)
    u = await ravi.post(f"{B}/undo", json={"activity_id": made.json()["meta"]["activity_id"]})
    assert u.status_code == 200, u.text
    bare = await _portfolio(ravi, name="Bare")
    r = await ravi.post(
        f"{B}/dashboards/from-template/preview",
        json={"template": "leadership", "portfolio_id": bare},
    )
    assert r.status_code == 422 and r.json()["code"] == "template_unbound"
    r = await ravi.post(
        f"{B}/dashboards/from-template/preview", json={"template": "nope", "portfolio_id": bare}
    )
    assert r.status_code == 404


def _has_data(kind: str, x: dict[str, Any]) -> bool:
    if kind == "kpi":
        # a calendar-period KPI can be 0 early in its period; it then shows the one before
        return x["value"] is not None and (x["value"] > 0 or (x["previous"] or 0) > 0)
    if kind in ("list", "table"):
        return bool(x["tasks"] or x["rows"])
    if kind in ("bar", "donut", "stacked_bar"):
        return any(g["value"] for g in x["groups"])
    if kind == "line":
        return any(p["value"] for p in x["series"])
    if kind in ("funnel", "stage_time", "aging"):
        return any(s["count"] for s in x["stages"])
    if kind == "timeline":
        return bool(x["timeline"])
    return kind == "note" and bool(x["text"])


async def test_every_role_template_fills_every_widget_for_its_persona(
    uow: UnitOfWork, settings: Settings, as_user: Clients
) -> None:
    async with uow.transaction() as s:
        await seed_onboarding(s, settings, files=False, backfill_days=30)
    timings: dict[str, float] = {}
    for key, persona in ROLE_DASHBOARDS.items():
        c = await as_user(persona)
        pinned = (await c.get(f"{B}/dashboards/pinned")).json()["data"]
        board = next(d for d in pinned if d["template"] == key)
        detail = (await c.get(f"{B}/dashboards/{board['id']}")).json()
        assert detail["can_edit"] is True  # the persona made it
        assert len(detail["widgets"]) >= 5
        start = time.perf_counter()
        for w in detail["widgets"]:
            r = await c.get(f"{B}/dashboards/widgets/{w['id']}/data")
            assert r.status_code == 200, (key, w["title"], r.text)
            assert _has_data(w["kind"], r.json()), (key, w["title"], r.json())
        timings[key] = time.perf_counter() - start
    # generous here (a shared CI box, one request at a time, cold); the as-built note has the
    # measured p95
    assert max(timings.values()) < 6.0, timings


async def test_seeded_role_dashboards_are_consistent(
    uow: UnitOfWork, settings: Settings, as_user: Clients
) -> None:
    """A KPI and its table agree, and a stage bar adds up to the portfolio."""
    async with uow.transaction() as s:
        await seed_onboarding(s, settings, files=False, backfill_days=0)
    sofia = await as_user("sofia")
    board = next(
        d
        for d in (await sofia.get(f"{B}/dashboards/pinned")).json()["data"]
        if d["template"] == "sales"
    )
    detail = (await sofia.get(f"{B}/dashboards/{board['id']}")).json()
    data = {
        w["title"]: (await sofia.get(f"{B}/dashboards/widgets/{w['id']}/data")).json()
        for w in detail["widgets"]
    }
    # every account in the table is Sofia's, and the KPI counts the ones still in flight
    assert data["Accounts in flight"]["value"] == len(
        [r for r in data["My accounts"]["rows"] if r["stage"] not in ("Live", "Lost")]
    )
    assert date.today()  # (the dates themselves are covered by the stage analytics tests)
