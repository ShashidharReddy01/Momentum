"""S1.5.1 My Tasks: recently assigned, daily bucketing (pins respected), moves + undo, subtasks."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from momentum.core.db import UnitOfWork
from tests.helpers import Clients

BASE = "/api/v1"


async def _setup(c):  # type: ignore[no-untyped-def]
    users = {
        u["email"].split("@")[0]: u["id"] for u in (await c.get(f"{BASE}/users")).json()["data"]
    }
    pid = next(
        p["id"]
        for p in (await c.get(f"{BASE}/projects")).json()["data"]
        if p["name"] == "Website Revamp"
    )
    return users, pid


async def _mine(c, **params) -> dict[str, list[str]]:  # type: ignore[no-untyped-def]
    rows = (await c.get(f"{BASE}/me/tasks", params=params)).json()["data"]
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r["bucket"] or "-", []).append(r["title"])
    return out


def _all(buckets: dict[str, list[str]]) -> list[str]:
    return [t for titles in buckets.values() for t in titles]


async def _new_day(uow: UnitOfWork, local: str) -> None:
    """Pretend the daily pass last ran yesterday."""
    async with uow.transaction() as s:
        await s.execute(
            text("UPDATE users SET prefs = prefs - 'my_tasks_day' WHERE email = :e"),
            {"e": f"{local}@acme-demo.test"},
        )


async def test_assigned_task_appears_in_recently_assigned_right_away(as_user: Clients) -> None:
    ravi, ana = await as_user("ravi"), await as_user("ana")
    users, pid = await _setup(ravi)
    before = await _mine(ana)
    t1 = (await ravi.post(f"{BASE}/projects/{pid}/tasks", json={"title": "For Ana 1"})).json()[
        "data"
    ]
    t2 = (await ravi.post(f"{BASE}/projects/{pid}/tasks", json={"title": "For Ana 2"})).json()[
        "data"
    ]
    await ravi.patch(f"{BASE}/tasks/{t1['id']}", json={"assignee_id": users["ana"]})
    await ravi.patch(f"{BASE}/tasks/{t2['id']}", json={"assignee_id": users["ana"]})
    mine = await _mine(ana)
    assert mine["recently_assigned"][:2] == ["For Ana 2", "For Ana 1"]  # newest first
    assert len(mine["recently_assigned"]) == len(before.get("recently_assigned", [])) + 2
    rows = (await ana.get(f"{BASE}/me/tasks")).json()["data"]
    assert next(r for r in rows if r["title"] == "For Ana 1")["project"]["name"] == "Website Revamp"
    # reassigned away → gone
    await ravi.patch(f"{BASE}/tasks/{t1['id']}", json={"assignee_id": users["ravi"]})
    assert "For Ana 1" not in _all(await _mine(ana))


async def test_daily_pass_moves_unpinned_by_due_date(as_user: Clients, uow: UnitOfWork) -> None:
    ravi = await as_user("ravi")
    users, pid = await _setup(ravi)
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()  # Ravi's day, as the API sees it

    async def mk(title: str, due: object = None) -> str:
        t = (await ravi.post(f"{BASE}/projects/{pid}/tasks", json={"title": title})).json()["data"]
        await ravi.patch(
            f"{BASE}/tasks/{t['id']}", json={"assignee_id": users["ravi"], "due_on": due}
        )
        return str(t["id"])

    overdue = await mk("Overdue", str(today - timedelta(days=2)))
    far = await mk("Next month", str(today + timedelta(days=30)))
    undated = await mk("Someday")
    later_now_today = await mk("Soon", str(today + timedelta(days=40)))
    pinned = await mk("Pinned later", str(today))
    await ravi.get(f"{BASE}/me/tasks")  # sync: everything new is "recently assigned"
    # the user sorts some by hand (pins) …
    await ravi.post(f"{BASE}/me/tasks/{later_now_today}/move", json={"bucket": "later"})
    await ravi.post(f"{BASE}/me/tasks/{pinned}/move", json={"bucket": "later"})
    # … an unpinned task sits in Later and becomes due today
    async with uow.transaction() as s:
        await s.execute(
            text(
                "UPDATE my_task_placements SET pinned = false, bucket = 'later' WHERE task_id = :t"
            ),
            {"t": later_now_today},
        )
    await ravi.patch(f"{BASE}/tasks/{later_now_today}", json={"due_on": str(today)})
    await _new_day(uow, "ravi")
    mine = await _mine(ravi)
    assert "Overdue" in mine["today"]  # overdue surfaces from Recently assigned
    assert "Soon" in mine["today"]
    assert "Next month" in mine["recently_assigned"] and "Someday" in mine["recently_assigned"]
    assert "Pinned later" in mine["later"]  # pinned: stays even though due today
    assert far and undated and overdue


async def test_move_pins_and_undo(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    users, pid = await _setup(ravi)
    ids = []
    for title in ["A", "B"]:
        t = (await ravi.post(f"{BASE}/projects/{pid}/tasks", json={"title": title})).json()["data"]
        await ravi.patch(f"{BASE}/tasks/{t['id']}", json={"assignee_id": users["ravi"]})
        ids.append(t["id"])
    await ravi.get(f"{BASE}/me/tasks")
    r = await ravi.post(f"{BASE}/me/tasks/{ids[0]}/move", json={"bucket": "today"})
    assert r.status_code == 200
    await ravi.post(f"{BASE}/me/tasks/{ids[1]}/move", json={"bucket": "today", "before_id": ids[0]})
    assert (await _mine(ravi))["today"][:2] == ["B", "A"]
    # undoing A's move puts it back in Recently assigned (A itself wasn't moved again)
    u = await ravi.post(f"{BASE}/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert u.status_code == 200
    mine = await _mine(ravi)
    assert "A" in mine["recently_assigned"] and mine["today"][:1] == ["B"]
    # but a move that was followed by another move of the same task can't be undone
    m1 = await ravi.post(f"{BASE}/me/tasks/{ids[1]}/move", json={"bucket": "later"})
    await ravi.post(f"{BASE}/me/tasks/{ids[1]}/move", json={"bucket": "this_week"})
    u = await ravi.post(f"{BASE}/undo", json={"activity_id": m1.json()["meta"]["activity_id"]})
    assert u.status_code == 409


async def test_move_validation_and_isolation(as_user: Clients) -> None:
    ravi, ana = await as_user("ravi"), await as_user("ana")
    users, pid = await _setup(ravi)
    t = (await ravi.post(f"{BASE}/projects/{pid}/tasks", json={"title": "Mine"})).json()["data"]
    await ravi.patch(f"{BASE}/tasks/{t['id']}", json={"assignee_id": users["ravi"]})
    assert (
        await ravi.post(f"{BASE}/me/tasks/{t['id']}/move", json={"bucket": "someday"})
    ).status_code == 422
    assert (
        await ana.post(f"{BASE}/me/tasks/{t['id']}/move", json={"bucket": "today"})
    ).status_code == 404


async def test_completed_keeps_place_and_subtasks_show_with_project(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    users, pid = await _setup(ravi)
    t = (await ravi.post(f"{BASE}/projects/{pid}/tasks", json={"title": "Parent"})).json()["data"]
    sub = (await ravi.post(f"{BASE}/tasks/{t['id']}/subtasks", json={"title": "My step"})).json()[
        "data"
    ]
    await ravi.patch(f"{BASE}/tasks/{sub['id']}", json={"assignee_id": users["ravi"]})
    rows = (await ravi.get(f"{BASE}/me/tasks")).json()["data"]
    row = next(r for r in rows if r["title"] == "My step")
    assert row["project"]["name"] == "Website Revamp" and row["parent_id"] == t["id"]
    await ravi.post(f"{BASE}/me/tasks/{sub['id']}/move", json={"bucket": "this_week"})
    await ravi.post(f"{BASE}/tasks/{sub['id']}/complete")
    assert "My step" in _all(await _mine(ravi, completed="true"))
    assert "My step" not in _all(await _mine(ravi))
    await ravi.post(f"{BASE}/tasks/{sub['id']}/uncomplete")
    assert "My step" in (await _mine(ravi))["this_week"]  # back where it was
    # deleting the parent hides it
    await ravi.delete(f"{BASE}/tasks/{t['id']}")
    assert "My step" not in _all(await _mine(ravi))


async def test_concurrent_first_loads_dont_conflict(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    results = await asyncio.gather(*(ravi.get(f"{BASE}/me/tasks") for _ in range(4)))
    assert all(r.status_code == 200 for r in results)


async def test_deleted_project_hides_task_and_restore_keeps_its_bucket(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    users, pid = await _setup(ravi)
    team_id = (await ravi.get(f"{BASE}/projects/{pid}")).json()["team_id"]
    proj = (
        await ravi.post(f"{BASE}/projects", json={"team_id": team_id, "name": "Short-lived"})
    ).json()["data"]
    t = (await ravi.post(f"{BASE}/projects/{proj['id']}/tasks", json={"title": "Orphan"})).json()[
        "data"
    ]
    await ravi.patch(f"{BASE}/tasks/{t['id']}", json={"assignee_id": users["ravi"]})
    await ravi.get(f"{BASE}/me/tasks")
    await ravi.post(f"{BASE}/me/tasks/{t['id']}/move", json={"bucket": "later"})
    d = await ravi.delete(f"{BASE}/projects/{proj['id']}")
    assert d.status_code == 200
    assert "Orphan" not in _all(await _mine(ravi))
    u = await ravi.post(f"{BASE}/undo", json={"activity_id": d.json()["meta"]["activity_id"]})
    assert u.status_code == 200
    mine = await _mine(ravi)
    assert "Orphan" in mine["later"]
    row = next(
        r for r in (await ravi.get(f"{BASE}/me/tasks")).json()["data"] if r["title"] == "Orphan"
    )
    assert row["project"]["name"] == "Short-lived"
