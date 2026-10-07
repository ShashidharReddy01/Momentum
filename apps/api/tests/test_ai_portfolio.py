"""Phase 7.5 S75-10: Mo on portfolios and dashboards (spec §8), on the customer onboarding seed.

A brief never names a project the viewer can't see and states only numbers from its facts; the
read tools count like the portfolio table; plain-English filters resolve names and dates as the
viewer and ask back with real options; a drafted dashboard previews real numbers and is created
only when the person posts it; a chart's explanation cites its own data; the readiness check reads
files only when ticked; a handoff is a preview until posted. Nothing is written without confirm.
"""

from __future__ import annotations

import calendar
import json
import uuid
from datetime import date
from typing import Any

import httpx
from sqlalchemy import delete, func, select, update

from momentum.core.activity import Activity
from momentum.core.db import UnitOfWork
from momentum.core.settings import Settings
from momentum.domain.dashboards.models import Dashboard
from momentum.domain.portfolios.models import Portfolio
from momentum.domain.portfolios.rows import ViewSpec, portfolio_rows_v2
from momentum.domain.projects.models import Project, ProjectMember
from momentum.domain.status_updates.models import StatusUpdate
from momentum.seed_onboarding import PORTFOLIO_NAME, SMALL_DISTRIBUTION, seed_onboarding
from tests.ai_fixtures import call
from tests.helpers import Clients, ctx_for

B = "/api/v1"


async def _onboard(uow: UnitOfWork, settings: Settings, *, files: bool = False) -> uuid.UUID:
    async with uow.transaction() as s:
        await seed_onboarding(
            s, settings, distribution=SMALL_DISTRIBUTION, files=files, backfill_days=30
        )
        return (
            await s.execute(select(Portfolio.id).where(Portfolio.name == PORTFOLIO_NAME))
        ).scalar_one()


async def _hide_one_from(uow: UnitOfWork, settings: Settings, local: str, folio: uuid.UUID) -> str:
    """Make one customer private and take ``local`` off it: in the portfolio, not visible."""
    who = await ctx_for(uow, settings, local)
    owner = await ctx_for(uow, settings, "sofia")  # sees every customer; takes the hidden one
    async with uow.transaction() as s:
        p = await s.get(Portfolio, folio)
        assert p is not None
        rows = (await portfolio_rows_v2(s, owner, p, ViewSpec())).rows
        name = str(sorted(r["name"] for r in rows)[0])
        await s.execute(
            update(Project)
            .where(Project.name == name)
            .values(privacy="private", owner_id=owner.actor.id)
        )
        pid = (await s.execute(select(Project.id).where(Project.name == name))).scalar_one()
        await s.execute(
            delete(ProjectMember).where(
                ProjectMember.project_id == pid, ProjectMember.user_id == who.actor.id
            )
        )
    return name


async def _count(uow: UnitOfWork, model: Any) -> int:
    async with uow.transaction() as s:
        return int((await s.execute(select(func.count()).select_from(model))).scalar_one())


async def _rows(c: httpx.AsyncClient, folio: uuid.UUID, filters: Any = None) -> dict[str, Any]:
    params = {"filters": json.dumps(filters)} if filters is not None else {}
    r = await c.get(f"{B}/portfolios/{folio}/rows", params=params)
    assert r.status_code == 200, r.text
    return dict(r.json())


async def test_a_brief_never_names_a_hidden_project_and_writes_nothing(
    uow: UnitOfWork, settings: Settings, as_user: Clients
) -> None:
    folio = await _onboard(uow, settings)
    hidden = await _hide_one_from(uow, settings, "ravi", folio)
    ravi = await as_user("ravi")
    visible = {r["name"] for r in (await _rows(ravi, folio))["rows"]}
    assert hidden not in visible
    before = (await _count(uow, StatusUpdate), await _count(uow, Activity))

    r = await ravi.post(f"{B}/ai/portfolios/{folio}/brief")
    assert r.status_code == 200, r.text
    b = r.json()
    assert hidden not in r.text  # never named, only counted
    assert b["hidden"] == 1 and b["ai"] is True
    assert len(b["items"]) >= 4
    for item in b["items"]:
        assert item["cites"]  # every kept item cites something real
        assert "987654" not in item["text"]  # the invented number was dropped
        assert "dropped" not in item["text"]
    named = {c for i in b["items"] for c in i["cites"]} & (visible | {hidden})
    assert named and named <= visible
    assert any(i["project_ids"] for i in b["items"])
    # nothing was written: the brief is a preview
    assert (await _count(uow, StatusUpdate), await _count(uow, Activity)) == before

    # "Post as status update" goes through the normal endpoint after the preview
    draft = b["status_update"]
    assert draft["generated_by_ai"] is True and draft["title"].startswith("Portfolio brief")
    posted = await ravi.post(f"{B}/portfolios/{folio}/status-updates", json=draft)
    assert posted.status_code == 201, posted.text
    assert await _count(uow, StatusUpdate) == before[0] + 1

    # someone who sees none of it gets no model call and no names
    priya = await as_user("priya")
    out = (await priya.post(f"{B}/ai/portfolios/{folio}/brief")).json()
    assert out["ai"] is False and out["items"] == [] and out["hidden"] >= 1


