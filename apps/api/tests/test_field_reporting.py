"""S7.4.1 custom-field reporting across projects: dashboards filter by fields, add up and average a
number field, split by multi-select / people / checkbox fields, chart a custom date over time, and
every mark drills into exactly the tasks it counted. Search filters by fields too, and the bulk
value lookup serves My Tasks and search results."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx

from tests.helpers import Clients

B = "/api/v1"


async def _project(c: httpx.AsyncClient, name: str) -> str:
    return next(  # type: ignore[no-any-return]
        p["id"] for p in (await c.get(f"{B}/projects")).json()["data"] if p["name"] == name
    )


async def _field(c: httpx.AsyncClient, pid: str, **body: Any) -> dict[str, Any]:
    r = await c.post(f"{B}/projects/{pid}/fields", json=body)
    assert r.status_code == 201, r.text
    return r.json()["data"]  # type: ignore[no-any-return]


async def _task(c: httpx.AsyncClient, pid: str, title: str, **values: Any) -> str:
    t = (await c.post(f"{B}/projects/{pid}/tasks", json={"title": title})).json()["data"]
    for fid, v in values.items():
        r = await c.put(f"{B}/tasks/{t['id']}/fields/{fid}", json={"value": v})
        assert r.status_code == 200, r.text
    return t["id"]  # type: ignore[no-any-return]


async def _run(c: httpx.AsyncClient, kind: str, spec: dict[str, Any]) -> dict[str, Any]:
    r = await c.post(f"{B}/dashboards/query", json={"kind": kind, "query_spec": spec})
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


async def _drill(c: httpx.AsyncClient, spec: dict[str, Any], **point: Any) -> set[str]:
    r = await c.post(f"{B}/dashboards/drill", json={"query_spec": spec, **point})
    assert r.status_code == 200, r.text
    return {t["title"] for t in r.json()["tasks"]}


async def test_a_custom_field_report_across_two_projects(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    web, mobile = await _project(ravi, "Website Revamp"), await _project(ravi, "Mobile App v2")
    stage = await _field(
        ravi,
        web,
        name="Stage",
        type="single_select",
        options=[{"label": "Plan"}, {"label": "Ship"}],
    )
    plan, ship = (o["id"] for o in stage["options"])
    points = await _field(ravi, web, name="Points", type="number")
    areas = await _field(
        ravi, web, name="Areas", type="multi_select", options=[{"label": "UI"}, {"label": "API"}]
    )
    ui, api = (o["id"] for o in areas["options"])
    legal = await _field(ravi, web, name="Legal", type="checkbox")
    owners = await _field(ravi, web, name="Owners", type="people")
    launch = await _field(ravi, web, name="Launch", type="date")
    for f in (stage, points, areas, legal, owners, launch):
        r = await ravi.post(f"{B}/projects/{mobile}/fields/attach", json={"field_id": f["id"]})
        assert r.status_code in (200, 201), r.text
    me = (await ravi.get(f"{B}/me")).json()["user"]["id"]
    soon = (date.today() + timedelta(days=3)).isoformat()

    S, P, A, L, W, D = (f["id"] for f in (stage, points, areas, legal, owners, launch))
    await _task(ravi, web, "W1", **{S: ship, P: 3, A: [ui, api], L: True, W: [me], D: soon})
    await _task(ravi, web, "W2", **{S: plan, P: 5, A: [api]})
    await _task(ravi, mobile, "M1", **{S: ship, P: 8, A: [ui], D: soon})
    await _task(ravi, mobile, "M2", **{S: ship})  # no points

    shipping = {"filters": {"fields": [{"field_id": S, "op": "any", "values": [ship]}]}}
    # filtered across both projects, and described in words
    n = await _run(ravi, "count", shipping)
    assert n["value"] == 3
    assert "Stage: Ship" in n["description"]
    assert [x["label"] for x in n["filter_names"]] == ["Stage: Ship"]

    # total and average of a number field; tasks with no value are counted as such
    total = await _run(ravi, "count", {**shipping, "measure": "sum_field", "measure_field_id": P})
    assert (total["value"], total["unestimated"], total["measure_field_name"]) == (11, 1, "Points")
    assert total["description"].startswith("Total Points of open tasks")
    avg = await _run(ravi, "count", {**shipping, "measure": "avg_field", "measure_field_id": P})
    assert avg["value"] == 5.5

    # split by a multi-select: a task is in each group it holds; drills list exactly those
    set_on = {"filters": {"fields": [{"field_id": S, "op": "set"}]}}
    by_area = {**set_on, "group_by": "field", "field_id": A}
    bars = {g["label"]: g["tasks"] for g in (await _run(ravi, "bar", by_area))["groups"]}
    assert bars == {"UI": 2, "API": 2, "No value": 1}
    assert await _drill(ravi, by_area, key=ui) == {"W1", "M1"}
    assert await _drill(ravi, by_area, key="none") == {"M2"}

    # people and checkbox fields split too
    by_owner = {**set_on, "group_by": "field", "field_id": W}
    owners_bars = {g["label"]: g["tasks"] for g in (await _run(ravi, "bar", by_owner))["groups"]}
    assert owners_bars == {"Ravi Kumar": 1, "No value": 3}
    by_legal = {**set_on, "group_by": "field", "field_id": L, "measure": "sum_field"}
    by_legal["measure_field_id"] = P
    legal_bars = {g["label"]: g["value"] for g in (await _run(ravi, "bar", by_legal))["groups"]}
    assert legal_bars == {"Checked": 3, "Not checked": 13}
    assert await _drill(ravi, by_legal, key="true") == {"W1"}

    # a custom date over time
    line = await _run(
        ravi,
        "line",
        {**set_on, "time_bucket": "week", "time_field": "field", "time_field_id": D},
    )
    assert sum(p["tasks"] for p in line["series"]) == 2
    assert "by Launch per week" in line["description"]

    # a field that doesn't suit its use is refused with a reason
    for bad in (
        {"group_by": "field", "field_id": P},
        {"measure": "sum_field", "measure_field_id": S},
        {"time_bucket": "week", "time_field": "field", "time_field_id": P},
        {"filters": {"fields": [{"field_id": P, "op": "has", "value": "x"}]}},
    ):
        r = await ravi.post(f"{B}/dashboards/query", json={"kind": "count", "query_spec": bad})
        assert r.status_code == 422, (bad, r.text)


async def test_search_and_the_value_lookup_respect_visibility(as_user: Clients) -> None:
    ravi, tom = await as_user("ravi"), await as_user("tom")
    web, mobile = await _project(ravi, "Website Revamp"), await _project(ravi, "Mobile App v2")
    stage = await _field(ravi, web, name="Stage", type="single_select", options=[{"label": "Ship"}])
    ship = stage["options"][0]["id"]
    r = await ravi.post(f"{B}/projects/{mobile}/fields/attach", json={"field_id": stage["id"]})
    assert r.status_code in (200, 201), r.text
    public = await _task(ravi, web, "Shipping page", **{stage["id"]: ship})
    private = await _task(ravi, mobile, "Shipping app", **{stage["id"]: ship})
    flt = f"{stage['id']}:any:{ship}"

    # filters alone list matching tasks; with words they narrow the search
    hits = (await ravi.get(f"{B}/search", params={"field": flt})).json()
    assert {t["title"] for t in hits["tasks"]} == {"Shipping page", "Shipping app"}
    assert hits["projects"] == [] and hits["people"] == []
    hits = (await ravi.get(f"{B}/search", params={"q": "app", "field": flt})).json()
    assert {t["title"] for t in hits["tasks"]} == {"Shipping app"}
    bad = await ravi.get(f"{B}/search", params={"field": "nope"})
    assert bad.status_code == 422

    # tom can't see the private Mobile project: neither its task nor its values
    hers = (await tom.get(f"{B}/search", params={"field": flt})).json()
    assert "Shipping app" not in {t["title"] for t in hers["tasks"]}
    looked = await tom.post(f"{B}/field-values/lookup", json={"task_ids": [public, private]})
    assert looked.status_code == 200
    assert {v["task_id"] for v in looked.json()["data"]} <= {public}
    mine = await ravi.post(f"{B}/field-values/lookup", json={"task_ids": [public, private]})
    assert {v["task_id"] for v in mine.json()["data"]} == {public, private}
