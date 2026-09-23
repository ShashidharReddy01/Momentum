"""S1.2.1 Sections: create/rename/move/delete, ordering, permissions, undo."""

from __future__ import annotations

import asyncio

from tests.helpers import Clients


async def _wr(c) -> str:  # type: ignore[no-untyped-def]
    return next(
        p["id"]
        for p in (await c.get("/api/v1/projects")).json()["data"]
        if p["name"] == "Website Revamp"
    )


async def _names(c, pid: str) -> list[str]:  # type: ignore[no-untyped-def]
    return [s["name"] for s in (await c.get(f"/api/v1/projects/{pid}/sections")).json()["data"]]


async def _ids(c, pid: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {
        s["name"]: s["id"] for s in (await c.get(f"/api/v1/projects/{pid}/sections")).json()["data"]
    }


async def test_create_at_end_after_and_before(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _wr(ravi)
    assert await _names(ravi, pid) == ["Backlog", "In progress", "Review", "Done"]
    await ravi.post(f"/api/v1/projects/{pid}/sections", json={"name": "Archive"})
    ids = await _ids(ravi, pid)
    await ravi.post(
        f"/api/v1/projects/{pid}/sections", json={"name": "QA", "after_id": ids["Review"]}
    )
    await ravi.post(
        f"/api/v1/projects/{pid}/sections", json={"name": "Ideas", "before_id": ids["Backlog"]}
    )
    assert await _names(ravi, pid) == [
        "Ideas",
        "Backlog",
        "In progress",
        "Review",
        "QA",
        "Done",
        "Archive",
    ]


async def test_rename_move_and_undo(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _wr(ravi)
    ids = await _ids(ravi, pid)
    r = await ravi.patch(f"/api/v1/sections/{ids['Review']}", json={"name": "Code review"})
    assert r.json()["data"]["name"] == "Code review"
    m = await ravi.post(f"/api/v1/sections/{ids['Done']}/move", json={"before_id": ids["Backlog"]})
    assert m.status_code == 200
    assert await _names(ravi, pid) == ["Done", "Backlog", "In progress", "Code review"]
    await ravi.post("/api/v1/undo", json={"activity_id": m.json()["meta"]["activity_id"]})
    assert await _names(ravi, pid) == ["Backlog", "In progress", "Code review", "Done"]
    await ravi.post("/api/v1/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert "Review" in await _names(ravi, pid)


async def test_delete_restore_and_last_section_guard(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _wr(ravi)
    ids = await _ids(ravi, pid)
    d = await ravi.delete(f"/api/v1/sections/{ids['Review']}")
    assert d.status_code == 200 and d.json()["meta"]["batch_id"]
    assert "Review" not in await _names(ravi, pid)
    await ravi.post("/api/v1/undo", json={"activity_id": d.json()["meta"]["activity_id"]})
    assert await _names(ravi, pid) == ["Backlog", "In progress", "Review", "Done"]
    for name in ("Backlog", "In progress", "Review"):
        assert (await ravi.delete(f"/api/v1/sections/{ids[name]}")).status_code == 200
    last = await ravi.delete(f"/api/v1/sections/{ids['Done']}")
    assert last.status_code == 409 and last.json()["code"] == "last_section"


async def test_permissions(as_user: Clients) -> None:
    ravi, tom = await as_user("ravi"), await as_user("tom")
    pid = await _wr(ravi)
    ids = await _ids(ravi, pid)
    assert (await tom.get(f"/api/v1/projects/{pid}/sections")).status_code == 404
    assert (
        await tom.patch(f"/api/v1/sections/{ids['Done']}", json={"name": "x"})
    ).status_code == 404
    users = {
        u["email"].split("@")[0]: u["id"] for u in (await ravi.get("/api/v1/users")).json()["data"]
    }
    await ravi.post(
        f"/api/v1/projects/{pid}/members", json={"user_id": users["mei"], "role": "commenter"}
    )
    mei = await as_user("mei")
    assert (await mei.get(f"/api/v1/projects/{pid}/sections")).status_code == 200
    assert (
        await mei.post(f"/api/v1/projects/{pid}/sections", json={"name": "Nope"})
    ).status_code == 403


async def test_concurrent_inserts_keep_distinct_order(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _wr(ravi)
    ids = await _ids(ravi, pid)
    results = await asyncio.gather(
        *[
            ravi.post(
                f"/api/v1/projects/{pid}/sections",
                json={"name": f"N{i}", "after_id": ids["Backlog"]},
            )
            for i in range(8)
        ]
    )
    assert all(r.status_code == 201 for r in results)
    sections = (await ravi.get(f"/api/v1/projects/{pid}/sections")).json()["data"]
    positions = [s["position"] for s in sections]
    assert len(set(positions)) == len(positions)
    names = [s["name"] for s in sections]
    assert names[0] == "Backlog" and names[-3:] == ["In progress", "Review", "Done"]


async def test_validation(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _wr(ravi)
    ids = await _ids(ravi, pid)
    assert (
        await ravi.post(f"/api/v1/projects/{pid}/sections", json={"name": ""})
    ).status_code == 422
    assert (
        await ravi.post(f"/api/v1/sections/{ids['Done']}/move", json={"after_id": ids["Done"]})
    ).status_code == 422
    r = await ravi.delete(f"/api/v1/sections/{ids['Done']}", params={"tasks": "nuke"})
    assert r.status_code == 422
