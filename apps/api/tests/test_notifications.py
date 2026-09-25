"""S2.5.1 Notification generation: assigned/mentioned/commented/completed (event-driven),
due_soon/overdue (lazy per-user daily sync), coalescing, prefs, and the inbox read/archive API."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from tests.helpers import Clients


def doc_with_text(text: str) -> dict:  # type: ignore[type-arg]
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def mention(kind: str, id_: str) -> dict:  # type: ignore[type-arg]
    return {"type": "mention", "attrs": {"id": id_, "label": "x", "kind": kind}}


def doc_with_mention(id_: str) -> dict:  # type: ignore[type-arg]
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [mention("user", id_), {"type": "text", "text": " check this"}],
            }
        ],
    }


async def _project(c, name: str = "Website Revamp") -> str:  # type: ignore[no-untyped-def]
    return next(
        p["id"] for p in (await c.get("/api/v1/projects")).json()["data"] if p["name"] == name
    )


async def _users(c) -> dict:  # type: ignore[no-untyped-def]
    return {
        u["email"].split("@")[0]: u["id"] for u in (await c.get("/api/v1/users")).json()["data"]
    }


async def _task(c, pid: str, **kw) -> dict:  # type: ignore[no-untyped-def]
    r = await c.post(f"/api/v1/projects/{pid}/tasks", json={"title": "T", **kw})
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def test_assigning_someone_else_notifies_them_not_yourself(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    ana = await as_user("ana")
    pid = await _project(ravi)
    users = await _users(ravi)
    t = await _task(ravi, pid)

    r = await ravi.patch(f"/api/v1/tasks/{t['id']}", json={"assignee_id": users["ana"]})
    assert r.status_code == 200

    notes = (await ana.get("/api/v1/notifications")).json()["data"]
    assert any(n["kind"] == "assigned" and n["entity_id"] == t["id"] for n in notes)
    # ravi didn't notify himself
    assert (await ravi.get("/api/v1/notifications")).json()["data"] == []


async def test_assigning_yourself_does_not_notify(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    users = await _users(ravi)
    t = await _task(ravi, pid)
    await ravi.patch(f"/api/v1/tasks/{t['id']}", json={"assignee_id": users["ravi"]})
    assert (await ravi.get("/api/v1/notifications")).json()["data"] == []


async def test_mention_in_a_comment_notifies_the_mentioned_person(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    ana = await as_user("ana")
    pid = await _project(ravi)
    users = await _users(ravi)
    t = await _task(ravi, pid)

    r = await ravi.post(
        f"/api/v1/tasks/{t['id']}/comments", json={"body": doc_with_mention(users["ana"])}
    )
    assert r.status_code == 201

    notes = (await ana.get("/api/v1/notifications")).json()["data"]
    assert any(n["kind"] == "mentioned" and n["entity_id"] == t["id"] for n in notes)


async def test_comment_on_a_followed_task_notifies_other_followers(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    ana = await as_user("ana")
    pid = await _project(ravi)
    users = await _users(ravi)
    t = await _task(ravi, pid)
    await ravi.post(f"/api/v1/tasks/{t['id']}/followers", json={"user_id": users["ana"]})

    r = await ravi.post(f"/api/v1/tasks/{t['id']}/comments", json={"body": doc_with_text("hello")})
    assert r.status_code == 201

    notes = (await ana.get("/api/v1/notifications")).json()["data"]
    assert any(n["kind"] == "commented" and n["entity_id"] == t["id"] for n in notes)
    # the commenter doesn't notify themself
    assert (await ravi.get("/api/v1/notifications")).json()["data"] == []


async def test_mentioned_follower_gets_only_the_mention_not_also_a_comment_notification(
    as_user: Clients,
) -> None:
    ravi = await as_user("ravi")
    ana = await as_user("ana")
    pid = await _project(ravi)
    users = await _users(ravi)
    t = await _task(ravi, pid)
    await ravi.post(f"/api/v1/tasks/{t['id']}/followers", json={"user_id": users["ana"]})

    await ravi.post(
        f"/api/v1/tasks/{t['id']}/comments", json={"body": doc_with_mention(users["ana"])}
    )

    notes = (await ana.get("/api/v1/notifications")).json()["data"]
    kinds = [n["kind"] for n in notes if n["entity_id"] == t["id"]]
    assert kinds == ["mentioned"]


async def test_completing_a_task_notifies_its_creator(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    ana = await as_user("ana")
    pid = await _project(ravi)
    users = await _users(ravi)
    t = await _task(ana, pid)  # ana creates it
    r = await ravi.patch(f"/api/v1/tasks/{t['id']}", json={"assignee_id": users["ravi"]})
    assert r.status_code == 200

    r2 = await ravi.post(f"/api/v1/tasks/{t['id']}/complete")
    assert r2.status_code == 200

    notes = (await ana.get("/api/v1/notifications")).json()["data"]
    assert any(n["kind"] == "completed" and n["entity_id"] == t["id"] for n in notes)


async def test_completing_your_own_created_task_does_not_notify_yourself(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    t = await _task(ravi, pid)
    await ravi.post(f"/api/v1/tasks/{t['id']}/complete")
    assert (await ravi.get("/api/v1/notifications")).json()["data"] == []


async def test_repeated_assignments_within_10_minutes_coalesce_into_one_notification(
    as_user: Clients,
) -> None:
    ravi = await as_user("ravi")
    ana = await as_user("ana")
    pid = await _project(ravi)
    users = await _users(ravi)
    t = await _task(ravi, pid)

    await ravi.patch(f"/api/v1/tasks/{t['id']}", json={"assignee_id": users["priya"]})
    await ravi.patch(f"/api/v1/tasks/{t['id']}", json={"assignee_id": users["ana"]})
    await ravi.patch(
        f"/api/v1/tasks/{t['id']}", json={"assignee_id": users["ana"]}
    )  # no-op, no dup
    r = await ravi.patch(f"/api/v1/tasks/{t['id']}", json={"title": "Renamed"})
    assert r.status_code == 200

    notes = [
        n
        for n in (await ana.get("/api/v1/notifications")).json()["data"]
        if n["entity_id"] == t["id"]
    ]
    assert len(notes) == 1


async def test_mark_read_unread_and_archive(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    ana = await as_user("ana")
    pid = await _project(ravi)
    users = await _users(ravi)
    t = await _task(ravi, pid)
    await ravi.patch(f"/api/v1/tasks/{t['id']}", json={"assignee_id": users["ana"]})
    note = (await ana.get("/api/v1/notifications")).json()["data"][0]

    assert (await ana.get("/api/v1/notifications/unread-count")).json()["count"] == 1

    r = await ana.post(f"/api/v1/notifications/{note['id']}/read")
    assert r.status_code == 200 and r.json()["read_at"] is not None
    assert (await ana.get("/api/v1/notifications/unread-count")).json()["count"] == 0

    r2 = await ana.post(f"/api/v1/notifications/{note['id']}/unread")
    assert r2.json()["read_at"] is None

    r3 = await ana.post(f"/api/v1/notifications/{note['id']}/archive")
    assert r3.status_code == 200 and r3.json()["archived_at"] is not None
    assert (await ana.get("/api/v1/notifications")).json()["data"] == []
    archived = (await ana.get("/api/v1/notifications", params={"archived": "true"})).json()["data"]
    assert [n["id"] for n in archived] == [note["id"]]


async def test_cannot_act_on_someone_elses_notification(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    ana = await as_user("ana")
    pid = await _project(ravi)
    users = await _users(ravi)
    t = await _task(ravi, pid)
    await ravi.patch(f"/api/v1/tasks/{t['id']}", json={"assignee_id": users["ana"]})
    note = (await ana.get("/api/v1/notifications")).json()["data"][0]

    r = await ravi.post(f"/api/v1/notifications/{note['id']}/read")
    assert r.status_code == 404


async def test_prefs_off_suppresses_that_kind(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    ana = await as_user("ana")
    pid = await _project(ravi)
    users = await _users(ravi)

    r = await ana.get("/api/v1/me/prefs/notifications")
    assert r.status_code == 200 and r.json()["assigned"] is True
    prefs = r.json()
    prefs["assigned"] = False
    r2 = await ana.put("/api/v1/me/prefs/notifications", json=prefs)
    assert r2.status_code == 200 and r2.json()["assigned"] is False

    t = await _task(ravi, pid)
    await ravi.patch(f"/api/v1/tasks/{t['id']}", json={"assignee_id": users["ana"]})
    assert (await ana.get("/api/v1/notifications")).json()["data"] == []


async def test_due_today_and_overdue_tasks_are_synced_on_read(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    users = await _users(ravi)

    due_today = await _task(ravi, pid, assignee_id=users["ravi"])
    todays_date = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()  # Ravi's day
    await ravi.patch(f"/api/v1/tasks/{due_today['id']}", json={"due_on": todays_date})
    overdue = await _task(ravi, pid, assignee_id=users["ravi"])
    await ravi.patch(f"/api/v1/tasks/{overdue['id']}", json={"due_on": "2020-01-01"})

    notes = (await ravi.get("/api/v1/notifications")).json()["data"]
    kinds_by_entity = {n["entity_id"]: n["kind"] for n in notes}
    assert kinds_by_entity.get(due_today["id"]) == "due_soon"
    assert kinds_by_entity.get(overdue["id"]) == "overdue"
