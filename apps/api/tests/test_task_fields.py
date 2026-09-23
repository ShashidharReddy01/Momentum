"""S1.2.3 Assignee and dates: validation, derived due_on, auto-follow, events, undo."""

from __future__ import annotations

from sqlalchemy import select

from momentum.core.db import UnitOfWork
from momentum.core.events import OutboxEvent
from momentum.domain.tasks.models import Follower
from tests.helpers import Clients, uid, user_by_local


async def _task(c) -> dict:  # type: ignore[no-untyped-def]
    pid = next(
        p["id"]
        for p in (await c.get("/api/v1/projects")).json()["data"]
        if p["name"] == "Website Revamp"
    )
    r = await c.post(f"/api/v1/projects/{pid}/tasks", json={"title": "Fields"})
    assert r.status_code == 201, r.text
    return r.json()["data"]  # type: ignore[no-any-return]


async def test_assign_follows_emits_and_undo(as_user: Clients, uow: UnitOfWork) -> None:
    ravi = await as_user("ravi")
    ana = await user_by_local(uow, "ana")
    t = await _task(ravi)
    r = await ravi.patch(f"/api/v1/tasks/{t['id']}", json={"assignee_id": str(ana.id)})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["assignee_id"] == str(ana.id)
    async with uow.transaction() as s:
        assert await s.get(Follower, (uid(t["id"]), ana.id)) is not None
        ev = (
            await s.execute(
                select(OutboxEvent).where(
                    OutboxEvent.type == "task.assigned", OutboxEvent.entity_id == uid(t["id"])
                )
            )
        ).scalar_one()
        assert ev.payload["data"]["assignee_id"] == str(ana.id)
        assert f"user:{ana.id}" in ev.payload["channels"]
    await ravi.post("/api/v1/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert (await ravi.get(f"/api/v1/tasks/{t['id']}")).json()["assignee_id"] is None
    # unassign is a no-op when already empty
    r = await ravi.patch(f"/api/v1/tasks/{t['id']}", json={"assignee_id": None})
    assert r.json()["meta"]["activity_id"] is None


async def test_invalid_assignee(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    t = await _task(ravi)
    r = await ravi.patch(
        f"/api/v1/tasks/{t['id']}", json={"assignee_id": "00000000-0000-7000-8000-000000000000"}
    )
    assert r.status_code == 422 and r.json()["code"] == "invalid_assignee"


async def test_dates_validation_and_derivation(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    t = await _task(ravi)
    url = f"/api/v1/tasks/{t['id']}"
    r = await ravi.patch(url, json={"start_on": "2026-10-05", "due_on": "2026-10-01"})
    assert r.status_code == 422 and r.json()["code"] == "dates_out_of_order"
    r = await ravi.patch(url, json={"start_on": "2026-10-01", "due_on": "2026-10-05"})
    assert r.status_code == 200
    # start after an existing due date is rejected too
    r = await ravi.patch(url, json={"start_on": "2026-10-09"})
    assert r.status_code == 422
    # due_at alone derives due_on (actor timezone is UTC in the seed)
    r = await ravi.patch(url, json={"due_at": "2026-10-07T23:30:00-02:00"})
    d = r.json()["data"]
    assert d["due_on"] == "2026-10-08" and d["due_at"].startswith("2026-10-08T01:30")
    # clearing due_on clears the time
    r = await ravi.patch(url, json={"due_on": None})
    d = r.json()["data"]
    assert d["due_on"] is None and d["due_at"] is None and d["start_on"] == "2026-10-01"
    # naive datetimes are rejected
    r = await ravi.patch(url, json={"due_at": "2026-10-07T10:00:00"})
    assert r.status_code == 422


async def test_date_change_undo_restores_all_fields(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    t = await _task(ravi)
    url = f"/api/v1/tasks/{t['id']}"
    await ravi.patch(url, json={"due_on": "2026-10-05", "due_at": "2026-10-05T17:00:00Z"})
    r = await ravi.patch(url, json={"due_on": "2026-11-01", "due_at": None})
    await ravi.post("/api/v1/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    d = (await ravi.get(url)).json()
    assert d["due_on"] == "2026-10-05" and d["due_at"].startswith("2026-10-05T17:00")


async def test_viewer_cannot_assign(as_user: Clients, uow: UnitOfWork) -> None:
    ravi = await as_user("ravi")
    t = await _task(ravi)
    kim = await as_user("kim")  # not on the Product team
    r = await kim.patch(f"/api/v1/tasks/{t['id']}", json={"due_on": "2026-10-01"})
    assert r.status_code in (403, 404)
