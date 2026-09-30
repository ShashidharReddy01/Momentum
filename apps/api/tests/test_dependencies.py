"""S2.4.2 Dependencies: blocked-by/blocking, cycle detection, complete-with-blockers confirmation,
the bulk "waiting on" endpoint, the picker search, permissions, and undo."""

from __future__ import annotations

from tests.helpers import Clients


async def _project(c, name: str = "Website Revamp") -> str:  # type: ignore[no-untyped-def]
    return next(
        p["id"] for p in (await c.get("/api/v1/projects")).json()["data"] if p["name"] == name
    )


async def _task(c, pid: str, title: str = "T") -> dict:  # type: ignore[no-untyped-def]
    r = await c.post(f"/api/v1/projects/{pid}/tasks", json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def test_add_and_list_blocked_by_and_blocking(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    a = await _task(ravi, pid, "A")
    b = await _task(ravi, pid, "B")

    r = await ravi.post(f"/api/v1/tasks/{a['id']}/dependencies", json={"depends_on_id": b["id"]})
    assert r.status_code == 201, r.text
    assert r.json()["data"]["id"] == b["id"]

    deps_a = (await ravi.get(f"/api/v1/tasks/{a['id']}/dependencies")).json()
    assert [t["id"] for t in deps_a["blocked_by"]] == [b["id"]]
    assert deps_a["blocking"] == []

    deps_b = (await ravi.get(f"/api/v1/tasks/{b['id']}/dependencies")).json()
    assert [t["id"] for t in deps_b["blocking"]] == [a["id"]]
    assert deps_b["blocked_by"] == []


async def test_cannot_depend_on_self(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    a = await _task(ravi, pid, "A")
    r = await ravi.post(f"/api/v1/tasks/{a['id']}/dependencies", json={"depends_on_id": a["id"]})
    assert r.status_code == 422


async def test_duplicate_dependency_conflicts(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    a = await _task(ravi, pid, "A")
    b = await _task(ravi, pid, "B")
    await ravi.post(f"/api/v1/tasks/{a['id']}/dependencies", json={"depends_on_id": b["id"]})
    r = await ravi.post(f"/api/v1/tasks/{a['id']}/dependencies", json={"depends_on_id": b["id"]})
    assert r.status_code == 409


async def test_direct_cycle_is_rejected(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    a = await _task(ravi, pid, "A")
    b = await _task(ravi, pid, "B")
    await ravi.post(f"/api/v1/tasks/{a['id']}/dependencies", json={"depends_on_id": b["id"]})
    r = await ravi.post(f"/api/v1/tasks/{b['id']}/dependencies", json={"depends_on_id": a["id"]})
    assert r.status_code == 422
    assert r.json()["code"] == "cycle"


async def test_transitive_cycle_is_rejected(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    a = await _task(ravi, pid, "A")
    b = await _task(ravi, pid, "B")
    c = await _task(ravi, pid, "C")
    # A blocked by B, B blocked by C: A -> B -> C
    await ravi.post(f"/api/v1/tasks/{a['id']}/dependencies", json={"depends_on_id": b["id"]})
    await ravi.post(f"/api/v1/tasks/{b['id']}/dependencies", json={"depends_on_id": c["id"]})
    # C depending on A would close the loop
    r = await ravi.post(f"/api/v1/tasks/{c['id']}/dependencies", json={"depends_on_id": a["id"]})
    assert r.status_code == 422


async def test_remove_dependency(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    a = await _task(ravi, pid, "A")
    b = await _task(ravi, pid, "B")
    await ravi.post(f"/api/v1/tasks/{a['id']}/dependencies", json={"depends_on_id": b["id"]})
    r = await ravi.delete(f"/api/v1/tasks/{a['id']}/dependencies/{b['id']}")
    assert r.status_code == 200
    deps = (await ravi.get(f"/api/v1/tasks/{a['id']}/dependencies")).json()
    assert deps["blocked_by"] == []


async def test_completing_a_task_with_incomplete_blockers_needs_confirmation(
    as_user: Clients,
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    a = await _task(ravi, pid, "A")
    b = await _task(ravi, pid, "B")
    await ravi.post(f"/api/v1/tasks/{a['id']}/dependencies", json={"depends_on_id": b["id"]})

    r = await ravi.post(f"/api/v1/tasks/{a['id']}/complete")
    assert r.status_code == 409
    assert r.json()["code"] == "has_incomplete_blockers"

    r2 = await ravi.post(f"/api/v1/tasks/{a['id']}/complete", params={"force": "true"})
    assert r2.status_code == 200
    assert r2.json()["data"]["completed_at"] is not None


async def test_completing_the_blocker_first_needs_no_confirmation(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    a = await _task(ravi, pid, "A")
    b = await _task(ravi, pid, "B")
    await ravi.post(f"/api/v1/tasks/{a['id']}/dependencies", json={"depends_on_id": b["id"]})
    await ravi.post(f"/api/v1/tasks/{b['id']}/complete")
    r = await ravi.post(f"/api/v1/tasks/{a['id']}/complete")
    assert r.status_code == 200


async def test_editor_access_required_to_manage_dependencies(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    a = await _task(ravi, pid, "A")
    b = await _task(ravi, pid, "B")
    kim = await as_user("kim")  # not on the Product team
    r = await kim.post(f"/api/v1/tasks/{a['id']}/dependencies", json={"depends_on_id": b["id"]})
    assert r.status_code in (403, 404)


async def test_bulk_blocked_tasks_for_a_project(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    a = await _task(ravi, pid, "A")
    b = await _task(ravi, pid, "B")
    c = await _task(ravi, pid, "C")
    await ravi.post(f"/api/v1/tasks/{a['id']}/dependencies", json={"depends_on_id": b["id"]})

    ids = {
        row["task_id"]
        for row in (await ravi.get(f"/api/v1/projects/{pid}/blocked-tasks")).json()["data"]
    }
    assert ids == {a["id"]}
    assert c["id"] not in ids

    # completing the blocker removes it from the "waiting on" set
    await ravi.post(f"/api/v1/tasks/{b['id']}/complete")
    ids2 = {
        row["task_id"]
        for row in (await ravi.get(f"/api/v1/projects/{pid}/blocked-tasks")).json()["data"]
    }
    assert ids2 == set()


async def test_search_project_tasks_for_the_picker(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    a = await _task(ravi, pid, "Design the homepage")
    await _task(ravi, pid, "Write copy")

    r = await ravi.get(f"/api/v1/projects/{pid}/tasks/search", params={"q": "Design the"})
    assert r.status_code == 200
    titles = [t["title"] for t in r.json()["data"]]
    assert titles == ["Design the homepage"]

    r2 = await ravi.get(
        f"/api/v1/projects/{pid}/tasks/search", params={"q": "", "exclude": a["id"]}
    )
    excluded_ids = {t["id"] for t in r2.json()["data"]}
    assert a["id"] not in excluded_ids


async def test_undo_add_and_remove_dependency(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    a = await _task(ravi, pid, "A")
    b = await _task(ravi, pid, "B")

    add = await ravi.post(f"/api/v1/tasks/{a['id']}/dependencies", json={"depends_on_id": b["id"]})
    await ravi.post("/api/v1/undo", json={"activity_id": add.json()["meta"]["activity_id"]})
    assert (await ravi.get(f"/api/v1/tasks/{a['id']}/dependencies")).json()["blocked_by"] == []

    add2 = await ravi.post(f"/api/v1/tasks/{a['id']}/dependencies", json={"depends_on_id": b["id"]})
    remove = await ravi.delete(f"/api/v1/tasks/{a['id']}/dependencies/{b['id']}")
    u = await ravi.post("/api/v1/undo", json={"activity_id": remove.json()["meta"]["activity_id"]})
    assert u.status_code == 200
    assert [
        t["id"]
        for t in (await ravi.get(f"/api/v1/tasks/{a['id']}/dependencies")).json()["blocked_by"]
    ] == [b["id"]]
    assert add2.status_code == 201


async def test_project_dependency_edges_for_the_timeline(as_user: Clients) -> None:
    """S6.1.1a: one call returns every edge between two tasks of the project; an edge to a task
    in another project, or to a deleted task, is left out; a non-member gets 404."""
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    other = await _project(ravi, "Mobile App v2")
    a = await _task(ravi, pid, "A")
    b = await _task(ravi, pid, "B")
    c = await _task(ravi, pid, "C")
    elsewhere = await _task(ravi, other, "Elsewhere")
    gone = await _task(ravi, pid, "Gone")
    for task, blocker in ((a, b), (b, c), (a, elsewhere), (c, gone)):
        r = await ravi.post(
            f"/api/v1/tasks/{task['id']}/dependencies", json={"depends_on_id": blocker["id"]}
        )
        assert r.status_code == 201, r.text
    assert (await ravi.delete(f"/api/v1/tasks/{gone['id']}")).status_code == 200

    r = await ravi.get(f"/api/v1/projects/{pid}/dependencies")
    assert r.status_code == 200, r.text
    edges = {(e["task_id"], e["depends_on_id"]) for e in r.json()["data"]}
    assert edges == {(a["id"], b["id"]), (b["id"], c["id"])}

    mei = await as_user("mei")  # not a member of the private project
    assert (await mei.get(f"/api/v1/projects/{other}/dependencies")).status_code == 404


async def test_timeline_perf_seed_is_dated_linked_and_rerunnable(
    as_user: Clients,
    uow,
    settings,  # type: ignore[no-untyped-def]
) -> None:
    """S6.1.1a: ``seed --perf`` adds a dated, dependency-linked timeline project; re-running adds
    nothing."""
    from momentum.seed import TIMELINE_PERF_PROJECT, seed_perf

    async with uow.transaction() as session:
        first = await seed_perf(session, settings, n=10, timeline_n=60)
    async with uow.transaction() as session:
        again = await seed_perf(session, settings, n=10, timeline_n=60)
    assert first["timeline_tasks_created"] == 60
    assert first["timeline_dependencies"] > 10
    assert again == {
        "perf_tasks_created": 0,
        "timeline_tasks_created": 0,
        "timeline_dependencies": 0,
    }

    ravi = await as_user("ravi")
    pid = await _project(ravi, TIMELINE_PERF_PROJECT)
    tasks = (await ravi.get(f"/api/v1/projects/{pid}/tasks")).json()["data"]
    assert sum(1 for t in tasks if t["due_on"]) > len(tasks) // 2
    assert any(t["type"] == "milestone" for t in tasks) or len(tasks) < 60
    edges = (await ravi.get(f"/api/v1/projects/{pid}/dependencies")).json()["data"]
    assert len(edges) == first["timeline_dependencies"]