async def test_read_tools_count_like_the_table_and_hide_what_you_cant_see(
    uow: UnitOfWork, settings: Settings, as_user: Clients
) -> None:
    folio = await _onboard(uow, settings)
    hidden = await _hide_one_from(uow, settings, "ravi", folio)
    ctx = await ctx_for(uow, settings, "ravi")
    table = (await _rows(await as_user("ravi"), folio))["rows"]

    out = await call(uow, ctx, "get_portfolio_rows", {"portfolio": PORTFOLIO_NAME})
    assert out.ok, out.result.error
    data = out.result.data
    assert data["projects_you_cannot_see"] == 1
    assert hidden not in json.dumps(data)
    by_name = {r["name"]: r for r in table}
    assert {p["name"] for p in data["projects"]} == set(by_name)
    for p in data["projects"]:
        row = by_name[p["name"]]
        assert p.get("overdue") == row["overdue"] and p.get("open") == row["open"]
        assert p.get("stage") == (row["stage"] or {}).get("label")

    impl = await call(
        uow, ctx, "get_portfolio_rows", {"portfolio": "customer", "stages": ["Implementation"]}
    )
    assert impl.ok and all(p["stage"] == "Implementation" for p in impl.result.data["projects"])
    bad = await call(
        uow, ctx, "get_portfolio_rows", {"portfolio": PORTFOLIO_NAME, "stages": ["Pilot"]}
    )
    assert not bad.ok and "Discovery" in bad.result.error["message"]  # type: ignore[index]

    metrics = await call(uow, ctx, "get_stage_metrics", {"portfolio": PORTFOLIO_NAME})
    assert metrics.ok, metrics.result.error
    m = metrics.result.data
    assert [s["stage"] for s in m["funnel"]][:3] == ["Pre-sales", "Discovery", "Contracts"]
    assert {"aging", "time_in_stage"} <= set(m)
    assert sum(a["projects"] for a in m["aging"]) <= len(table)


