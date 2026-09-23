"""S1.3.2 Subtasks: order, counts, visibility inheritance, depth, reorder/outdent + undo."""

from __future__ import annotations

from tests.helpers import Clients

BASE = "/api/v1"


async def _project(c, name: str = "Website Revamp") -> str:  # type: ignore[no-untyped-def]
    return next(
        p["id"] for p in (await c.get(f"{BASE}/projects")).json()["data"] if p["name"] == name
    )


async def _task(c, pid: str, title: str = "Parent") -> dict:  # type: ignore[no-untyped-def]
    r = await c.post(f"{BASE}/projects/{pid}/tasks", json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()["data"]  # type: ignore[no-any-return]


async def _sub(c, parent: str, title: str, **kw) -> dict:  # type: ignore[no-untyped-def]
    r = await c.post(f"{BASE}/tasks/{parent}/subtasks", json={"title": title, **kw})
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


async def _subs(c, parent: str) -> list[str]:  # type: ignore[no-untyped-def]
    return [t["title"] for t in (await c.get(f"{BASE}/tasks/{parent}/subtasks")).json()["data"]]


async def test_create_order_counts_and_shape(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    parent = await _task(ravi, pid)
    a = (await _sub(ravi, parent["id"], "A"))["data"]
    await _sub(ravi, parent["id"], "C")
    await _sub(ravi, parent["id"], "B", after_id=a["id"])
    assert await _subs(ravi, parent["id"]) == ["A", "B", "C"]
    assert a["parent_id"] == parent["id"] and a["section_id"] is None and a["project_id"] == pid
    await ravi.post(f"{BASE}/tasks/{a['id']}/complete")
    rows = {t["id"]: t for t in (await ravi.get(f"{BASE}/projects/{pid}/tasks")).json()["data"]}
    assert (rows[parent["id"]]["subtask_count"], rows[parent["id"]]["completed_subtask_count"]) == (
        3,
        1,
    )
    # subtasks are not rows of the project list
    assert a["id"] not in rows
    detail = (await ravi.get(f"{BASE}/tasks/{a['id']}")).json()
    assert detail["parent"] == {"id": parent["id"], "name": "Parent"} and detail["section"] is None


async def test_subtask_of_private_task_is_invisible_to_non_members(as_user: Clients) -> None:
    priya, ravi, tom = await as_user("priya"), await as_user("ravi"), await as_user("tom")
    pid = await _project(priya, "Mobile App v2")  # private: priya (owner) + ravi
    parent = await _task(priya, pid, "Secret parent")
    sub = (await _sub(priya, parent["id"], "Secret sub"))["data"]
    nested = (await _sub(priya, sub["id"], "Deeper"))["data"]
    assert (await ravi.get(f"{BASE}/tasks/{nested['id']}")).status_code == 200
    for url in (
        f"{BASE}/tasks/{sub['id']}",
        f"{BASE}/tasks/{nested['id']}",
        f"{BASE}/tasks/{parent['id']}/subtasks",
    ):
        assert (await tom.get(url)).status_code == 404, url
    assert (await tom.post(f"{BASE}/tasks/{sub['id']}/complete")).status_code == 404


async def test_deleting_the_parent_hides_subtasks_until_undo(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    parent = await _task(ravi, pid)
    sub = (await _sub(ravi, parent["id"], "Child"))["data"]
    d = await ravi.delete(f"{BASE}/tasks/{parent['id']}")
    assert (await ravi.get(f"{BASE}/tasks/{sub['id']}")).status_code == 404
    await ravi.post(f"{BASE}/undo", json={"activity_id": d.json()["meta"]["activity_id"]})
    assert (await ravi.get(f"{BASE}/tasks/{sub['id']}")).status_code == 200


async def test_depth_limit(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    current = (await _task(ravi, pid))["id"]
    for level in range(1, 5):
        current = (await _sub(ravi, current, f"L{level}"))["data"]["id"]
    r = await ravi.post(f"{BASE}/tasks/{current}/subtasks", json={"title": "too deep"})
    assert r.status_code == 422 and r.json()["code"] == "too_deep"


async def test_reorder_and_undo(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    parent = (await _task(ravi, pid))["id"]
    ids = {t: (await _sub(ravi, parent, t))["data"]["id"] for t in ["1", "2", "3"]}
    r = await ravi.post(f"{BASE}/tasks/{ids['3']}/subtask-move", json={"before_id": ids["1"]})
    assert r.status_code == 200 and await _subs(ravi, parent) == ["3", "1", "2"]
    await ravi.post(f"{BASE}/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert await _subs(ravi, parent) == ["1", "2", "3"]
    r = await ravi.post(f"{BASE}/tasks/{ids['1']}/subtask-move", json={"after_id": ids["1"]})
    assert r.status_code == 422
    # top-level tasks can't use subtask-move; subtasks can't use /move
    r = await ravi.post(f"{BASE}/tasks/{parent}/subtask-move", json={})
    assert r.status_code == 422 and r.json()["code"] == "not_a_subtask"
    secs = (await ravi.get(f"{BASE}/projects/{pid}/sections")).json()["data"]
    r = await ravi.post(f"{BASE}/tasks/{ids['1']}/move", json={"section_id": secs[0]["id"]})
    assert r.status_code == 422 and r.json()["code"] == "not_movable"


async def test_outdent_to_section_and_to_grandparent_with_undo(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    sec = (await ravi.post(f"{BASE}/projects/{pid}/sections", json={"name": "O"})).json()["data"][
        "id"
    ]
    parent = (
        await ravi.post(f"{BASE}/projects/{pid}/tasks", json={"title": "P", "section_id": sec})
    ).json()["data"]
    await ravi.post(f"{BASE}/projects/{pid}/tasks", json={"title": "After P", "section_id": sec})
    child = (await _sub(ravi, parent["id"], "Child"))["data"]
    grandchild = (await _sub(ravi, child["id"], "Grandchild"))["data"]
    # depth 2 → under the grandparent, right after its old parent
    r = await ravi.post(f"{BASE}/tasks/{grandchild['id']}/outdent")
    assert r.status_code == 200 and r.json()["data"]["parent_id"] == parent["id"]
    assert await _subs(ravi, parent["id"]) == ["Child", "Grandchild"]
    # depth 1 → a top-level task in the parent's section, right after the parent
    r = await ravi.post(f"{BASE}/tasks/{child['id']}/outdent")
    assert r.status_code == 200 and r.json()["data"]["section_id"] == sec
    titles = [
        t["title"]
        for t in (await ravi.get(f"{BASE}/projects/{pid}/tasks")).json()["data"]
        if t["section_id"] == sec
    ]
    assert titles == ["P", "Child", "After P"]
    # undo puts it back as a subtask, in its old place
    await ravi.post(f"{BASE}/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert await _subs(ravi, parent["id"]) == ["Child", "Grandchild"]
    titles = [
        t["title"]
        for t in (await ravi.get(f"{BASE}/projects/{pid}/tasks")).json()["data"]
        if t["section_id"] == sec
    ]
    assert titles == ["P", "After P"]
    assert (await ravi.post(f"{BASE}/tasks/{parent['id']}/outdent")).status_code == 422


async def test_permissions(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    parent = (await _task(ravi, pid))["id"]
    users = {
        u["email"].split("@")[0]: u["id"] for u in (await ravi.get(f"{BASE}/users")).json()["data"]
    }
    await ravi.post(
        f"{BASE}/projects/{pid}/members", json={"user_id": users["mei"], "role": "viewer"}
    )
    mei = await as_user("mei")
    assert (await mei.get(f"{BASE}/tasks/{parent}/subtasks")).status_code == 200
    assert (
        await mei.post(f"{BASE}/tasks/{parent}/subtasks", json={"title": "x"})
    ).status_code == 403
