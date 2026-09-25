"""S2.4.3 Milestones: convert task <-> milestone, permissions, and undo."""

from __future__ import annotations

from tests.helpers import Clients


async def _project(c, name: str = "Website Revamp") -> str:  # type: ignore[no-untyped-def]
    return next(
        p["id"] for p in (await c.get("/api/v1/projects")).json()["data"] if p["name"] == name
    )


async def _task(c, pid: str) -> dict:  # type: ignore[no-untyped-def]
    r = await c.post(f"/api/v1/projects/{pid}/tasks", json={"title": "T"})
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def test_convert_to_milestone_and_back(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    t = await _task(ravi, pid)
    assert t["type"] == "task"

    r = await ravi.post(f"/api/v1/tasks/{t['id']}/convert", json={"type": "milestone"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["type"] == "milestone"

    r2 = await ravi.post(f"/api/v1/tasks/{t['id']}/convert", json={"type": "task"})
    assert r2.status_code == 200
    assert r2.json()["data"]["type"] == "task"


async def test_converting_to_the_same_type_is_a_noop(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    t = await _task(ravi, pid)
    r = await ravi.post(f"/api/v1/tasks/{t['id']}/convert", json={"type": "task"})
    assert r.status_code == 200
    assert r.json()["meta"]["activity_id"] is None


async def test_approval_type_is_not_a_valid_conversion_target(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    t = await _task(ravi, pid)
    r = await ravi.post(f"/api/v1/tasks/{t['id']}/convert", json={"type": "approval"})
    assert r.status_code == 422


async def test_editor_access_required_to_convert(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    t = await _task(ravi, pid)
    kim = await as_user("kim")  # not on the Product team
    r = await kim.post(f"/api/v1/tasks/{t['id']}/convert", json={"type": "milestone"})
    assert r.status_code in (403, 404)


async def test_undo_convert(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    t = await _task(ravi, pid)
    r = await ravi.post(f"/api/v1/tasks/{t['id']}/convert", json={"type": "milestone"})
    activity_id = r.json()["meta"]["activity_id"]

    u = await ravi.post("/api/v1/undo", json={"activity_id": activity_id})
    assert u.status_code == 200
    after = await ravi.get(f"/api/v1/tasks/{t['id']}")
    assert after.json()["type"] == "task"
