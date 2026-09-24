"""S2.3.3 Tags: workspace tag library CRUD, task attach/detach (incl. inline-create-by-name),
the bulk per-project endpoint, the cross-project tag page, and permissions."""

from __future__ import annotations

from tests.helpers import Clients


async def _project(c, name: str = "Website Revamp") -> str:  # type: ignore[no-untyped-def]
    return next(
        p["id"] for p in (await c.get("/api/v1/projects")).json()["data"] if p["name"] == name
    )


async def _task(c, pid: str) -> dict:  # type: ignore[no-untyped-def]
    sec = (await c.get(f"/api/v1/projects/{pid}/sections")).json()["data"][0]["id"]
    r = await c.post(f"/api/v1/projects/{pid}/tasks", json={"title": "T", "section_id": sec})
    return r.json()["data"]


async def _tag(c, **body):  # type: ignore[no-untyped-def]
    r = await c.post("/api/v1/tags", json=body)
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def test_create_list_and_default_color(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    tag = await _tag(ravi, name="Urgent")
    assert tag["name"] == "Urgent"
    assert tag["color"] == "#94a3b8"
    names = [t["name"] for t in (await ravi.get("/api/v1/tags")).json()["data"]]
    assert "Urgent" in names


async def test_create_rejects_duplicate_name_case_insensitively(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    await _tag(ravi, name="Urgent", color="#ff0000")
    r = await ravi.post("/api/v1/tags", json={"name": "urgent", "color": "#00ff00"})
    assert r.status_code == 409


async def test_rename_and_recolor(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    tag = await _tag(ravi, name="Urgent")
    r = await ravi.patch(f"/api/v1/tags/{tag['id']}", json={"name": "Blocked", "color": "#ff0000"})
    assert r.status_code == 200
    assert r.json()["data"]["name"] == "Blocked"
    assert r.json()["data"]["color"] == "#ff0000"


async def test_rename_to_an_existing_name_conflicts(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    a = await _tag(ravi, name="Urgent")
    await _tag(ravi, name="Blocked")
    r = await ravi.patch(f"/api/v1/tags/{a['id']}", json={"name": "blocked"})
    assert r.status_code == 409


async def test_delete_hides_it_from_the_library(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    tag = await _tag(ravi, name="Urgent")
    r = await ravi.delete(f"/api/v1/tags/{tag['id']}")
    assert r.status_code == 200
    names = [t["name"] for t in (await ravi.get("/api/v1/tags")).json()["data"]]
    assert "Urgent" not in names


async def test_attach_by_id_and_read_back(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    t = await _task(ravi, pid)
    tag = await _tag(ravi, name="Urgent")
    r = await ravi.post(f"/api/v1/tasks/{t['id']}/tags", json={"tag_id": tag["id"]})
    assert r.status_code == 201
    names = [x["name"] for x in (await ravi.get(f"/api/v1/tasks/{t['id']}/tags")).json()["data"]]
    assert names == ["Urgent"]


async def test_attach_by_name_creates_the_tag_inline(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    t = await _task(ravi, pid)
    r = await ravi.post(f"/api/v1/tasks/{t['id']}/tags", json={"name": "New Tag"})
    assert r.status_code == 201
    assert r.json()["data"]["name"] == "New Tag"
    assert "New Tag" in [t["name"] for t in (await ravi.get("/api/v1/tags")).json()["data"]]


async def test_attach_by_name_reuses_an_existing_tag_case_insensitively(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    t = await _task(ravi, pid)
    existing = await _tag(ravi, name="Urgent")
    r = await ravi.post(f"/api/v1/tasks/{t['id']}/tags", json={"name": "urgent"})
    assert r.status_code == 201
    assert r.json()["data"]["id"] == existing["id"]
    lib = (await ravi.get("/api/v1/tags")).json()["data"]
    assert len([x for x in lib if x["name"].lower() == "urgent"]) == 1


async def test_attaching_the_same_tag_twice_is_a_noop_not_a_conflict(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    t = await _task(ravi, pid)
    tag = await _tag(ravi, name="Urgent")
    await ravi.post(f"/api/v1/tasks/{t['id']}/tags", json={"tag_id": tag["id"]})
    r = await ravi.post(f"/api/v1/tasks/{t['id']}/tags", json={"tag_id": tag["id"]})
    assert r.status_code == 201
    names = [x["name"] for x in (await ravi.get(f"/api/v1/tasks/{t['id']}/tags")).json()["data"]]
    assert names == ["Urgent"]


async def test_remove_tag_from_task(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    t = await _task(ravi, pid)
    tag = await _tag(ravi, name="Urgent")
    await ravi.post(f"/api/v1/tasks/{t['id']}/tags", json={"tag_id": tag["id"]})
    r = await ravi.delete(f"/api/v1/tasks/{t['id']}/tags/{tag['id']}")
    assert r.status_code == 200
    assert (await ravi.get(f"/api/v1/tasks/{t['id']}/tags")).json()["data"] == []


async def test_tagging_a_task_needs_editor_access_to_it(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    t = await _task(ravi, pid)
    kim = await as_user("kim")  # not on the Product team
    r = await kim.post(f"/api/v1/tasks/{t['id']}/tags", json={"name": "Urgent"})
    assert r.status_code in (403, 404)


async def test_bulk_task_tags_for_a_project_in_one_call(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    t1 = await _task(ravi, pid)
    t2 = await _task(ravi, pid)
    tag = await _tag(ravi, name="Urgent")
    await ravi.post(f"/api/v1/tasks/{t1['id']}/tags", json={"tag_id": tag["id"]})

    r = await ravi.get(f"/api/v1/projects/{pid}/task-tags")
    assert r.status_code == 200
    by_task = {row["task_id"] for row in r.json()["data"]}
    assert t1["id"] in by_task
    assert t2["id"] not in by_task

    # a second project's task tags don't leak in
    other = await _project(ravi, "Mobile App v2")
    ot = await _task(ravi, other)
    await ravi.post(f"/api/v1/tasks/{ot['id']}/tags", json={"tag_id": tag["id"]})
    r2 = await ravi.get(f"/api/v1/projects/{pid}/task-tags")
    assert ot["id"] not in {row["task_id"] for row in r2.json()["data"]}


async def test_tag_page_lists_tasks_across_projects(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    other = await _project(ravi, "Mobile App v2")
    tag = await _tag(ravi, name="Urgent")
    t1 = await _task(ravi, pid)
    t2 = await _task(ravi, other)
    untagged = await _task(ravi, pid)
    await ravi.post(f"/api/v1/tasks/{t1['id']}/tags", json={"tag_id": tag["id"]})
    await ravi.post(f"/api/v1/tasks/{t2['id']}/tags", json={"tag_id": tag["id"]})

    r = await ravi.get(f"/api/v1/tags/{tag['id']}/tasks")
    assert r.status_code == 200
    ids = {t["id"] for t in r.json()["data"]}
    assert ids == {t1["id"], t2["id"]}
    assert untagged["id"] not in ids


async def test_tag_page_never_leaks_a_private_project_task(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    kim = await as_user("kim")
    pid = await _project(ravi)
    tag = await _tag(ravi, name="Urgent")
    t = await _task(ravi, pid)
    await ravi.post(f"/api/v1/tasks/{t['id']}/tags", json={"tag_id": tag["id"]})

    r = await kim.get(f"/api/v1/tags/{tag['id']}/tasks")
    assert r.status_code == 200
    assert t["id"] not in {row["id"] for row in r.json()["data"]}
