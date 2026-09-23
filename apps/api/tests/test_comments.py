"""S1.4.1 Comments, mentions, reactions: permissions, validation, mention rules, undo."""

from __future__ import annotations

from sqlalchemy import select

from momentum.core.db import UnitOfWork
from momentum.domain.comments.models import Mention
from tests.helpers import Clients, uid

BASE = "/api/v1"


def body(*parts: dict) -> dict:  # type: ignore[type-arg]
    return {"type": "doc", "content": [{"type": "paragraph", "content": list(parts)}]}


def text(t: str) -> dict:  # type: ignore[type-arg]
    return {"type": "text", "text": t}


def mention(kind: str, id_: str, label: str = "x") -> dict:  # type: ignore[type-arg]
    return {"type": "mention", "attrs": {"id": id_, "label": label, "kind": kind}}


async def _users(c) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {
        u["email"].split("@")[0]: u["id"] for u in (await c.get(f"{BASE}/users")).json()["data"]
    }


async def _task(c, project: str = "Website Revamp") -> dict:  # type: ignore[no-untyped-def]
    pid = next(
        p["id"] for p in (await c.get(f"{BASE}/projects")).json()["data"] if p["name"] == project
    )
    return (await c.post(f"{BASE}/projects/{pid}/tasks", json={"title": "Discuss"})).json()["data"]  # type: ignore[no-any-return]


