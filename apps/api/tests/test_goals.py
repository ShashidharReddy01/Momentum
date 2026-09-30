"""S6.3.1 Goals: create/edit/delete with undo, sub-goals without cycles, links (only what you can
see), progress from each source computed as the viewer, owner/admin editing, check-ins that move
the metric (undoable), and Mo's get_goals."""

from __future__ import annotations

from typing import Any

import httpx

from tests.helpers import Clients

Q4 = {"period_start": "2026-10-01", "period_end": "2026-12-31", "period_label": "Q4 2026"}


async def _project(c: httpx.AsyncClient, name: str = "Website Revamp") -> str:
    return next(
        p["id"] for p in (await c.get("/api/v1/projects")).json()["data"] if p["name"] == name
    )


async def _goal(c: httpx.AsyncClient, name: str, **body: Any) -> dict[str, Any]:
    r = await c.post("/api/v1/goals", json={"name": name, **Q4, **body})
    assert r.status_code == 201, r.text
    return r.json()["data"]  # type: ignore[no-any-return]


async def _task(c: httpx.AsyncClient, pid: str, done: bool) -> None:
    t = (await c.post(f"/api/v1/projects/{pid}/tasks", json={"title": "T"})).json()["data"]
    if done:
        await c.post(f"/api/v1/tasks/{t['id']}/complete")


async def test_manual_metric_progress_and_check_ins(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    g = await _goal(
        ravi,
        "Grow paying customers",
        metric={"type": "number", "start": 100, "target": 200, "current": 100, "unit": "customers"},
    )
    assert g["progress"] == 0.0 and g["can_edit"]

    r = await ravi.post(
        f"/api/v1/goals/{g['id']}/check-ins",
        json={"status": "on_track", "title": "Webinar funnel is converting", "current": 150},
    )
    assert r.status_code == 201, r.text
    d = (await ravi.get(f"/api/v1/goals/{g['id']}")).json()
    assert d["progress"] == 0.5 and d["status"] == "on_track" and d["metric"]["current"] == 150
    assert [
        u["title"] for u in (await ravi.get(f"/api/v1/goals/{g['id']}/check-ins")).json()["data"]
    ] == ["Webinar funnel is converting"]

    await ravi.post("/api/v1/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    d = (await ravi.get(f"/api/v1/goals/{g['id']}")).json()
    assert d["progress"] == 0.0 and d["status"] is None

    # a goal with no metric can't move one; with no source data progress is null, not 0
    bare = await _goal(ravi, "Be delightful")
    assert bare["progress"] is None
    r = await ravi.post(
        f"/api/v1/goals/{bare['id']}/check-ins",
        json={"status": "on_track", "title": "x", "current": 5},
    )
    assert r.status_code == 422 and r.json()["code"] == "no_metric"


async def test_project_progress_is_computed_as_the_viewer(as_user: Clients) -> None:
    ravi, mei = await as_user("ravi"), await as_user("mei")
    web = await _project(ravi)
    private = await _project(ravi, "Mobile App v2")  # mei can't see it
    before = {p: None for p in (web, private)}
    g = await _goal(ravi, "Ship the relaunch", progress_source="projects")
    for pid in before:
        r = await ravi.post(
            f"/api/v1/goals/{g['id']}/links", json={"entity_type": "project", "entity_id": pid}
        )
        assert r.status_code == 201, r.text
    # make the two projects' completion differ in a way we can check: add tasks to both
    for pid, done in ((web, True), (web, True), (private, False), (private, False)):
        await _task(ravi, pid, done)

    mine = (await ravi.get(f"/api/v1/goals/{g['id']}")).json()
    hers = (await mei.get(f"/api/v1/goals/{g['id']}")).json()
    assert {x["name"] for x in mine["links"]} == {"Website Revamp", "Mobile App v2"}
    assert [x["name"] for x in hers["links"]] == ["Website Revamp"]
    assert hers["hidden_links"] == 1 and "Mobile App v2" not in str(hers)
    web_only = next(x for x in mine["links"] if x["name"] == "Website Revamp")["progress"]
    assert hers["progress"] == web_only  # only what she can see counts
    assert mine["progress"] != hers["progress"]

    # linking needs you to see the project
    mei_goal = await _goal(mei, "Mei's goal", progress_source="projects")
    r = await mei.post(
        f"/api/v1/goals/{mei_goal['id']}/links",
        json={"entity_type": "project", "entity_id": private},
    )
    assert r.status_code == 404


async def test_subgoals_average_and_cannot_loop(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    parent = await _goal(ravi, "Win Q4", progress_source="subgoals")
    a = await _goal(
        ravi, "A", parent_id=parent["id"], metric={"start": 0, "target": 10, "current": 10}
    )
    await _goal(ravi, "B", parent_id=parent["id"], metric={"start": 0, "target": 10, "current": 0})
    d = (await ravi.get(f"/api/v1/goals/{parent['id']}")).json()
    assert d["progress"] == 0.5 and {c["name"] for c in d["children"]} == {"A", "B"}

    r = await ravi.patch(f"/api/v1/goals/{parent['id']}", json={"parent_id": a["id"]})
    assert r.status_code == 422 and r.json()["code"] == "goal_cycle"
    r = await ravi.delete(f"/api/v1/goals/{parent['id']}")
    assert r.status_code == 409 and r.json()["code"] == "has_subgoals"


async def test_edit_rights_undo_and_validation(as_user: Clients) -> None:
    ravi, mei, admin = await as_user("ravi"), await as_user("mei"), await as_user("admin")
    g = await _goal(ravi, "Cut churn")
    assert (await mei.patch(f"/api/v1/goals/{g['id']}", json={"name": "Mine"})).status_code == 403
    assert (
        await admin.patch(f"/api/v1/goals/{g['id']}", json={"period_label": "Q4"})
    ).status_code == 200

    r = await ravi.patch(
        f"/api/v1/goals/{g['id']}",
        json={
            "name": "Cut churn to 5%",
            "metric": {"type": "percent", "start": 8, "target": 5, "current": 6.5},
        },
    )
    assert r.status_code == 200 and r.json()["data"]["progress"] == 0.5  # a falling target works
    await ravi.post("/api/v1/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    d = (await ravi.get(f"/api/v1/goals/{g['id']}")).json()
    assert d["name"] == "Cut churn" and d["metric"] is None

    r = await ravi.post(
        "/api/v1/goals",
        json={"name": "x", "period_start": "2026-12-31", "period_end": "2026-10-01"},
    )
    assert r.status_code == 422

    r = await ravi.delete(f"/api/v1/goals/{g['id']}")
    assert r.status_code == 200 and (await ravi.get(f"/api/v1/goals/{g['id']}")).status_code == 404
    await ravi.post("/api/v1/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert (await ravi.get(f"/api/v1/goals/{g['id']}")).status_code == 200
