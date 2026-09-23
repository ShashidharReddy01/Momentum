"""S1.2.2 Tasks: create/order/number, complete + undo position, edit, delete, batch, permissions."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event

from tests.helpers import Clients


async def _project(c, name: str = "Website Revamp") -> str:  # type: ignore[no-untyped-def]
    return next(
        p["id"] for p in (await c.get("/api/v1/projects")).json()["data"] if p["name"] == name
    )


async def _sections(c, pid: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {
        s["name"]: s["id"] for s in (await c.get(f"/api/v1/projects/{pid}/sections")).json()["data"]
    }


async def _titles(c, pid: str, section: str | None = None) -> list[str]:  # type: ignore[no-untyped-def]
    tasks = (await c.get(f"/api/v1/projects/{pid}/tasks")).json()["data"]
    return [t["title"] for t in tasks if section is None or t["section_id"] == section]


async def _new(c, pid, title, **kw):  # type: ignore[no-untyped-def]
    r = await c.post(f"/api/v1/projects/{pid}/tasks", json={"title": title, **kw})
    assert r.status_code == 201, r.text
    return r.json()


async def test_create_orders_and_keys(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    sec = (await _sections(ravi, pid))["Review"]
    a = (await _new(ravi, pid, "A", section_id=sec))["data"]
    c = (await _new(ravi, pid, "C", section_id=sec))["data"]
    await _new(ravi, pid, "B", section_id=sec, after_id=a["id"])
    await _new(ravi, pid, "Z", section_id=sec, before_id=a["id"])
    assert (await _titles(ravi, pid, sec))[-4:] == ["Z", "A", "B", "C"]
    assert a["key"] == f"T-{a['number']}" and c["number"] == a["number"] + 1
    # default section is the first one
    d = (await _new(ravi, pid, "Default placement"))["data"]
    assert d["section_id"] == (await _sections(ravi, pid))["Backlog"]


async def test_rapid_sequential_creation_keeps_order(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    sec = (await _sections(ravi, pid))["Review"]
    prev = None
    for i in range(10):
        body = {"section_id": sec, **({"after_id": prev} if prev else {})}
        prev = (await _new(ravi, pid, f"Item {i}", **body))["data"]["id"]
    titles = await _titles(ravi, pid, sec)
    assert [t for t in titles if t.startswith("Item")] == [f"Item {i}" for i in range(10)]


async def test_numbers_unique_under_concurrency(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    results = await asyncio.gather(*[_new(ravi, pid, f"Parallel {i}") for i in range(10)])
    numbers = [r["data"]["number"] for r in results]
    assert len(set(numbers)) == 10 and max(numbers) - min(numbers) == 9


async def test_complete_hides_and_undo_restores_exact_position(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    before = (await ravi.get(f"/api/v1/projects/{pid}/tasks")).json()["data"]
    target = before[2]
    r = await ravi.post(f"/api/v1/tasks/{target['id']}/complete")
    assert r.status_code == 200 and r.json()["data"]["completed_at"]
    after = [t["id"] for t in (await ravi.get(f"/api/v1/projects/{pid}/tasks")).json()["data"]]
    assert target["id"] not in after
    done = (await ravi.get(f"/api/v1/projects/{pid}/tasks", params={"completed": True})).json()[
        "data"
    ]
    assert done[0]["id"] == target["id"]
    await ravi.post("/api/v1/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    restored = [t["id"] for t in (await ravi.get(f"/api/v1/projects/{pid}/tasks")).json()["data"]]
    assert restored == [t["id"] for t in before]


async def test_rename_version_conflict_and_undo(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    t = (await _new(ravi, pid, "Original"))["data"]
    r = await ravi.patch(f"/api/v1/tasks/{t['id']}", json={"title": "  Renamed   task "})
    assert r.json()["data"]["title"] == "Renamed task"
    stale = await ravi.patch(
        f"/api/v1/tasks/{t['id']}", json={"title": "x"}, headers={"If-Match": "1"}
    )
    assert stale.status_code == 409 and stale.json()["code"] == "version_conflict"
    await ravi.post("/api/v1/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert (await ravi.get(f"/api/v1/tasks/{t['id']}")).json()["title"] == "Original"
    assert (await ravi.patch(f"/api/v1/tasks/{t['id']}", json={"title": "   "})).status_code == 422


async def test_delete_and_undo(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    t = (await _new(ravi, pid, "Temp"))["data"]
    d = await ravi.delete(f"/api/v1/tasks/{t['id']}")
    assert (await ravi.get(f"/api/v1/tasks/{t['id']}")).status_code == 404
    await ravi.post("/api/v1/undo", json={"activity_id": d.json()["meta"]["activity_id"]})
    assert (await ravi.get(f"/api/v1/tasks/{t['id']}")).status_code == 200


async def test_batch_create_in_order_and_batch_undo(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    sec = (await _sections(ravi, pid))["Done"]
    r = await ravi.post(
        f"/api/v1/projects/{pid}/tasks/batch",
        json={"titles": ["one", "", "two", "three"], "section_id": sec},
    )
    assert r.status_code == 201
    assert [t["title"] for t in r.json()["data"]["data"]] == ["one", "two", "three"]
    titles = await _titles(ravi, pid, sec)
    assert titles[-3:] == ["one", "two", "three"]
    await ravi.post("/api/v1/undo", json={"batch_id": r.json()["meta"]["batch_id"]})
    assert not {"one", "two", "three"} & set(await _titles(ravi, pid, sec))


async def test_permissions(as_user: Clients) -> None:
    ravi, tom = await as_user("ravi"), await as_user("tom")
    pid = await _project(ravi)
    t = (await _new(ravi, pid, "Secret"))["data"]
    assert (await tom.get(f"/api/v1/tasks/{t['id']}")).status_code == 404
    assert (await tom.get(f"/api/v1/projects/{pid}/tasks")).status_code == 404
    users = {
        u["email"].split("@")[0]: u["id"] for u in (await ravi.get("/api/v1/users")).json()["data"]
    }
    await ravi.post(
        f"/api/v1/projects/{pid}/members", json={"user_id": users["mei"], "role": "viewer"}
    )
    mei = await as_user("mei")
    assert (await mei.get(f"/api/v1/tasks/{t['id']}")).status_code == 200
    assert (await mei.post(f"/api/v1/tasks/{t['id']}/complete")).status_code == 403
    assert (await mei.post(f"/api/v1/projects/{pid}/tasks", json={"title": "x"})).status_code == 403


async def test_section_delete_moves_tasks_and_undo_restores(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    secs = await _sections(ravi, pid)
    in_review = await _titles(ravi, pid, secs["Review"])
    assert in_review
    d = await ravi.delete(
        f"/api/v1/sections/{secs['Review']}", params={"target_section_id": secs["Done"]}
    )
    assert d.status_code == 200
    assert (await _titles(ravi, pid, secs["Done"]))[-len(in_review) :] == in_review
    await ravi.post("/api/v1/undo", json={"activity_id": d.json()["meta"]["activity_id"]})
    assert await _titles(ravi, pid, secs["Review"]) == in_review


@contextmanager
def count_queries(engine) -> Iterator[list[str]]:  # type: ignore[no-untyped-def]
    statements: list[str] = []

    def before(conn, cursor, statement, *a):  # type: ignore[no-untyped-def]
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", before)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before)


async def test_list_query_count(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    engine = as_user.app.state.momentum.engine
    with count_queries(engine) as statements:
        r = await ravi.get(f"/api/v1/projects/{pid}/tasks")
    assert r.status_code == 200
    # auth (identity, user, workspace) + project visibility + the list query + one query for
    # subtask counts, independent of the number of tasks (no N+1)
    task_queries = [s for s in statements if "FROM tasks" in s]
    assert len(task_queries) == 2, task_queries
    await ravi.post(
        f"/api/v1/projects/{pid}/tasks/batch", json={"titles": [f"x{i}" for i in range(20)]}
    )
    with count_queries(engine) as more:
        await ravi.get(f"/api/v1/projects/{pid}/tasks")
    assert len([s for s in more if "FROM tasks" in s]) == 2