async def test_comment_permissions_and_auto_follow(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    u = await _users(ravi)
    t = await _task(ravi)
    await ravi.post(
        f"{BASE}/projects/{t['project_id']}/members", json={"user_id": u["mei"], "role": "viewer"}
    )
    await ravi.post(
        f"{BASE}/projects/{t['project_id']}/members",
        json={"user_id": u["priya"], "role": "commenter"},
    )
    mei, priya = await as_user("mei"), await as_user("priya")
    url = f"{BASE}/tasks/{t['id']}/comments"
    assert (await mei.post(url, json={"body": body(text("hi"))})).status_code == 403
    r = await priya.post(url, json={"body": body(text("Looks good"))})
    assert r.status_code == 201, r.text
    assert r.json()["data"]["can_edit"] is True
    assert u["priya"] in (await ravi.get(f"{BASE}/tasks/{t['id']}")).json()["followers"]
    listed = (await mei.get(url)).json()["data"]  # viewers can read
    assert [c["body"] for c in listed] == [body(text("Looks good"))]
    assert listed[0]["can_edit"] is False and listed[0]["can_delete"] is False


async def test_validation_and_sanitizing(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    t = await _task(ravi)
    url = f"{BASE}/tasks/{t['id']}/comments"
    r = await ravi.post(url, json={"body": {"type": "doc", "content": [{"type": "paragraph"}]}})
    assert r.status_code == 422 and r.json()["code"] == "empty_comment"
    evil = body(
        {
            "type": "text",
            "text": "click",
            "marks": [{"type": "link", "attrs": {"href": "javascript:x"}}],
        }
    )
    assert (await ravi.post(url, json={"body": evil})).json()["data"]["body"] == body(text("click"))
    r = await ravi.post(url, json={"body": {"type": "doc", "content": [{"type": "iframe"}]}})
    assert r.status_code == 422


async def test_mentions_follow_and_invisible_targets_are_dropped(
    as_user: Clients, uow: UnitOfWork
) -> None:
    ravi, priya = await as_user("ravi"), await as_user("priya")
    u = await _users(ravi)
    t = await _task(ravi)
    other = await _task(ravi)
    private = await _task(priya, "Mobile App v2")  # ravi is a member there
    tom_private = await _task(priya, "Mobile App v2")
    tom = await as_user("tom")
    doc = body(
        text("cc "),
        mention("user", u["ana"], "Ana"),
        mention("task", other["id"]),
        mention("task", private["id"]),
        mention("user", "not-a-uuid"),
        mention("user", "00000000-0000-7000-8000-000000000000"),
    )
    r = await ravi.post(f"{BASE}/tasks/{t['id']}/comments", json={"body": doc})
    assert r.status_code == 201
    assert u["ana"] in (await ravi.get(f"{BASE}/tasks/{t['id']}")).json()["followers"]
    async with uow.transaction() as s:
        rows = (
            (
                await s.execute(
                    select(Mention).where(Mention.source_id == uid(r.json()["data"]["id"]))
                )
            )
            .scalars()
            .all()
        )
    assert {(m.target_type, str(m.target_id)) for m in rows} == {
        ("user", u["ana"]),
        ("task", other["id"]),
        ("task", private["id"]),
    }
    # tom can't see the private task: mentioning it records nothing (and reveals nothing)
    await ravi.post(f"{BASE}/tasks/{t['id']}/followers", json={"user_id": u["tom"]})
    r = await tom.post(
        f"{BASE}/tasks/{t['id']}/comments",
        json={"body": body(text("x "), mention("task", tom_private["id"]))},
    )
    async with uow.transaction() as s:
        rows = (
            (
                await s.execute(
                    select(Mention).where(Mention.source_id == uid(r.json()["data"]["id"]))
                )
            )
            .scalars()
            .all()
        )
    assert rows == []


async def test_edit_delete_and_undo(as_user: Clients) -> None:
    ravi, ana = await as_user("ravi"), await as_user("ana")
    t = await _task(ravi)
    c = (
        await ravi.post(f"{BASE}/tasks/{t['id']}/comments", json={"body": body(text("v1"))})
    ).json()["data"]
    url = f"{BASE}/comments/{c['id']}"
    assert (await ana.patch(url, json={"body": body(text("hacked"))})).status_code == 403
    e = await ravi.patch(url, json={"body": body(text("v2"))})
    assert e.status_code == 200 and e.json()["data"]["edited_at"]
    await ravi.post(f"{BASE}/undo", json={"activity_id": e.json()["meta"]["activity_id"]})
    comments = (await ravi.get(f"{BASE}/tasks/{t['id']}/comments")).json()["data"]
    assert comments[0]["body"] == body(text("v1"))
    # undo refuses when edited again since
    e1 = await ravi.patch(url, json={"body": body(text("v3"))})
    await ravi.patch(url, json={"body": body(text("v4"))})
    r = await ravi.post(f"{BASE}/undo", json={"activity_id": e1.json()["meta"]["activity_id"]})
    assert r.status_code == 409
    # delete: others can't (ana is an editor, not the project admin); the author can, and undo it
    assert (await ana.delete(url)).status_code == 403
    d = await ravi.delete(url)
    assert (await ravi.get(f"{BASE}/tasks/{t['id']}/comments")).json()["data"] == []
    await ravi.post(f"{BASE}/undo", json={"activity_id": d.json()["meta"]["activity_id"]})
    assert len((await ravi.get(f"{BASE}/tasks/{t['id']}/comments")).json()["data"]) == 1


async def test_project_admin_can_delete_others_comments(as_user: Clients) -> None:
    ravi, ana = await as_user("ravi"), await as_user("ana")
    t = await _task(ravi)  # ravi created the project? Website Revamp is owned by ravi (admin)
    c = (
        await ana.post(f"{BASE}/tasks/{t['id']}/comments", json={"body": body(text("mine"))})
    ).json()["data"]
    listed = (await ravi.get(f"{BASE}/tasks/{t['id']}/comments")).json()["data"]
    assert listed[0]["can_delete"] is True and listed[0]["can_edit"] is False
    assert (await ravi.delete(f"{BASE}/comments/{c['id']}")).status_code == 200


async def test_reactions(as_user: Clients) -> None:
    ravi, ana = await as_user("ravi"), await as_user("ana")
    u = await _users(ravi)
    t = await _task(ravi)
    c = (
        await ravi.post(f"{BASE}/tasks/{t['id']}/comments", json={"body": body(text("ship it"))})
    ).json()["data"]
    url = f"{BASE}/comments/{c['id']}/reactions"
    await ravi.post(url, json={"emoji": "🎉"})
    await ana.post(url, json={"emoji": "🎉"})
    r = await ana.post(url, json={"emoji": "👍"})
    assert r.json()["data"]["reactions"] == [
        {"emoji": "🎉", "user_ids": [u["ravi"], u["ana"]]},
        {"emoji": "👍", "user_ids": [u["ana"]]},
    ]
    await ana.post(url, json={"emoji": "🎉"})  # idempotent
    r = await ana.post(url, json={"emoji": "🎉", "active": False})
    assert r.json()["data"]["reactions"][0] == {"emoji": "🎉", "user_ids": [u["ravi"]]}
    assert (await ana.post(url, json={"emoji": "💩"})).status_code == 422


async def test_mention_search_only_returns_visible_things(as_user: Clients) -> None:
    priya, tom = await as_user("priya"), await as_user("tom")
    await _task(priya, "Mobile App v2")
    r = (await tom.get(f"{BASE}/mentions/search", params={"q": "Discuss"})).json()
    assert r["tasks"] == []
    assert all(
        p["name"] != "Mobile App v2"
        for p in (await tom.get(f"{BASE}/mentions/search", params={"q": "Mobile"})).json()[
            "projects"
        ]
    )
    r = (await priya.get(f"{BASE}/mentions/search", params={"q": "Discuss"})).json()
    assert [t["title"] for t in r["tasks"]] == ["Discuss"]
    assert any(
        u["name"].startswith("Ana")
        for u in (await tom.get(f"{BASE}/mentions/search", params={"q": "ana"})).json()["users"]
    )
