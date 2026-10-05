"""S6.5.2 Ask for a chart: a question becomes a validated dashboard spec whose numbers the server
counts as the asker; names resolve only among what the asker can see, anything else is asked
back; the draft saves as a widget that remembers its question; Mo's ``query_metrics`` counts the
same way. The phase exit's 15 fixture questions live in ``momentum/ai/evals/cases/chart.yaml``."""

from __future__ import annotations

from typing import Any

import httpx

from momentum.core.db import UnitOfWork
from tests.ai_fixtures import World, call, world
from tests.helpers import Clients

_ = world
B = "/api/v1"


async def _project(c: httpx.AsyncClient, name: str = "Website Revamp") -> str:
    return next(p["id"] for p in (await c.get(f"{B}/projects")).json()["data"] if p["name"] == name)


async def _ask(c: httpx.AsyncClient, text: str, project_id: str | None = None) -> dict[str, Any]:
    r = await c.post(f"{B}/ai/dashboards/query", json={"text": text, "project_id": project_id})
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


async def test_a_question_becomes_a_chart_counted_as_the_asker(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    out = await _ask(ravi, "Show open tasks by assignee", pid)
    assert out["question"] is None
    assert out["kind"] == "bar" and out["query_spec"]["group_by"] == "assignee"
    groups = out["result"]["groups"]
    # the numbers are the server's: the same spec run through the dashboard endpoint agrees
    again = await ravi.post(
        f"{B}/dashboards/query",
        json={"kind": "bar", "query_spec": out["query_spec"], "project_id": pid},
    )
    assert again.json()["groups"] == groups
    assert sum(g["value"] for g in groups) == out["result"]["tasks_total"]

    # saved as a widget, it remembers the question it was asked with
    board = (
        await ravi.post(
            f"{B}/dashboards", json={"name": "Web", "project_id": pid, "starter": False}
        )
    ).json()["data"]
    r = await ravi.post(
        f"{B}/dashboards/{board['id']}/widgets",
        json={
            "kind": out["kind"],
            "title": out["title"],
            "query_spec": out["query_spec"],
            "created_from_prompt": "Show open tasks by assignee",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["data"]["created_from_prompt"] == "Show open tasks by assignee"
    got = (await ravi.get(f"{B}/dashboards/{board['id']}")).json()["widgets"]
    assert got[0]["created_from_prompt"] == "Show open tasks by assignee"


async def test_it_asks_rather_than_guesses(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    # something a task chart can't show
    assert "revenue" in (await _ask(ravi, "Chart our revenue by quarter", pid))["question"]
    # a person who doesn't exist
    zed = await _ask(ravi, "How many tasks for Zed?", pid)
    assert zed["question"] and "Zed" in zed["question"] and zed["result"] is None
    # a field that isn't a single-select here
    assert "single-select" in (await _ask(ravi, "Open tasks by vendor field", pid))["question"]


async def test_a_split_count_becomes_a_bar(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    out = await _ask(ravi, "Open task count per assignee", await _project(ravi))
    assert out["kind"] == "bar" and out["query_spec"]["group_by"] == "assignee"


async def test_names_resolve_only_among_what_the_asker_can_see(as_user: Clients) -> None:
    ravi, mei = await as_user("ravi"), await as_user("mei")
    # a private project mei isn't in: asking inside it is a 404, naming it is a question
    private = await _project(ravi, "Mobile App v2")
    r = await mei.post(
        f"{B}/ai/dashboards/query", json={"text": "Open tasks", "project_id": private}
    )
    assert r.status_code == 404
    out = await _ask(mei, "How many open tasks in secret plans?")
    assert out["question"] is not None and out["result"] is None


async def test_query_metrics_counts_like_a_chart(uow: UnitOfWork, world: World) -> None:
    out = await call(
        uow, world.ravi, "query_metrics", {"group_by": "assignee", "projects": ["AI Tools Lab"]}
    )
    assert out.ok, out.result.error
    metrics = out.result.data["metrics"]
    assert metrics["unit"] == "tasks" and metrics["tasks_matched"] == 2  # copy + faq
    assert [g["value"] for g in metrics["groups"]] == [2]
    listed = await call(
        uow, world.ravi, "query_metrics", {"kind": "list", "projects": ["AI Tools Lab"]}
    )
    assert {t["title"] for t in listed.result.data["metrics"]["tasks"]} == {
        "Draft pricing copy",
        "Draft pricing FAQ",
    }
    # priya's private project: ravi can't count it, and the tool says so instead of guessing
    hidden = await call(uow, world.ravi, "query_metrics", {"projects": ["Secret Plans"]})
    assert not hidden.ok
    assert "Draft pricing secret" not in str(hidden.result.to_json())


async def test_charts_by_custom_fields_resolve_names_to_ids(as_user: Clients) -> None:
    """S7.4.1: Mo can total a number field, split by a multi-select and filter by an option, all
    in names; an option that doesn't exist is asked back with the real ones."""
    ravi = await as_user("ravi")
    pid = await _project(ravi)

    async def field(**body: Any) -> dict[str, Any]:
        r = await ravi.post(f"{B}/projects/{pid}/fields", json=body)
        assert r.status_code == 201, r.text
        return r.json()["data"]  # type: ignore[no-any-return]

    stage = await field(
        name="Stage", type="single_select", options=[{"label": "Plan"}, {"label": "Ship"}]
    )
    areas = await field(
        name="Areas", type="multi_select", options=[{"label": "UI"}, {"label": "API"}]
    )
    points = await field(name="Points", type="number")
    ship = stage["options"][1]["id"]
    for title, pts, opt in (
        ("Shipping A", 3, ship),
        ("Shipping B", 5, ship),
        ("Planning", 8, None),
    ):
        t = (await ravi.post(f"{B}/projects/{pid}/tasks", json={"title": title})).json()["data"]
        await ravi.put(f"{B}/tasks/{t['id']}/fields/{points['id']}", json={"value": pts})
        if opt:
            await ravi.put(f"{B}/tasks/{t['id']}/fields/{stage['id']}", json={"value": opt})
        await ravi.put(
            f"{B}/tasks/{t['id']}/fields/{areas['id']}", json={"value": [areas["options"][0]["id"]]}
        )

    out = await _ask(ravi, "What are the total points of tasks in the Ship stage?", pid)
    assert out["question"] is None, out["question"]
    spec = out["query_spec"]
    assert spec["measure"] == "sum_field" and spec["measure_field_id"] == points["id"]
    assert spec["filters"]["fields"][0]["values"] == [ship]
    assert out["result"]["value"] == 8

    bars = await _ask(ravi, "Show open tasks by area", pid)
    assert bars["query_spec"]["field_id"] == areas["id"]
    assert any(g["label"] == "UI" and g["tasks"] >= 3 for g in bars["result"]["groups"])

    asked = await _ask(ravi, "How many tasks in the Launched stage?", pid)
    assert asked["question"] and "Plan" in asked["question"] and "Ship" in asked["question"]
