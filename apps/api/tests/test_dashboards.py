"""S6.5.1 Dashboards: workspace and project dashboards with undo, widgets validated against
their kind, numbers computed as the viewer through the visibility clause, drill-downs that list
exactly the tasks a mark counted (Other included), time series with empty buckets, estimates, and
custom-field grouping."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx

from tests.helpers import Clients

B = "/api/v1"


async def _project(c: httpx.AsyncClient, name: str = "Website Revamp") -> str:
    return next(p["id"] for p in (await c.get(f"{B}/projects")).json()["data"] if p["name"] == name)


async def _team(c: httpx.AsyncClient, name: str = "Product") -> str:
    return next(t["id"] for t in (await c.get(f"{B}/teams")).json()["data"] if t["name"] == name)


async def _user_id(c: httpx.AsyncClient, local: str) -> str:
    people = (await c.get(f"{B}/users", params={"q": local})).json()["data"]
    return next(u["id"] for u in people if u["email"].startswith(f"{local}@"))


async def _fresh(c: httpx.AsyncClient, name: str = "Dash Lab") -> str:
    r = await c.post(f"{B}/projects", json={"team_id": await _team(c), "name": name})
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]  # type: ignore[no-any-return]


async def _task(c: httpx.AsyncClient, pid: str, title: str, **patch: Any) -> dict[str, Any]:
    t = (await c.post(f"{B}/projects/{pid}/tasks", json={"title": title})).json()["data"]
    if patch:
        r = await c.patch(f"{B}/tasks/{t['id']}", json=patch)
        assert r.status_code == 200, r.text
        t = r.json()["data"]
    return t  # type: ignore[no-any-return]


async def _run(
    c: httpx.AsyncClient, kind: str, spec: dict[str, Any], project_id: str | None = None
) -> dict[str, Any]:
    r = await c.post(
        f"{B}/dashboards/query",
        json={"kind": kind, "query_spec": spec, "project_id": project_id},
    )
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


async def _drill(c: httpx.AsyncClient, spec: dict[str, Any], **point: Any) -> dict[str, Any]:
    r = await c.post(f"{B}/dashboards/drill", json={"query_spec": spec, **point})
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


async def test_workspace_dashboard_starter_widgets_and_undo(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    r = await ravi.post(f"{B}/dashboards", json={"name": "Leadership"})
    assert r.status_code == 201, r.text
    d = r.json()["data"]
    kinds = [w["kind"] for w in d["widgets"]]
    assert d["scope"] == "workspace" and d["can_edit"]
    assert {"count", "bar", "line", "donut", "list"} <= set(kinds)
    for w in d["widgets"]:
        data = await ravi.get(f"{B}/dashboards/widgets/{w['id']}/data")
        assert data.status_code == 200, (w["title"], data.text)
        assert data.json()["description"]
    assert any(x["id"] == d["id"] for x in (await ravi.get(f"{B}/dashboards")).json()["data"])

    undo = await ravi.post(f"{B}/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert undo.status_code == 200, undo.text
    assert (await ravi.get(f"{B}/dashboards/{d['id']}")).status_code == 404


async def test_widget_add_update_move_remove_with_undo(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    d = (await ravi.post(f"{B}/dashboards", json={"name": "Mine", "starter": False})).json()["data"]
    assert d["widgets"] == []
    add = lambda body: ravi.post(f"{B}/dashboards/{d['id']}/widgets", json=body)  # noqa: E731
    a = await add({"kind": "count", "title": "Open", "query_spec": {}})
    b = await add(
        {
            "kind": "bar",
            "title": "By who",
            "query_spec": {"group_by": "assignee"},
            "viz": {"size": "lg"},
        }
    )
    assert a.status_code == 201 and b.status_code == 201, (a.text, b.text)
    wa, wb = a.json()["data"], b.json()["data"]
    assert wb["viz"] == {"size": "lg"}

    r = await ravi.patch(
        f"{B}/dashboards/widgets/{wb['id']}",
        json={"kind": "donut", "title": "Who has it"},
    )
    assert r.status_code == 200 and r.json()["data"]["kind"] == "donut", r.text
    await ravi.post(f"{B}/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    back = (await ravi.get(f"{B}/dashboards/{d['id']}")).json()["widgets"]
    assert [(w["kind"], w["title"]) for w in back] == [("count", "Open"), ("bar", "By who")]

    r = await ravi.post(f"{B}/dashboards/widgets/{wb['id']}/move", json={"before_id": wa["id"]})
    assert r.status_code == 200, r.text
    order = [w["title"] for w in (await ravi.get(f"{B}/dashboards/{d['id']}")).json()["widgets"]]
    assert order == ["By who", "Open"]
    await ravi.post(f"{B}/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    order = [w["title"] for w in (await ravi.get(f"{B}/dashboards/{d['id']}")).json()["widgets"]]
    assert order == ["Open", "By who"]

    r = await ravi.delete(f"{B}/dashboards/widgets/{wa['id']}")
    assert r.status_code == 200
    assert len((await ravi.get(f"{B}/dashboards/{d['id']}")).json()["widgets"]) == 1
    assert (await ravi.get(f"{B}/dashboards/widgets/{wa['id']}/data")).status_code == 404
    await ravi.post(f"{B}/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert len((await ravi.get(f"{B}/dashboards/{d['id']}")).json()["widgets"]) == 2


async def test_specs_are_validated_against_their_kind(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    d = (await ravi.post(f"{B}/dashboards", json={"name": "V", "starter": False})).json()["data"]
    url = f"{B}/dashboards/{d['id']}/widgets"
    bad = [
        {"kind": "bar", "title": "x", "query_spec": {}},  # no group_by
        {"kind": "line", "title": "x", "query_spec": {"time_bucket": "week"}},  # open + completed
        {"kind": "count", "title": "x", "query_spec": {"group_by": "assignee"}},
        {"kind": "bar", "title": "x", "query_spec": {"group_by": "title"}},  # not a dimension
        {"kind": "bar", "title": "x", "query_spec": {"group_by": "field"}},  # no field_id
        {"kind": "count", "title": "x", "query_spec": {"sql": "select 1"}},  # unknown key
        {"kind": "count", "title": "x", "query_spec": {"filters": {"assignees": ["1; drop"]}}},
        {"kind": "list", "title": "x", "query_spec": {"measure": "sum_estimate"}},
        {"kind": "count", "title": "x", "query_spec": {"version": 2}},
    ]
    for body in bad:
        r = await ravi.post(url, json=body)
        assert r.status_code == 422, (body, r.text)
    # a patch is checked against the widget's current spec
    w = (await ravi.post(url, json={"kind": "count", "title": "n", "query_spec": {}})).json()[
        "data"
    ]
    r = await ravi.patch(f"{B}/dashboards/widgets/{w['id']}", json={"kind": "bar"})
    assert r.status_code == 422, r.text
    # a text field can't be grouped by
    pid = await _project(ravi)
    field = (
        await ravi.post(f"{B}/projects/{pid}/fields", json={"name": "Notes", "type": "text"})
    ).json()["data"]
    r = await ravi.post(
        url,
        json={
            "kind": "bar",
            "title": "x",
            "query_spec": {"group_by": "field", "field_id": field["id"]},
        },
    )
    assert r.status_code == 422, r.text


async def test_numbers_are_computed_as_the_viewer(as_user: Clients) -> None:
    ravi, mei = await as_user("ravi"), await as_user("mei")
    board = (await ravi.post(f"{B}/dashboards", json={"name": "All work"})).json()["data"]
    by_project = next(w for w in board["widgets"] if w["query_spec"].get("group_by") == "project")

    mine = (await ravi.get(f"{B}/dashboards/widgets/{by_project['id']}/data")).json()
    hers = (await mei.get(f"{B}/dashboards/widgets/{by_project['id']}/data")).json()
    assert "Mobile App v2" in {g["label"] for g in mine["groups"]}
    assert "Mobile App v2" not in str(hers)  # private project: not named, not counted
    assert hers["tasks_total"] < mine["tasks_total"]

    # mei sees the dashboard (workspace-visible) but can't change it
    got = (await mei.get(f"{B}/dashboards/{board['id']}")).json()
    assert got["can_edit"] is False
    r = await mei.patch(f"{B}/dashboards/{board['id']}", json={"name": "Mine now"})
    assert r.status_code == 403
    r = await mei.post(
        f"{B}/dashboards/{board['id']}/widgets",
        json={"kind": "count", "title": "x", "query_spec": {}},
    )
    assert r.status_code == 403
    # a filter naming a project she can't see matches nothing (no error that confirms it exists)
    private = await _project(ravi, "Mobile App v2")
    spec = {"filters": {"project_ids": [private]}}
    assert (await _run(mei, "count", spec))["value"] == 0
    assert (await _run(ravi, "count", spec))["value"] > 0
    # running inside a project she can't see is a 404
    r = await mei.post(
        f"{B}/dashboards/query", json={"kind": "count", "query_spec": {}, "project_id": private}
    )
    assert r.status_code == 404


async def test_project_dashboard_follows_the_project(as_user: Clients) -> None:
    ravi, mei = await as_user("ravi"), await as_user("mei")
    private = await _project(ravi, "Mobile App v2")
    tab = (await ravi.get(f"{B}/dashboards/project/{private}")).json()
    assert tab["dashboard"] is None and tab["starter"] and tab["can_edit"]
    r = await ravi.post(f"{B}/dashboards", json={"name": "Mobile", "project_id": private})
    assert r.status_code == 201, r.text
    d = r.json()["data"]
    assert d["scope"] == "project" and len(d["widgets"]) == len(tab["starter"])
    again = await ravi.post(f"{B}/dashboards", json={"name": "Twice", "project_id": private})
    assert again.status_code == 409

    assert (await mei.get(f"{B}/dashboards/{d['id']}")).status_code == 404
    assert (await mei.get(f"{B}/dashboards/project/{private}")).status_code == 404
    w = d["widgets"][0]
    assert (await mei.get(f"{B}/dashboards/widgets/{w['id']}/data")).status_code == 404
    # a project dashboard always shows its own project
    r = await ravi.post(
        f"{B}/dashboards/{d['id']}/widgets",
        json={
            "kind": "count",
            "title": "x",
            "query_spec": {"filters": {"project_ids": [await _project(ravi)]}},
        },
    )
    assert r.status_code == 422

    # "reset" = delete: the tab shows the starter again; undo brings it back
    r = await ravi.delete(f"{B}/dashboards/{d['id']}")
    assert r.status_code == 200
    assert (await ravi.get(f"{B}/dashboards/project/{private}")).json()["dashboard"] is None
    await ravi.post(f"{B}/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert (await ravi.get(f"{B}/dashboards/project/{private}")).json()["dashboard"]["id"] == d[
        "id"
    ]


async def test_groups_status_and_drill_match_their_counts(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _fresh(ravi)
    me, ana = await _user_id(ravi, "ravi"), await _user_id(ravi, "ana")
    today = date.today()
    await _task(ravi, pid, "late", assignee_id=me, due_on=str(today - timedelta(days=3)))
    await _task(ravi, pid, "soon", assignee_id=me, due_on=str(today + timedelta(days=2)))
    await _task(ravi, pid, "later", assignee_id=ana, due_on=str(today + timedelta(days=30)))
    await _task(ravi, pid, "undated")
    done = await _task(ravi, pid, "done", assignee_id=ana)
    await ravi.post(f"{B}/tasks/{done['id']}/complete")

    status = await _run(ravi, "donut", {"group_by": "status", "filters": {"status": "all"}}, pid)
    assert [(g["key"], g["value"]) for g in status["groups"]] == [
        ("overdue", 1),
        ("due_soon", 1),
        ("later", 1),
        ("no_date", 1),
        ("completed", 1),
    ]
    assert status["total"] == 5

    spec = {"group_by": "assignee"}
    who = await _run(ravi, "bar", spec, pid)
    counts = {g["key"]: g["value"] for g in who["groups"]}
    assert counts == {me: 2, ana: 1, "none": 1}
    assert next(g for g in who["groups"] if g["key"] == "none")["label"] == "Unassigned"
    for g in who["groups"]:
        got = await _drill(ravi, spec, project_id=pid, key=g["key"])
        assert got["total"] == g["value"] and len(got["tasks"]) == g["value"], g
    mine = await _drill(ravi, spec, project_id=pid, key=me)
    assert [t["title"] for t in mine["tasks"]] == ["late", "soon"]  # due soonest first
    assert mine["tasks"][0]["key"].startswith("T-")

    # past the limit, the rest fold into Other, and Other drills to exactly those tasks
    folded = {"group_by": "assignee", "limit": 1}
    top = await _run(ravi, "bar", folded, pid)
    assert [g["key"] for g in top["groups"]] == [me, "other"]
    assert top["groups"][1]["value"] == 2 and top["groups"][1]["label"] == "Other"
    other = await _drill(ravi, folded, project_id=pid, key="other")
    assert {t["title"] for t in other["tasks"]} == {"later", "undated"}

    overdue = await _run(ravi, "list", {"filters": {"overdue": True}}, pid)
    assert [t["title"] for t in overdue["tasks"]] == ["late"] and overdue["more"] == 0


async def test_series_fill_empty_buckets_and_drill_by_bucket(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _fresh(ravi, "Series Lab")
    for title in ("a", "b"):
        t = await _task(ravi, pid, title)
        await ravi.post(f"{B}/tasks/{t['id']}/complete")
    spec = {
        "filters": {"status": "completed"},
        "time_bucket": "week",
        "time_field": "completed",
        "window_days": 28,
    }
    out = await _run(ravi, "line", spec, pid)
    assert len(out["series"]) in (4, 5)  # every week in the window, empty ones as 0
    last = out["series"][-1]
    assert last["value"] == 2 and all(p["value"] == 0 for p in out["series"][:-1])
    got = await _drill(ravi, spec, project_id=pid, bucket_start=last["start"])
    assert got["total"] == 2 and {t["title"] for t in got["tasks"]} == {"a", "b"}
    empty = await _drill(ravi, spec, project_id=pid, bucket_start=out["series"][0]["start"])
    assert empty["total"] == 0


async def test_estimates_and_custom_field_groups(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _fresh(ravi, "Effort Lab")
    await _task(ravi, pid, "big", estimate_minutes=240)
    await _task(ravi, pid, "small", estimate_minutes=60)
    t = await _task(ravi, pid, "unknown")
    hours = await _run(ravi, "count", {"measure": "sum_estimate"}, pid)
    assert hours["value"] == 300 and hours["unestimated"] == 1
    assert hours["description"].startswith("Estimated hours of open tasks")

    field = (
        await ravi.post(
            f"{B}/projects/{pid}/fields",
            json={
                "name": "Stage",
                "type": "single_select",
                "options": [
                    {"label": "Build", "color": "#ff0000"},
                    {"label": "Ship", "color": "#00ff00"},
                ],
            },
        )
    ).json()["data"]
    build = field["options"][0]["id"]
    r = await ravi.put(f"{B}/tasks/{t['id']}/fields/{field['id']}", json={"value": build})
    assert r.status_code == 200, r.text
    spec = {"group_by": "field", "field_id": field["id"]}
    out = await _run(ravi, "bar", spec, pid)
    assert {(g["label"], g["value"]) for g in out["groups"]} == {("Build", 1), ("No value", 2)}
    assert "by Stage" in out["description"]
    got = await _drill(ravi, spec, project_id=pid, key=build)
    assert [x["title"] for x in got["tasks"]] == ["unknown"]


async def test_filter_names_are_what_the_viewer_may_see(as_user: Clients) -> None:
    """The editor shows a chart's narrowing filters by name (2026-10-01): a project the viewer
    can't see is named generically, never by its real name."""
    ravi, mei = await as_user("ravi"), await as_user("mei")
    web, hidden = await _project(ravi), await _project(ravi, "Mobile App v2")  # mei: not a member
    me = await _user_id(ravi, "ravi")
    spec = {
        "filters": {
            "project_ids": [web, hidden],
            "assignees": ["me", "none", me],
            "priorities": ["urgent"],
        }
    }
    names = {
        (n["filter"], n["key"]): n["label"]
        for n in (await _run(ravi, "count", spec))["filter_names"]
    }
    assert names[("project_ids", web)] == "Website Revamp"
    assert names[("project_ids", hidden)] == "Mobile App v2"
    assert names[("assignees", "me")] == "Me" and names[("assignees", "none")] == "Unassigned"
    assert names[("assignees", me)].startswith("Ravi")
    assert names[("priorities", "urgent")] == "Urgent"
    hers = {
        (n["filter"], n["key"]): n["label"]
        for n in (await _run(mei, "count", spec))["filter_names"]
    }
    assert hers[("project_ids", hidden)] == "A project you can't see"
    assert hers[("project_ids", web)] == "Website Revamp"
