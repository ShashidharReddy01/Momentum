"""S1.2.4: move ordering, bulk actions (all-or-nothing, one undo batch), rebalancing."""

from __future__ import annotations

from sqlalchemy import func, select

from momentum.core.db import UnitOfWork
from momentum.core.settings import Settings
from momentum.domain.tasks import service
from momentum.domain.tasks.models import TaskProject
from tests.helpers import Clients, ctx_for, uid

BASE = "/api/v1"


async def _setup(c, name: str = "Website Revamp") -> tuple[str, dict[str, str]]:  # type: ignore[no-untyped-def]
    pid = next(
        p["id"] for p in (await c.get(f"{BASE}/projects")).json()["data"] if p["name"] == name
    )
    secs = {
        s["name"]: s["id"] for s in (await c.get(f"{BASE}/projects/{pid}/sections")).json()["data"]
    }
    return pid, secs


async def _order(c, pid: str, sid: str) -> list[str]:  # type: ignore[no-untyped-def]
    tasks = (await c.get(f"{BASE}/projects/{pid}/tasks")).json()["data"]
    return [t["title"] for t in tasks if t["section_id"] == sid]


async def _make(c, pid: str, sid: str, titles: list[str]) -> dict[str, str]:  # type: ignore[no-untyped-def]
    r = await c.post(
        f"{BASE}/projects/{pid}/tasks/batch", json={"titles": titles, "section_id": sid}
    )
    assert r.status_code == 201, r.text
    return {t["title"]: t["id"] for t in r.json()["data"]["data"]}


async def _empty_section(c, pid: str, name: str) -> str:  # type: ignore[no-untyped-def]
    r = await c.post(f"{BASE}/projects/{pid}/sections", json={"name": name})
    assert r.status_code == 201, r.text
    return str(r.json()["data"]["id"])


