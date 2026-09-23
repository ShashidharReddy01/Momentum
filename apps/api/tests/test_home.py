"""S1.5.2 Home: priorities, recent projects from my activity, waiting on others, empty states."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import text

from momentum.core.db import UnitOfWork
from tests.helpers import Clients

BASE = "/api/v1"


async def _ids(c):  # type: ignore[no-untyped-def]
    users = {
        u["email"].split("@")[0]: u["id"] for u in (await c.get(f"{BASE}/users")).json()["data"]
    }
    projects = {p["name"]: p["id"] for p in (await c.get(f"{BASE}/projects")).json()["data"]}
    return users, projects


async def _task(c, pid: str, title: str, **patch):  # type: ignore[no-untyped-def]
    t = (await c.post(f"{BASE}/projects/{pid}/tasks", json={"title": title})).json()["data"]
    if patch:
        r = await c.patch(f"{BASE}/tasks/{t['id']}", json=patch)
        assert r.status_code == 200, r.text
    return t


async def test_priorities_order_counts_and_hidden_tasks(as_user: Clients, uow: UnitOfWork) -> None:
    ravi = await as_user("ravi")
    users, projects = await _ids(ravi)
    pid = projects["Website Revamp"]
    me = users["ravi"]
    old = date(2001, 1, 1)
    await _task(ravi, pid, "Oldest low", assignee_id=me, due_on=old.isoformat())
    urgent = await _task(ravi, pid, "Oldest urgent", assignee_id=me, due_on=old.isoformat())
    await _task(ravi, pid, "Next day", assignee_id=me, due_on=(old + timedelta(1)).isoformat())
    gone = await _task(ravi, pid, "Deleted", assignee_id=me, due_on="2000-01-01")
    await ravi.delete(f"{BASE}/tasks/{gone['id']}")
    done = await _task(ravi, pid, "Done", assignee_id=me, due_on="2000-01-01")
    await ravi.post(f"{BASE}/tasks/{done['id']}/complete")
    async with uow.transaction() as s:
        await s.execute(
            text("UPDATE tasks SET priority = 'urgent' WHERE id = :id"), {"id": urgent["id"]}
        )
    h = (await ravi.get(f"{BASE}/home")).json()
    titles = [t["title"] for t in h["priorities"]]
    assert titles[:3] == ["Oldest urgent", "Oldest low", "Next day"]
    assert len(titles) <= 5 and "Deleted" not in titles and "Done" not in titles
    assert h["priorities"][0]["project"]["name"] == "Website Revamp"
    mine = (await ravi.get(f"{BASE}/me/tasks")).json()["data"]
    assert h["counts"]["open"] == len(mine)
    assert h["counts"]["overdue"] >= 3
    assert h["has_projects"] is True


async def test_recent_projects_follow_my_activity_and_visibility(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    _, projects = await _ids(ravi)
    await _task(ravi, projects["Mobile App v2"], "Touch mobile")
    t = await _task(ravi, projects["Website Revamp"], "Touch web")
    names = [p["name"] for p in (await ravi.get(f"{BASE}/home")).json()["recent_projects"]]
    assert names[:2] == ["Website Revamp", "Mobile App v2"]
    # a comment counts as activity in that task's project
    await _task(ravi, projects["Mobile App v2"], "Another")
    body = {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "hi"}]}],
    }
    r = await ravi.post(f"{BASE}/tasks/{t['id']}/comments", json={"body": body})
    assert r.status_code == 201, r.text
    recent = (await ravi.get(f"{BASE}/home")).json()["recent_projects"]
    assert recent[0]["name"] == "Website Revamp" and recent[0]["last_active_at"]
    assert recent[0]["team_name"] == "Product" and recent[0]["open_count"] >= 1
    assert len(recent) <= 6 and len({p["id"] for p in recent}) == len(recent)
    # archived and deleted projects drop out
    await ravi.post(f"{BASE}/projects/{projects['Website Revamp']}/archive")
    priya = await as_user("priya")  # owner of the private Mobile App v2
    d = await priya.delete(f"{BASE}/projects/{projects['Mobile App v2']}")
    assert d.status_code == 200, d.text
    names = [p["name"] for p in (await ravi.get(f"{BASE}/home")).json()["recent_projects"]]
    assert "Website Revamp" not in names and "Mobile App v2" not in names
    # someone else's activity in a project I can't see never shows up for me
    ana = await as_user("ana")
    _, ana_projects = await _ids(ana)
    await _task(ana, ana_projects["Q4 Launch Campaign"], "Marketing only")
    names = [p["name"] for p in (await ravi.get(f"{BASE}/home")).json()["recent_projects"]]
    assert "Q4 Launch Campaign" not in names


async def test_waiting_on_others(as_user: Clients) -> None:
    ravi, ana = await as_user("ravi"), await as_user("ana")
    users, projects = await _ids(ravi)
    pid = projects["Website Revamp"]
    yesterday = (date.today() - timedelta(days=2)).isoformat()
    later = (date.today() + timedelta(days=30)).isoformat()
    late = await _task(ravi, pid, "Ana is late", assignee_id=users["ana"], due_on=yesterday)
    await _task(ravi, pid, "Not due yet", assignee_id=users["ana"], due_on=later)
    await _task(ravi, pid, "Mine and late", assignee_id=users["ravi"], due_on=yesterday)
    await _task(ravi, pid, "Nobody", due_on=yesterday)
    # a task I only follow (created by Ana, assigned to Priya)
    followed = await _task(ana, pid, "Followed", assignee_id=users["priya"], due_on=yesterday)
    f = await ravi.post(f"{BASE}/tasks/{followed['id']}/followers", json={"user_id": users["ravi"]})
    assert f.status_code == 200, f.text
    h = (await ravi.get(f"{BASE}/home")).json()
    waiting = [t["title"] for t in h["waiting"]]
    assert "Ana is late" in waiting and "Followed" in waiting
    assert not {"Not due yet", "Mine and late", "Nobody"} & set(waiting)
    assert h["waiting_total"] >= 2
    # Ana doesn't wait on herself
    assert "Ana is late" not in [
        t["title"] for t in (await ana.get(f"{BASE}/home")).json()["waiting"]
    ]
    await ana.post(f"{BASE}/tasks/{late['id']}/complete")
    assert "Ana is late" not in [
        t["title"] for t in (await ravi.get(f"{BASE}/home")).json()["waiting"]
    ]


async def test_new_user_without_projects(as_user: Clients, uow: UnitOfWork) -> None:
    async with uow.transaction() as s:
        await s.execute(
            text(
                "DELETE FROM team_members WHERE user_id = "
                "(SELECT id FROM users WHERE email = 'kim@acme-demo.test')"
            )
        )
        await s.execute(
            text(
                "UPDATE tasks SET assignee_id = NULL WHERE assignee_id = "
                "(SELECT id FROM users WHERE email = 'kim@acme-demo.test')"
            )
        )
    kim = await as_user("kim")
    h = (await kim.get(f"{BASE}/home")).json()
    assert h["has_projects"] is False
    assert h["priorities"] == [] and h["recent_projects"] == [] and h["waiting"] == []
    assert h["counts"] == {"open": 0, "due_today": 0, "overdue": 0}