async def test_filters_resolve_as_the_viewer_and_ask_back_with_real_options(
    uow: UnitOfWork, settings: Settings, as_user: Clients
) -> None:
    folio = await _onboard(uow, settings)
    ravi = await as_user("ravi")
    r = await ravi.post(
        f"{B}/ai/filters",
        json={
            "text": "Implementations going live in November that are at risk",
            "surface": "portfolio",
            "portfolio_id": str(folio),
        },
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["question"] is None
    f = d["filters"]
    assert f["status"] == ["at_risk"] and len(f["stage"]) == 1
    today = date.today()
    year = today.year if today.month <= 11 else today.year + 1
    bounds = sorted((c["op"], c["value"]) for c in f["fields"])
    assert bounds == [
        ("gte", f"{year}-11-01"),
        ("lte", f"{year}-11-{calendar.monthrange(year, 11)[1]}"),
    ]
    assert d["chips"][0]["label"].startswith("Health")
    # the draft is the view's own schema: the rows endpoint takes it as it is
    rows = await _rows(ravi, folio, f)
    assert all(x["status"] == "at_risk" for x in rows["rows"])

    ask = (
        await ravi.post(
            f"{B}/ai/filters",
            json={
                "text": "Anything in the Pilot stage",
                "surface": "portfolio",
                "portfolio_id": str(folio),
            },
        )
    ).json()
    assert "Pilot" in ask["question"] and {"Discovery", "Implementation"} <= set(ask["options"])
    # someone who can't see the portfolio's projects still can't see other portfolios
    missing = await ravi.post(
        f"{B}/ai/filters",
        json={"text": "x", "surface": "portfolio", "portfolio_id": str(uuid.uuid4())},
    )
    assert missing.status_code == 404


async def test_a_dashboard_draft_previews_real_numbers_and_is_created_only_on_post(
    uow: UnitOfWork, settings: Settings, as_user: Clients
) -> None:
    folio = await _onboard(uow, settings)
    ravi = await as_user("ravi")
    sentence = (
        "A dashboard for my implementations: go-lives next 90 days, slipping projects, "
        "waiting on customer by age, RAID by severity"
    )
    before = await _count(uow, Dashboard)
    r = await ravi.post(f"{B}/ai/dashboards/draft", json={"text": sentence})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["question"] is None and d["portfolio_id"] == str(folio)
    assert d["filters"]["owner"] == ["me"]
    assert [w["title"] for w in d["widgets"]][1] == "Slipping projects"  # renamed by Mo
    assert len(d["widgets"]) == 4 and all(w["result"] is not None for w in d["widgets"])
    assert await _count(uow, Dashboard) == before  # a preview saves nothing

    made = await ravi.post(
        f"{B}/dashboards/from-draft",
        json={
            "name": d["name"],
            "filters": d["filters"],
            "widgets": [
                {k: w[k] for k in ("kind", "title", "query_spec", "viz")} for w in d["widgets"]
            ],
            "prompt": sentence,
        },
    )
    assert made.status_code == 201, made.text
    board = made.json()["data"]
    assert len(board["widgets"]) == 4
    assert all(w["created_from_prompt"] == sentence for w in board["widgets"])
    undo = await ravi.post(f"{B}/undo", json={"activity_id": made.json()["meta"]["activity_id"]})
    assert undo.status_code == 200, undo.text
    assert (await ravi.get(f"{B}/dashboards/{board['id']}")).status_code == 404

    # a spec that doesn't validate is refused on create, like any widget
    bad = await ravi.post(
        f"{B}/dashboards/from-draft",
        json={
            "name": "x",
            "widgets": [
                {"kind": "funnel", "title": "x", "query_spec": d["widgets"][0]["query_spec"]}
            ],
            "prompt": "x",
        },
    )
    assert bad.status_code == 422
    # asked back when it can't tell which portfolio
    ask = (
        await ravi.post(
            f"{B}/ai/dashboards/draft", json={"text": "A control tower for Partner rollouts"}
        )
    ).json()
    assert ask["question"] and PORTFOLIO_NAME in ask["options"]


async def test_explaining_a_chart_cites_its_own_data(
    uow: UnitOfWork, settings: Settings, as_user: Clients
) -> None:
    await _onboard(uow, settings)
    ravi = await as_user("ravi")
    pinned = (await ravi.get(f"{B}/dashboards/pinned")).json()["data"]
    board = next(x for x in pinned if x["template"] == "implementation_lead")
    detail = (await ravi.get(f"{B}/dashboards/{board['id']}")).json()
    w = next(x for x in detail["widgets"] if x["title"].startswith("Waiting on customer"))
    data = (await ravi.get(f"{B}/dashboards/widgets/{w['id']}/data")).json()
    r = await ravi.post(f"{B}/ai/dashboards/widgets/{w['id']}/explain", json={})
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["ai"] is True and len(e["paragraphs"]) == 2
    labels = {g["label"] for g in data["groups"]} | {w["title"]}
    assert all(set(p["cites"]) & labels or p["cites"] for p in e["paragraphs"])
    assert "987654" not in r.text and "cites nothing" not in r.text
    assert e["links"] and all(lk["kind"] == "task" for lk in e["links"])
    # a note has nothing to explain
    note = await ravi.post(
        f"{B}/dashboards/{board['id']}/widgets",
        json={
            "kind": "note",
            "title": "Read me",
            "query_spec": {"version": 2, "entity": "note", "text": "hi"},
        },
    )
    assert note.status_code == 201, note.text
    nid = note.json()["data"]["id"]
    assert (await ravi.post(f"{B}/ai/dashboards/widgets/{nid}/explain", json={})).status_code == 422


async def test_readiness_reads_files_only_when_ticked_and_handoff_is_a_preview(
    uow: UnitOfWork, settings: Settings, as_user: Clients
) -> None:
    folio = await _onboard(uow, settings, files=True)
    ravi = await as_user("ravi")
    rows = (await _rows(ravi, folio))["rows"]
    live = next(r for r in rows if (r["stage"] or {}).get("label") in ("Hypercare", "Live"))
    detail = (await ravi.get(f"{B}/portfolios/{folio}")).json()
    stage_field = detail["stage_field_id"]
    options = next(
        f for f in (await ravi.get(f"{B}/project-fields")).json()["data"] if f["id"] == stage_field
    )["options"]
    impl = next(o["id"] for o in options if o["label"] == "Implementation")
    url = f"{B}/ai/portfolios/{folio}/projects/{live['id']}/readiness"

    plain = (await ravi.post(url, json={"to": impl})).json()
    assert plain["ai"] is False and plain["notes"] == [] and plain["files_read"] == []
    assert [i["kind"] for i in plain["readiness"]["items"]] == ["field", "milestone", "file"]
    read = (await ravi.post(url, json={"to": impl, "read_files": True})).json()
    assert read["ai"] is True and len(read["files_read"]) == 1
    assert read["files_read"][0].startswith("Contract signed")
    assert len(read["notes"]) == 1 and read["files_read"][0] in read["notes"][0]["cites"]

    before = (await _count(uow, StatusUpdate), await _count(uow, Activity))
    h = await ravi.post(f"{B}/ai/projects/{live['id']}/handoff", json={"to_stage": "Live"})
    assert h.status_code == 200, h.text
    note = h.json()
    assert {"sold", "scope", "commitments", "contacts", "risks"} <= set(note["sections"])
    assert "987654" not in h.text and "cites nothing" not in h.text
    assert note["status_update"]["title"] == f"Handoff to Live: {live['name']}"
    assert (await _count(uow, StatusUpdate), await _count(uow, Activity)) == before
    posted = await ravi.post(
        f"{B}/projects/{live['id']}/status-updates", json=note["status_update"]
    )
    assert posted.status_code == 201, posted.text
    assert posted.json()["data"]["generated_by_ai"] is True

    # someone who can't see the project gets nothing
    priya = await as_user("priya")
    assert (await priya.post(f"{B}/ai/projects/{live['id']}/handoff", json={})).status_code == 404
    assert (await priya.post(url, json={"to": impl})).status_code == 404
