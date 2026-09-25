"""S2.4.1 Multi-homing: add/remove a task to/from projects, the bulk "other projects" endpoint
for list rows, visibility (a private co-placement never leaks), and undo."""

from __future__ import annotations

from tests.helpers import Clients


async def _project(c, name: str = "Website Revamp") -> str:  # type: ignore[no-untyped-def]
    return next(
        p["id"] for p in (await c.get("/api/v1/projects")).json()["data"] if p["name"] == name
    )


async def _sections(c, pid: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {
        s["name"]: s["id"] for s in (await c.get(f"/api/v1/projects/{pid}/sections")).json()["data"]
    }


async def _task(c, pid: str) -> dict:  # type: ignore[no-untyped-def]
    r = await c.post(f"/api/v1/projects/{pid}/tasks", json={"title": "T"})
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def test_add_to_a_second_project_and_list_placements(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    home = await _project(ravi, "Website Revamp")
    other = await _project(ravi, "Mobile App v2")
    t = await _task(ravi, home)

    r = await ravi.post(f"/api/v1/tasks/{t['id']}/projects", json={"project_id": other})
    assert r.status_code == 201, r.text
    assert r.json()["data"]["project"]["id"] == other

    projects = {
        p["project"]["id"]
        for p in (await ravi.get(f"/api/v1/tasks/{t['id']}/projects")).json()["data"]
    }
    assert projects == {home, other}
    # visible in both projects' lists
    assert t["id"] in {
        x["id"] for x in (await ravi.get(f"/api/v1/projects/{home}/tasks")).json()["data"]
    }
    assert t["id"] in {
        x["id"] for x in (await ravi.get(f"/api/v1/projects/{other}/tasks")).json()["data"]
    }


async def test_double_add_conflicts(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    home = await _project(ravi, "Website Revamp")
    other = await _project(ravi, "Mobile App v2")
    t = await _task(ravi, home)
    await ravi.post(f"/api/v1/tasks/{t['id']}/projects", json={"project_id": other})
    r = await ravi.post(f"/api/v1/tasks/{t['id']}/projects", json={"project_id": other})
    assert r.status_code == 409


async def test_cannot_remove_the_only_placement(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    home = await _project(ravi, "Website Revamp")
    t = await _task(ravi, home)
    r = await ravi.delete(f"/api/v1/tasks/{t['id']}/projects/{home}")
    assert r.status_code == 422


async def test_remove_from_one_project_keeps_the_task_in_the_other(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    home = await _project(ravi, "Website Revamp")
    other = await _project(ravi, "Mobile App v2")
    t = await _task(ravi, home)
    await ravi.post(f"/api/v1/tasks/{t['id']}/projects", json={"project_id": other})

    r = await ravi.delete(f"/api/v1/tasks/{t['id']}/projects/{home}")
    assert r.status_code == 200
    projects = {
        p["project"]["id"]
        for p in (await ravi.get(f"/api/v1/tasks/{t['id']}/projects")).json()["data"]
    }
    assert projects == {other}
    assert t["id"] not in {
        x["id"] for x in (await ravi.get(f"/api/v1/projects/{home}/tasks")).json()["data"]
    }
    assert t["id"] in {
        x["id"] for x in (await ravi.get(f"/api/v1/projects/{other}/tasks")).json()["data"]
    }


async def test_subtasks_cannot_be_placed_directly(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    home = await _project(ravi, "Website Revamp")
    other = await _project(ravi, "Mobile App v2")
    t = await _task(ravi, home)
    sub = (await ravi.post(f"/api/v1/tasks/{t['id']}/subtasks", json={"title": "Sub"})).json()[
        "data"
    ]
    r = await ravi.post(f"/api/v1/tasks/{sub['id']}/projects", json={"project_id": other})
    assert r.status_code == 422


async def test_editor_access_required_on_the_target_project(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    home = await _project(ravi, "Website Revamp")
    other = await _project(ravi, "Mobile App v2")
    t = await _task(ravi, home)
    mei = await as_user("mei")  # sees Website Revamp (Product team) but not Mobile App v2
    r = await mei.post(f"/api/v1/tasks/{t['id']}/projects", json={"project_id": other})
    assert r.status_code in (403, 404)


async def test_private_co_placement_is_never_leaked_to_a_non_member(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    home = await _project(ravi, "Website Revamp")
    other = await _project(ravi, "Mobile App v2")
    t = await _task(ravi, home)
    await ravi.post(f"/api/v1/tasks/{t['id']}/projects", json={"project_id": other})

    mei = await as_user("mei")  # on Product (sees Website Revamp), not a Mobile App v2 member
    # mei can still see the task at all, via the project she IS a member of
    assert (await mei.get(f"/api/v1/tasks/{t['id']}")).status_code == 200
    # ...but the private co-placement itself is hidden from her
    projects = {
        p["project"]["id"]
        for p in (await mei.get(f"/api/v1/tasks/{t['id']}/projects")).json()["data"]
    }
    assert projects == {home}
    other_placements = (await mei.get(f"/api/v1/projects/{home}/other-placements")).json()["data"]
    assert other_placements == []
    # ravi (a member of both) does see it
    ravi_other = {
        row["project"]["id"]
        for row in (await ravi.get(f"/api/v1/projects/{home}/other-placements")).json()["data"]
    }
    assert ravi_other == {other}


async def test_bulk_other_placements_scoped_per_project(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    home = await _project(ravi, "Website Revamp")
    other = await _project(ravi, "Mobile App v2")
    t1 = await _task(ravi, home)
    t2 = await _task(ravi, home)
    await ravi.post(f"/api/v1/tasks/{t1['id']}/projects", json={"project_id": other})

    rows = (await ravi.get(f"/api/v1/projects/{home}/other-placements")).json()["data"]
    by_task = {r["task_id"]: r["project"]["id"] for r in rows}
    assert by_task == {t1["id"]: other}
    assert t2["id"] not in by_task


async def test_undo_add_and_remove(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    home = await _project(ravi, "Website Revamp")
    other = await _project(ravi, "Mobile App v2")
    t = await _task(ravi, home)

    add = await ravi.post(f"/api/v1/tasks/{t['id']}/projects", json={"project_id": other})
    activity_id = add.json()["meta"]["activity_id"]
    assert await ravi.post("/api/v1/undo", json={"activity_id": activity_id})
    projects = {
        p["project"]["id"]
        for p in (await ravi.get(f"/api/v1/tasks/{t['id']}/projects")).json()["data"]
    }
    assert projects == {home}

    await ravi.post(f"/api/v1/tasks/{t['id']}/projects", json={"project_id": other})
    remove = await ravi.delete(f"/api/v1/tasks/{t['id']}/projects/{home}")
    activity_id2 = remove.json()["meta"]["activity_id"]
    u = await ravi.post("/api/v1/undo", json={"activity_id": activity_id2})
    assert u.status_code == 200
    projects2 = {
        p["project"]["id"]
        for p in (await ravi.get(f"/api/v1/tasks/{t['id']}/projects")).json()["data"]
    }
    assert projects2 == {home, other}
