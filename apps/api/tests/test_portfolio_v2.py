"""Phase 7.5 S75-05: portfolio v2 (spec §5.2-§5.6). Rule membership as the viewer, every built-in
column in SQL with a constant query count, filters / grouping / sort on the server, saved views,
members and permissions (guests too), manual ↔ rule, settings validation, readiness and stage
moves with gate overrides, and the workload grid restricted to a portfolio."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from momentum.core.activity import Activity
from momentum.core.db import UnitOfWork
from momentum.core.settings import Settings
from momentum.domain.forecasts.models import Forecast
from momentum.domain.portfolios.models import Portfolio
from momentum.domain.portfolios.rows import ViewSpec, portfolio_rows_v2
from tests.helpers import Clients, ctx_for

SessionFactory = async_sessionmaker[AsyncSession]
B = "/api/v1"
STAGES = ["Pre-sales", "Discovery", "Contracts", "Implementation", "Go-live", "Hypercare"]


async def _ids(c: httpx.AsyncClient) -> dict[str, str]:
    users = {u["email"].split("@")[0]: u["id"] for u in (await c.get(f"{B}/users")).json()["data"]}
    teams = {t["name"]: t["id"] for t in (await c.get(f"{B}/teams")).json()["data"]}
    projects = {p["name"]: p["id"] for p in (await c.get(f"{B}/projects")).json()["data"]}
    return {**users, **teams, **projects}


async def _stage(c: httpx.AsyncClient) -> tuple[str, dict[str, str]]:
    r = await c.post(
        f"{B}/project-fields",
        json={"name": "Stage", "type": "single_select", "options": [{"label": s} for s in STAGES]},
    )
    assert r.status_code == 201, r.text
    f = r.json()["data"]
    return f["id"], {o["label"]: o["id"] for o in f["options"]}


async def _value_field(c: httpx.AsyncClient) -> str:
    r = await c.post(f"{B}/project-fields", json={"name": "Contract value", "type": "currency"})
    assert r.status_code == 201, r.text
    return str(r.json()["data"]["id"])


async def _portfolio(c: httpx.AsyncClient, name: str = "Onboarding", *pids: str) -> str:
    r = await c.post(f"{B}/portfolios", json={"name": name})
    assert r.status_code == 201, r.text
    fid = str(r.json()["data"]["id"])
    for pid in pids:
        r = await c.post(f"{B}/portfolios/{fid}/projects", json={"project_id": pid})
        assert r.status_code == 201, r.text
    return fid


async def _set(c: httpx.AsyncClient, pid: str, fid: str, value: Any) -> None:
    r = await c.put(f"{B}/projects/{pid}/project-field-values/{fid}", json={"value": value})
    assert r.status_code == 200, r.text


async def _rows(c: httpx.AsyncClient, folio: str, **params: Any) -> dict[str, Any]:
    r = await c.get(f"{B}/portfolios/{folio}/rows", params=params)
    assert r.status_code == 200, r.text
    return dict(r.json())


async def _task(c: httpx.AsyncClient, pid: str, title: str, **body: Any) -> str:
    r = await c.post(f"{B}/projects/{pid}/tasks", json={"title": title, **body})
    assert r.status_code == 201, r.text
    return str(r.json()["data"]["id"])


# ---------------- rows: every built-in column ----------------


async def test_rows_compute_every_builtin_column(
    as_user: Clients, session_factory: SessionFactory
) -> None:
    ravi = await as_user("ravi")
    ids = await _ids(ravi)
    pid = ids["Website Revamp"]
    stage_id, stages = await _stage(ravi)
    value_id = await _value_field(ravi)
    folio = await _portfolio(ravi, "Onboarding", pid)
    r = await ravi.patch(
        f"{B}/portfolios/{folio}/settings",
        json={"stage_field_id": stage_id, "stage_targets": {stages["Implementation"]: 30}},
    )
    assert r.status_code == 200, r.text

    today = datetime.now(UTC).date()
    late = await _task(ravi, pid, "Late thing", due_on=(today - timedelta(days=2)).isoformat())
    blocker = await _task(ravi, pid, "Blocker")
    waits = await _task(ravi, pid, "Waits on blocker")
    r = await ravi.post(f"{B}/tasks/{waits}/dependencies", json={"depends_on_id": blocker})
    assert r.status_code in (200, 201), r.text
    ms = await _task(ravi, pid, "Contract signed", due_on=(today + timedelta(days=5)).isoformat())
    await ravi.post(f"{B}/tasks/{ms}/convert", json={"type": "milestone"})
    waiting = (
        await ravi.post(
            f"{B}/projects/{pid}/fields",
            json={
                "name": "Waiting on",
                "type": "single_select",
                "options": [{"label": "Customer"}, {"label": "Us"}],
            },
        )
    ).json()["data"]
    customer = next(o["id"] for o in waiting["options"] if o["label"] == "Customer")
    await ravi.put(f"{B}/tasks/{late}/fields/{waiting['id']}", json={"value": customer})
    await _set(ravi, pid, stage_id, stages["Implementation"])
    await _set(ravi, pid, value_id, 120000)
    async with session_factory() as s, s.begin():
        project = uuid.UUID(pid)
        ws = (await s.get(Portfolio, uuid.UUID(folio))).workspace_id  # type: ignore[union-attr]
        s.add(
            Forecast(
                workspace_id=ws,
                project_id=project,
                as_of=today,
                status="ok",
                p50=today + timedelta(days=20),
                p80=today + timedelta(days=40),
                p95=today + timedelta(days=50),
                risk_score=40,
                risk_level="medium",
                drivers=[],
                inputs={},
            )
        )

    out = await _rows(ravi, folio)
    (row,) = out["rows"]
    assert row["overdue"] >= 1 and row["open"] >= 4
    assert row["blocked"] == 1
    assert row["waiting_on_customer"] == 1
    assert row["next_milestone"]["title"] == "Contract signed"
    assert row["stage"] == {"option_id": stages["Implementation"], "label": "Implementation"}
    assert row["stage_age_days"] == 0 and row["stage_target_days"] == 30
    assert row["target_date"] == (today + timedelta(days=30)).isoformat()
    assert row["forecast_date"] == (today + timedelta(days=40)).isoformat()
    assert row["slip_days"] == 10
    assert row["fields"][value_id] == 120000
    assert 0 <= row["progress"] <= 1
    keys = [c["key"] for c in out["columns"]]
    assert keys[:3] == ["name", "owner", "status"] and f"field:{value_id}" in keys
    assert out["hidden_projects"] == 0
    # the portfolio can say which choice means "waiting on the customer"
    r = await ravi.patch(
        f"{B}/portfolios/{folio}/settings",
        json={"columns": [{"key": "waiting_on_customer", "option_label": "Us"}]},
    )
    assert r.status_code == 200, r.text
    assert (await _rows(ravi, folio))["rows"][0]["waiting_on_customer"] == 0


async def test_query_count_is_constant_and_forty_projects_are_fast(
    as_user: Clients, uow: UnitOfWork, settings: Settings, engine: AsyncEngine
) -> None:
    ravi = await as_user("ravi")
    ids = await _ids(ravi)
    stage_id, stages = await _stage(ravi)
    value_id = await _value_field(ravi)
    small = [ids["Website Revamp"]]
    many = list(small)
    for i in range(39):
        r = await ravi.post(f"{B}/projects", json={"team_id": ids["Product"], "name": f"Cust {i}"})
        pid = r.json()["data"]["id"]
        many.append(pid)
        await _task(ravi, pid, "Kickoff", due_on="2026-01-05")
        await _set(ravi, pid, stage_id, stages[STAGES[i % len(STAGES)]])
        await _set(ravi, pid, value_id, 1000 * i)
    f_small = await _portfolio(ravi, "Small", *small)
    f_many = await _portfolio(ravi, "Many", *many)
    for f in (f_small, f_many):
        await ravi.patch(f"{B}/portfolios/{f}/settings", json={"stage_field_id": stage_id})
    ctx = await ctx_for(uow, settings, "ravi")

    statements: list[str] = []

    def count(*args: Any) -> None:
        statements.append(str(args[2]))

    async def run(folio: str) -> tuple[int, float, int]:
        statements.clear()
        async with uow.transaction() as s:
            p = await s.get(Portfolio, uuid.UUID(folio))
            assert p is not None
            event.listen(engine.sync_engine, "before_cursor_execute", count)
            try:
                started = time.perf_counter()
                out = await portfolio_rows_v2(s, ctx, p, ViewSpec(group_by="stage"))
                took = time.perf_counter() - started
            finally:
                event.remove(engine.sync_engine, "before_cursor_execute", count)
        return len(statements), took, len(out.rows)

    q_small, _t, n_small = await run(f_small)
    q_many, took, n_many = await run(f_many)
    assert (n_small, n_many) == (1, 40)
    assert q_many == q_small, (q_small, q_many)  # no N+1: the count doesn't grow with projects
    assert took < 1.0, took  # spec budget is 300 ms on the onboarding seed (as-built note)


# ---------------- filters, grouping, sort ----------------


async def test_filters_grouping_rollups_and_sort_on_the_server(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    ids = await _ids(ravi)
    stage_id, stages = await _stage(ravi)
    value_id = await _value_field(ravi)
    a, b, c = ids["Website Revamp"], ids["Mobile App v2"], ids["Vendor Onboarding"]
    folio = await _portfolio(ravi, "Onboarding", a, b, c)
    await ravi.patch(f"{B}/portfolios/{folio}/settings", json={"stage_field_id": stage_id})
    await _set(ravi, a, stage_id, stages["Discovery"])
    await _set(ravi, b, stage_id, stages["Discovery"])
    await _set(ravi, c, stage_id, stages["Go-live"])
    await _set(ravi, a, value_id, 100)
    await _set(ravi, b, value_id, 300)

    out = await _rows(ravi, folio, group_by="stage", sort=f"field:{value_id}:desc")
    assert [r["id"] for r in out["rows"]] == [b, a, c]  # empty values last
    groups = {g["label"]: g for g in out["groups"]}
    assert list(groups)[:6] == STAGES  # every stage, in lifecycle order, even empty
    assert groups["Discovery"]["rollup"]["count"] == 2
    assert groups["Discovery"]["rollup"]["sums"][value_id] == 400
    assert groups["Discovery"]["rollup"]["avgs"][value_id] == 200
    assert groups["Pre-sales"]["project_ids"] == []

    only = await _rows(ravi, folio, filters=f'{{"stage": ["{stages["Go-live"]}"]}}')
    assert [r["id"] for r in only["rows"]] == [c]
    cond = f'{{"fields": [{{"field_id": "{value_id}", "op": "set"}}]}}'
    assert {r["id"] for r in (await _rows(ravi, folio, filters=cond))["rows"]} == {a, b}
    r = await ravi.get(f"{B}/portfolios/{folio}/rows", params={"sort": "nonsense:asc"})
    assert r.status_code == 422
    r = await ravi.get(f"{B}/portfolios/{folio}/rows", params={"group_by": "budget"})
    assert r.status_code == 422


# ---------------- rule membership ----------------


async def test_rule_portfolio_membership_is_computed_as_the_viewer(as_user: Clients) -> None:
    admin = await as_user("admin")
    ids = await _ids(admin)
    stage_id, stages = await _stage(admin)
    for name in ("Website Revamp", "Q4 Launch Campaign"):
        await _set(admin, ids[name], stage_id, stages["Implementation"])
    folio = await _portfolio(admin, "In implementation")
    r = await admin.post(
        f"{B}/portfolios/{folio}/convert",
        json={
            "kind": "rule",
            "rule": {
                "project_field_conditions": [
                    {"field_id": stage_id, "op": "is", "value": stages["Implementation"]}
                ]
            },
        },
    )
    assert r.status_code == 200, r.text
    names = {r["name"] for r in (await _rows(admin, folio))["rows"]}
    assert names == {"Website Revamp", "Q4 Launch Campaign"}
    # ravi can't see the Marketing project: counted, never named
    ravi = await as_user("ravi")
    seen = await _rows(ravi, folio)
    assert [r["name"] for r in seen["rows"]] == ["Website Revamp"]
    assert seen["hidden_projects"] == 1
    # a new project that matches appears by itself; adding by hand is refused
    await _set(admin, ids["Vendor Onboarding"], stage_id, stages["Implementation"])
    assert len((await _rows(admin, folio))["rows"]) == 3
    r = await admin.post(
        f"{B}/portfolios/{folio}/projects", json={"project_id": ids["Website Revamp"]}
    )
    assert r.status_code == 422 and r.json()["code"] == "rule_portfolio"
    listed = {p["id"]: p for p in (await ravi.get(f"{B}/portfolios")).json()["data"]}
    assert listed[folio]["kind"] == "rule" and listed[folio]["project_count"] == 2


async def test_converting_keeps_the_projects_both_ways_and_undoes(
    as_user: Clients, session_factory: SessionFactory
) -> None:
    ravi = await as_user("ravi")
    ids = await _ids(ravi)
    a, b = ids["Website Revamp"], ids["Vendor Onboarding"]
    folio = await _portfolio(ravi, "Mine", a, b)
    r = await ravi.post(f"{B}/portfolios/{folio}/convert", json={"kind": "rule"})
    assert r.status_code == 200, r.text
    detail = r.json()["data"]
    assert detail["kind"] == "rule" and set(detail["rule"]["project_ids"]) == {a, b}
    assert {p["id"] for p in detail["projects"]} == {a, b}
    r = await ravi.post(f"{B}/portfolios/{folio}/convert", json={"kind": "manual"})
    assert r.json()["data"]["kind"] == "manual"
    assert {p["id"] for p in r.json()["data"]["projects"]} == {a, b}
    undo = await ravi.post(f"{B}/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert undo.status_code == 200, undo.text
    assert (await ravi.get(f"{B}/portfolios/{folio}")).json()["kind"] == "rule"


# ---------------- settings ----------------


async def test_settings_are_validated_and_undoable(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    ids = await _ids(ravi)
    stage_id, stages = await _stage(ravi)
    text_field = (
        await ravi.post(f"{B}/project-fields", json={"name": "Account", "type": "text"})
    ).json()["data"]["id"]
    folio = await _portfolio(ravi, "Onboarding", ids["Website Revamp"])
    url = f"{B}/portfolios/{folio}/settings"
    assert (await ravi.patch(url, json={"stage_field_id": text_field})).status_code == 422
    assert (await ravi.patch(url, json={"stage_targets": {"x": 3}})).status_code == 422
    ok = await ravi.patch(
        url,
        json={
            "stage_field_id": stage_id,
            "stage_gates": {stages["Implementation"]: {"required_files": ["*signed*.pdf"]}},
            "columns": [
                {"key": "name"},
                {"key": "stage", "width": 140},
                {"key": f"field:{text_field}"},
            ],
        },
    )
    assert ok.status_code == 200, ok.text
    assert (await ravi.patch(url, json={"columns": [{"key": "budget"}]})).status_code == 422
    assert (await ravi.patch(url, json={"rule": {"team_ids": []}})).status_code == 422  # manual
    cols = (await _rows(ravi, folio))["columns"]
    assert [c["key"] for c in cols[:3]] == ["name", "stage", f"field:{text_field}"]
    assert cols[1]["width"] == 140 and cols[3]["visible"] is False  # unlisted ones hidden
    undo = await ravi.post(f"{B}/undo", json={"activity_id": ok.json()["meta"]["activity_id"]})
    assert undo.status_code == 200, undo.text
    detail = (await ravi.get(f"{B}/portfolios/{folio}")).json()
    assert detail["stage_field_id"] is None and detail["columns"] == []


# ---------------- views ----------------


async def test_views_personal_and_shared(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    ids = await _ids(ravi)
    folio = await _portfolio(ravi, "Onboarding", ids["Website Revamp"])
    mei = await as_user("mei")
    url = f"{B}/portfolios/{folio}/views"
    shared = await ravi.post(url, json={"name": "By stage", "group_by": "status", "shared": True})
    assert shared.status_code == 201, shared.text
    assert (await mei.post(url, json={"name": "Team", "shared": True})).status_code == 403
    mine = await mei.post(
        url, json={"name": "Mine", "layout": "board", "sort": [{"key": "name", "dir": "desc"}]}
    )
    assert mine.status_code == 201, mine.text
    assert {v["name"] for v in (await mei.get(url)).json()["data"]} == {"By stage", "Mine"}
    assert {v["name"] for v in (await ravi.get(url)).json()["data"]} == {"By stage"}
    vid = mine.json()["data"]["id"]
    assert (await ravi.patch(f"{url}/{vid}", json={"name": "x"})).status_code == 404
    assert (
        await mei.patch(f"{url}/{shared.json()['data']['id']}", json={"name": "x"})
    ).status_code == 403
    out = await _rows(mei, folio, view_id=vid)
    assert out["view_id"] == vid and out["groups"] is None
    grouped = await _rows(ravi, folio, view_id=shared.json()["data"]["id"])
    assert grouped["groups"] is not None
    gone = await mei.delete(f"{url}/{vid}")
    assert gone.status_code == 200
    await mei.post(f"{B}/undo", json={"activity_id": gone.json()["meta"]["activity_id"]})
    assert {v["name"] for v in (await mei.get(url)).json()["data"]} == {"By stage", "Mine"}
    assert (await mei.post(url, json={"name": "Bad", "group_by": "budget"})).status_code == 422


# ---------------- members, permissions, guests ----------------


async def test_members_edit_and_guests_see_only_shared_rows(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    admin = await as_user("admin")
    ids = await _ids(ravi)  # ravi is a member of the private Mobile App v2; admin isn't
    folio = await _portfolio(ravi, "Onboarding", ids["Website Revamp"], ids["Mobile App v2"])
    mei = await as_user("mei")
    settings_url = f"{B}/portfolios/{folio}/settings"
    assert (await mei.patch(settings_url, json={"columns": []})).status_code == 403
    r = await ravi.put(f"{B}/portfolios/{folio}/members/{ids['mei']}", json={"role": "editor"})
    assert r.status_code == 200, r.text
    assert (await mei.patch(settings_url, json={"columns": [{"key": "name"}]})).status_code == 200
    # an editor doesn't manage members; the owner and admins do
    r = await mei.put(f"{B}/portfolios/{folio}/members/{ids['kim']}", json={"role": "viewer"})
    assert r.status_code == 403
    members = (await mei.get(f"{B}/portfolios/{folio}/members")).json()["data"]
    assert [(m["name"], m["role"]) for m in members] == [("Mei Chen", "editor")]
    removed = await ravi.delete(f"{B}/portfolios/{folio}/members/{ids['mei']}")
    assert removed.status_code == 200
    await ravi.post(f"{B}/undo", json={"activity_id": removed.json()["meta"]["activity_id"]})
    assert len((await mei.get(f"{B}/portfolios/{folio}/members")).json()["data"]) == 1

    # guests: invisible unless a member, then only the rows of projects shared with them
    await admin.patch(f"{B}/users/{ids['sam']}", json={"role": "guest"})
    sam = await as_user("sam")
    assert folio not in {p["id"] for p in (await sam.get(f"{B}/portfolios")).json()["data"]}
    assert (await sam.get(f"{B}/portfolios/{folio}/rows")).status_code == 404
    await ravi.put(f"{B}/portfolios/{folio}/members/{ids['sam']}", json={"role": "viewer"})
    await ravi.post(
        f"{B}/projects/{ids['Website Revamp']}/members",
        json={"user_id": ids["sam"], "role": "viewer"},
    )
    out = await _rows(sam, folio)
    assert [r["name"] for r in out["rows"]] == ["Website Revamp"]
    assert out["hidden_projects"] == 1


# ---------------- readiness and stage moves ----------------


async def test_readiness_and_board_moves_with_gate_override(
    as_user: Clients, session_factory: SessionFactory
) -> None:
    ravi = await as_user("ravi")
    ids = await _ids(ravi)
    pid = ids["Website Revamp"]
    stage_id, stages = await _stage(ravi)
    value_id = await _value_field(ravi)
    folio = await _portfolio(ravi, "Onboarding", pid)
    impl = stages["Implementation"]
    await ravi.patch(
        f"{B}/portfolios/{folio}/settings",
        json={
            "stage_field_id": stage_id,
            "stage_gates": {
                impl: {
                    "required_fields": [value_id],
                    "required_milestones": ["Contract signed"],
                    "required_files": ["*contract*signed*.pdf"],
                }
            },
        },
    )
    url = f"{B}/portfolios/{folio}/projects/{pid}"
    ready = (await ravi.get(f"{url}/readiness", params={"to": impl})).json()
    assert ready["met"] is False and ready["stage_label"] == "Implementation"
    assert [(i["kind"], i["met"]) for i in ready["items"]] == [
        ("field", False),
        ("milestone", False),
        ("file", False),
    ]
    assert (await ravi.get(f"{url}/readiness", params={"to": "nope"})).status_code == 422
    # a stage without a gate moves straight away
    ok = await ravi.post(f"{url}/stage", json={"to": stages["Discovery"]})
    assert ok.status_code == 200, ok.text
    refused = await ravi.post(f"{url}/stage", json={"to": impl})
    assert refused.status_code == 409 and refused.json()["code"] == "gate_not_met"
    assert len(refused.json()["readiness"]["items"]) == 3
    moved = await ravi.post(f"{url}/stage", json={"to": impl, "override": True})
    assert moved.status_code == 200, moved.text
    async with session_factory() as s:
        act = await s.get(Activity, uuid.UUID(moved.json()["meta"]["activity_id"]))
        assert act is not None and "gate_override" in act.diff
    undo = await ravi.post(f"{B}/undo", json={"activity_id": moved.json()["meta"]["activity_id"]})
    assert undo.status_code == 200
    values = (await ravi.get(f"{B}/projects/{pid}/project-field-values")).json()["data"]
    assert next(v["value"] for v in values if v["field_id"] == stage_id) == stages["Discovery"]

    # meet the gate: the checklist turns green, the move needs no override
    await _set(ravi, pid, value_id, 5000)
    ms = await _task(ravi, pid, "Contract signed")
    await ravi.post(f"{B}/tasks/{ms}/convert", json={"type": "milestone"})
    await ravi.post(f"{B}/tasks/{ms}/complete")
    up = await ravi.post(
        f"{B}/projects/{pid}/files",
        files={"file": ("ACME contract SIGNED.pdf", b"%PDF-1.4 synthetic", "application/pdf")},
    )
    assert up.status_code == 201, up.text
    ready = (await ravi.get(f"{url}/readiness", params={"to": impl})).json()
    assert ready["met"] is True and all(i["ref"] for i in ready["items"])
    assert (await ravi.post(f"{url}/stage", json={"to": impl})).status_code == 200
    # a viewer of the project can't move it
    kim = await as_user("kim")
    await ravi.post(f"{B}/projects/{pid}/members", json={"user_id": ids["kim"], "role": "viewer"})
    assert (await kim.post(f"{url}/stage", json={"to": stages["Go-live"]})).status_code == 403


# ---------------- workload ----------------


async def test_workload_restricted_to_a_portfolio(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    ids = await _ids(ravi)
    a, b = ids["Website Revamp"], ids["Vendor Onboarding"]
    folio = await _portfolio(ravi, "Only one", a)
    soon = (date.today() + timedelta(days=1)).isoformat()
    await _task(ravi, a, "In the portfolio", due_on=soon, assignee_id=ids["ravi"])
    await _task(ravi, b, "Outside it", due_on=soon, assignee_id=ids["ravi"])
    out = (await ravi.get(f"{B}/workload", params={"portfolio_id": folio})).json()
    titles = {t["title"] for t in out["tasks"]}
    assert "In the portfolio" in titles and "Outside it" not in titles
    everything = (await ravi.get(f"{B}/workload")).json()
    assert {"In the portfolio", "Outside it"} <= {t["title"] for t in everything["tasks"]}
