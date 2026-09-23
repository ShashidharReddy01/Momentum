"""S1.3.1: description saves — hash-based conflicts, coalesced activity, undo, validation."""

from __future__ import annotations

from sqlalchemy import select

from momentum.core.activity import Activity
from momentum.core.db import UnitOfWork
from tests.helpers import Clients, uid

BASE = "/api/v1"


def text_doc(text: str) -> dict:  # type: ignore[type-arg]
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


async def _task(c) -> dict:  # type: ignore[no-untyped-def]
    pid = next(
        p["id"]
        for p in (await c.get(f"{BASE}/projects")).json()["data"]
        if p["name"] == "Website Revamp"
    )
    t = (await c.post(f"{BASE}/projects/{pid}/tasks", json={"title": "Spec"})).json()["data"]
    return (await c.get(f"{BASE}/tasks/{t['id']}")).json()  # type: ignore[no-any-return]


async def test_detail_includes_pane_fields(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    t = await _task(ravi)
    assert t["description"] is None and t["description_hash"] == ""
    assert t["project"]["name"] == "Website Revamp" and t["section"]["name"] == "Backlog"
    assert t["created_by"] and t["updated_at"]


async def test_save_and_conflicts_only_on_concurrent_description_edits(as_user: Clients) -> None:
    ravi, ana = await as_user("ravi"), await as_user("ana")
    t = await _task(ravi)
    url = f"{BASE}/tasks/{t['id']}"
    r = await ravi.patch(url, json={"description": text_doc("v1"), "description_base": ""})
    assert r.status_code == 200, r.text
    h1 = r.json()["data"]["description_hash"]
    assert h1 and r.json()["data"]["description"] == text_doc("v1")
    # an unrelated change by someone else does not block the next save
    await ana.patch(url, json={"due_on": "2026-10-01"})
    r = await ravi.patch(url, json={"description": text_doc("v2"), "description_base": h1})
    assert r.status_code == 200
    h2 = r.json()["data"]["description_hash"]
    # ana edits the description from the old base -> conflict, nothing overwritten
    r = await ana.patch(url, json={"description": text_doc("ana"), "description_base": h1})
    assert r.status_code == 409 and r.json()["code"] == "version_conflict"
    assert (await ravi.get(url)).json()["description"] == text_doc("v2")
    # "keep mine" = save again against the latest hash
    r = await ana.patch(url, json={"description": text_doc("ana"), "description_base": h2})
    assert r.status_code == 200
    # no base = last write wins (used by undo and API clients that don't care)
    assert (await ravi.patch(url, json={"description": None})).json()["data"]["description"] is None


async def test_autosaves_coalesce_into_one_activity_and_undo_restores_original(
    as_user: Clients, uow: UnitOfWork
) -> None:
    ravi = await as_user("ravi")
    t = await _task(ravi)
    url = f"{BASE}/tasks/{t['id']}"
    base = ""
    ids = set()
    for text in ["H", "He", "Hel", "Hello"]:
        r = await ravi.patch(url, json={"description": text_doc(text), "description_base": base})
        base = r.json()["data"]["description_hash"]
        ids.add(r.json()["meta"]["activity_id"])
    assert len(ids) == 1
    async with uow.transaction() as s:
        rows = (
            (
                await s.execute(
                    select(Activity).where(
                        Activity.entity_id == uid(t["id"]), Activity.verb == "task.updated"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1 and rows[0].diff == {"description": [None, "Hello"]}
    r = await ravi.post(f"{BASE}/undo", json={"activity_id": ids.pop()})
    assert r.status_code == 200, r.text
    assert (await ravi.get(url)).json()["description"] is None


async def test_other_edits_break_the_coalescing(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    t = await _task(ravi)
    url = f"{BASE}/tasks/{t['id']}"
    a = (await ravi.patch(url, json={"description": text_doc("one")})).json()["meta"]["activity_id"]
    await ravi.patch(url, json={"title": "Spec 2"})
    b = (await ravi.patch(url, json={"description": text_doc("two")})).json()["meta"]["activity_id"]
    assert a != b


async def test_validation_sanitizing_and_permissions(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    t = await _task(ravi)
    url = f"{BASE}/tasks/{t['id']}"
    r = await ravi.patch(
        url, json={"description": {"type": "doc", "content": [{"type": "script"}]}}
    )
    assert r.status_code == 422 and r.json()["code"] == "invalid_rich_text"
    evil = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "x",
                        "marks": [{"type": "link", "attrs": {"href": "javascript:alert(1)"}}],
                    }
                ],
            }
        ],
    }
    r = await ravi.patch(url, json={"description": evil})
    assert r.json()["data"]["description"] == text_doc("x")
    users = {
        u["email"].split("@")[0]: u["id"] for u in (await ravi.get(f"{BASE}/users")).json()["data"]
    }
    await ravi.post(
        f"{BASE}/projects/{t['project']['id']}/members",
        json={"user_id": users["mei"], "role": "commenter"},
    )
    mei = await as_user("mei")
    assert (await mei.patch(url, json={"description": text_doc("no")})).status_code == 403