async def test_move_within_and_across_sections(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid, _ = await _setup(ravi)
    a = await _empty_section(ravi, pid, "A")
    b = await _empty_section(ravi, pid, "B")
    ids = await _make(ravi, pid, a, ["1", "2", "3", "4"])
    r = await ravi.post(
        f"{BASE}/tasks/{ids['4']}/move", json={"section_id": a, "before_id": ids["1"]}
    )
    assert r.status_code == 200, r.text
    assert await _order(ravi, pid, a) == ["4", "1", "2", "3"]
    await ravi.post(f"{BASE}/tasks/{ids['1']}/move", json={"section_id": a, "after_id": ids["3"]})
    assert await _order(ravi, pid, a) == ["4", "2", "3", "1"]
    # into an empty section, then back to the end of A
    r = await ravi.post(f"{BASE}/tasks/{ids['2']}/move", json={"section_id": b})
    assert r.json()["data"]["section_id"] == b and await _order(ravi, pid, b) == ["2"]
    mv = await ravi.post(f"{BASE}/tasks/{ids['2']}/move", json={"section_id": a})
    assert await _order(ravi, pid, a) == ["4", "3", "1", "2"]
    # undo the last move → back in B
    await ravi.post(f"{BASE}/undo", json={"activity_id": mv.json()["meta"]["activity_id"]})
    assert await _order(ravi, pid, b) == ["2"]


async def test_move_validation(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid, _ = await _setup(ravi)
    a = await _empty_section(ravi, pid, "A")
    ids = await _make(ravi, pid, a, ["1", "2"])
    r = await ravi.post(
        f"{BASE}/tasks/{ids['1']}/move", json={"section_id": a, "after_id": ids["1"]}
    )
    assert r.status_code == 422 and r.json()["code"] == "invalid_anchor"
    # a section of another project
    _, other = await _setup(ravi, "Mobile App v2")
    r = await ravi.post(
        f"{BASE}/tasks/{ids['1']}/move", json={"section_id": next(iter(other.values()))}
    )
    assert r.status_code == 422 and r.json()["code"] == "cross_project_move"
    # an anchor from another section
    b = await _empty_section(ravi, pid, "B")
    r = await ravi.post(
        f"{BASE}/tasks/{ids['1']}/move", json={"section_id": b, "after_id": ids["2"]}
    )
    assert r.status_code == 404
    assert await _order(ravi, pid, a) == ["1", "2"]


async def test_undo_move_conflicts_after_another_move(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid, _ = await _setup(ravi)
    a = await _empty_section(ravi, pid, "A")
    ids = await _make(ravi, pid, a, ["1", "2", "3"])
    first = await ravi.post(f"{BASE}/tasks/{ids['1']}/move", json={"section_id": a})
    await ravi.post(f"{BASE}/tasks/{ids['1']}/move", json={"section_id": a, "before_id": ids["2"]})
    r = await ravi.post(f"{BASE}/undo", json={"activity_id": first.json()["meta"]["activity_id"]})
    assert r.status_code == 409 and r.json()["code"] == "undo_conflict"


async def test_bulk_move_20_is_one_undo_and_keeps_relative_order(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid, _ = await _setup(ravi)
    a = await _empty_section(ravi, pid, "A")
    b = await _empty_section(ravi, pid, "B")
    titles = [f"T{i:02d}" for i in range(30)]
    ids = await _make(ravi, pid, a, titles)
    await _make(ravi, pid, b, ["b1", "b2"])
    b_ids = {
        t["title"]: t["id"] for t in (await ravi.get(f"{BASE}/projects/{pid}/tasks")).json()["data"]
    }
    # select 20 (every other + tail), sent in scrambled order
    chosen = titles[::2] + titles[1::2][-5:]
    body = {
        "task_ids": [ids[t] for t in reversed(chosen)],
        "action": "move",
        "section_id": b,
        "after_id": b_ids["b1"],
    }
    r = await ravi.post(f"{BASE}/tasks/bulk", json=body)
    assert r.status_code == 200, r.text
    batch = r.json()["meta"]["batch_id"]
    assert batch and len(r.json()["data"]["data"]) == 20
    assert await _order(ravi, pid, b) == ["b1", *sorted(chosen), "b2"]
    assert await _order(ravi, pid, a) == [t for t in titles if t not in chosen]
    await ravi.post(f"{BASE}/undo", json={"batch_id": batch})
    assert await _order(ravi, pid, a) == titles
    assert await _order(ravi, pid, b) == ["b1", "b2"]


async def test_bulk_update_complete_delete_with_batch_undo(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid, _ = await _setup(ravi)
    a = await _empty_section(ravi, pid, "A")
    ids = await _make(ravi, pid, a, ["1", "2", "3"])
    users = {
        u["email"].split("@")[0]: u["id"] for u in (await ravi.get(f"{BASE}/users")).json()["data"]
    }
    all_ids = list(ids.values())
    r = await ravi.post(
        f"{BASE}/tasks/bulk",
        json={
            "task_ids": all_ids,
            "action": "update",
            "patch": {"assignee_id": users["ana"], "due_on": "2026-10-10"},
        },
    )
    assert r.status_code == 200, r.text
    assert {t["assignee_id"] for t in r.json()["data"]["data"]} == {users["ana"]}
    await ravi.post(f"{BASE}/undo", json={"batch_id": r.json()["meta"]["batch_id"]})
    tasks = (await ravi.get(f"{BASE}/projects/{pid}/tasks")).json()["data"]
    assert all(
        t["assignee_id"] is None and t["due_on"] is None for t in tasks if t["id"] in all_ids
    )
    # complete where one is already complete: no error, undo restores only what changed
    await ravi.post(f"{BASE}/tasks/{ids['1']}/complete")
    r = await ravi.post(f"{BASE}/tasks/bulk", json={"task_ids": all_ids, "action": "complete"})
    assert r.status_code == 200
    assert await _order(ravi, pid, a) == []
    await ravi.post(f"{BASE}/undo", json={"batch_id": r.json()["meta"]["batch_id"]})
    assert await _order(ravi, pid, a) == ["2", "3"]
    # delete + undo
    r = await ravi.post(
        f"{BASE}/tasks/bulk", json={"task_ids": [ids["2"], ids["3"]], "action": "delete"}
    )
    assert await _order(ravi, pid, a) == []
    await ravi.post(f"{BASE}/undo", json={"batch_id": r.json()["meta"]["batch_id"]})
    assert await _order(ravi, pid, a) == ["2", "3"]


async def test_bulk_is_all_or_nothing_and_validated(as_user: Clients) -> None:
    ravi, tom = await as_user("ravi"), await as_user("tom")
    pid, _ = await _setup(ravi)
    a = await _empty_section(ravi, pid, "A")
    ids = list((await _make(ravi, pid, a, ["1", "2"])).values())
    # a task tom can't see makes the whole request fail, nothing changes
    hidden = "00000000-0000-7000-8000-000000000000"
    r = await ravi.post(
        f"{BASE}/tasks/bulk", json={"task_ids": [*ids, hidden], "action": "complete"}
    )
    assert r.status_code == 404
    assert await _order(ravi, pid, a) == ["1", "2"]
    # tom (not on the team) can't act at all
    r = await tom.post(f"{BASE}/tasks/bulk", json={"task_ids": ids, "action": "delete"})
    assert r.status_code == 404
    # limits and required fields
    r = await ravi.post(
        f"{BASE}/tasks/bulk", json={"task_ids": [ids[0]] * 501, "action": "complete"}
    )
    assert r.status_code == 422
    r = await ravi.post(f"{BASE}/tasks/bulk", json={"task_ids": ids, "action": "move"})
    assert r.status_code == 422
    r = await ravi.post(f"{BASE}/tasks/bulk", json={"task_ids": ids, "action": "update"})
    assert r.status_code == 422
    # duplicates are ignored
    r = await ravi.post(
        f"{BASE}/tasks/bulk", json={"task_ids": [ids[0], ids[0]], "action": "complete"}
    )
    assert r.status_code == 200 and len(r.json()["data"]["data"]) == 1


async def test_viewer_cannot_bulk(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid, _ = await _setup(ravi)
    a = await _empty_section(ravi, pid, "A")
    ids = list((await _make(ravi, pid, a, ["1"])).values())
    users = {
        u["email"].split("@")[0]: u["id"] for u in (await ravi.get(f"{BASE}/users")).json()["data"]
    }
    await ravi.post(
        f"{BASE}/projects/{pid}/members", json={"user_id": users["mei"], "role": "viewer"}
    )
    mei = await as_user("mei")
    r = await mei.post(f"{BASE}/tasks/bulk", json={"task_ids": ids, "action": "complete"})
    assert r.status_code == 403
    r = await mei.post(f"{BASE}/tasks/{ids[0]}/move", json={"section_id": a})
    assert r.status_code == 403


async def test_repeated_front_inserts_rebalance(
    as_user: Clients, uow: UnitOfWork, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    pid, _ = await _setup(ravi)
    a = await _empty_section(ravi, pid, "A")
    ctx = await ctx_for(uow, settings, "ravi")
    first = None
    async with uow.transaction() as s:
        for i in range(400):
            m = await service.create_task(
                s, ctx, uid(pid), f"N{i}", section_id=uid(a), before_id=first
            )
            first = m.entity[0].id
    async with uow.transaction() as s:
        longest = (
            await s.execute(
                select(func.max(func.length(TaskProject.position))).where(
                    TaskProject.section_id == uid(a)
                )
            )
        ).scalar_one()
    assert longest <= 40
    assert await _order(ravi, pid, a) == [f"N{i}" for i in reversed(range(400))]
