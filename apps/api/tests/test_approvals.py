"""S4.4.1 Approvals: task type `approval`, decide (approve/request changes/reject), permissions
(only the assignee or a project admin, never an agent), notifications, undo, and the
`approval.decided` rule trigger."""

from __future__ import annotations

import dataclasses
from typing import Any

import httpx
import pytest

from momentum.core.context import Ctx
from momentum.core.db import UnitOfWork
from momentum.core.errors import Forbidden
from momentum.core.settings import Settings
from momentum.domain.rules.engine import run_rules
from momentum.domain.tasks.service import decide_approval
from tests.helpers import Clients, ctx_for


async def _project(c: httpx.AsyncClient, name: str = "Website Revamp") -> str:
    return next(
        p["id"] for p in (await c.get("/api/v1/projects")).json()["data"] if p["name"] == name
    )


async def _user_id(c: httpx.AsyncClient, local: str) -> str:
    users = (await c.get("/api/v1/dev/users")).json()
    return str(next(u["id"] for u in users if u["email"] == f"{local}@acme-demo.test"))


async def _approval(c: httpx.AsyncClient, pid: str, assignee_id: str, **extra: Any) -> dict:
    r = await c.post(f"/api/v1/projects/{pid}/tasks", json={"title": "Sign off on launch"})
    assert r.status_code == 201, r.text
    task = r.json()["data"]
    up = await c.patch(f"/api/v1/tasks/{task['id']}", json={"assignee_id": assignee_id, **extra})
    assert up.status_code == 200, up.text
    conv = await c.post(f"/api/v1/tasks/{task['id']}/convert", json={"type": "approval"})
    assert conv.status_code == 200, conv.text
    return conv.json()["data"]


async def test_convert_to_approval_starts_pending_and_notifies_the_assignee(
    as_user: Clients,
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    mei_id = await _user_id(ravi, "mei")
    t = await _approval(ravi, pid, mei_id)
    assert t["type"] == "approval"
    assert t["approval_state"] == "pending"

    mei = await as_user("mei")
    notes = (await mei.get("/api/v1/notifications")).json()["data"]
    assert any(n["kind"] == "approval_requested" and n["entity_id"] == t["id"] for n in notes)


async def test_the_assignee_can_approve_and_it_completes_the_task(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    mei_id = await _user_id(ravi, "mei")
    t = await _approval(ravi, pid, mei_id)

    mei = await as_user("mei")
    r = await mei.post(
        f"/api/v1/tasks/{t['id']}/approval/decide", json={"decision": "approved", "comment": "LGTM"}
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["approval_state"] == "approved"
    assert data["completed_at"] is not None

    feed = await ravi.get(f"/api/v1/tasks/{t['id']}/feed")
    comments = [i for i in feed.json()["data"] if i.get("kind") == "comment"]
    assert any(
        "LGTM" in span["text"]
        for c in comments
        for para in c["comment"]["body"]["content"]
        for span in para.get("content", [])
    )


async def test_a_project_admin_can_decide_even_if_not_the_assignee(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    mei_id = await _user_id(ravi, "mei")
    t = await _approval(ravi, pid, mei_id)

    r = await ravi.post(f"/api/v1/tasks/{t['id']}/approval/decide", json={"decision": "rejected"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["approval_state"] == "rejected"
    assert r.json()["data"]["completed_at"] is None


async def test_neither_assignee_nor_admin_cannot_decide(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    mei_id = await _user_id(ravi, "mei")
    t = await _approval(ravi, pid, mei_id)

    kim = await as_user("kim")  # not on the Product team at all
    r = await kim.post(f"/api/v1/tasks/{t['id']}/approval/decide", json={"decision": "approved"})
    assert r.status_code in (403, 404)


async def test_deciding_a_task_thats_not_an_approval_fails(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    r = await ravi.post(f"/api/v1/projects/{pid}/tasks", json={"title": "Ordinary task"})
    task_id = r.json()["data"]["id"]
    dec = await ravi.post(f"/api/v1/tasks/{task_id}/approval/decide", json={"decision": "approved"})
    assert dec.status_code == 422


async def test_deciding_twice_conflicts(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    mei_id = await _user_id(ravi, "mei")
    t = await _approval(ravi, pid, mei_id)

    first = await ravi.post(
        f"/api/v1/tasks/{t['id']}/approval/decide", json={"decision": "approved"}
    )
    assert first.status_code == 200
    second = await ravi.post(
        f"/api/v1/tasks/{t['id']}/approval/decide", json={"decision": "rejected"}
    )
    assert second.status_code == 409


async def test_undo_reopens_the_approval(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    mei_id = await _user_id(ravi, "mei")
    t = await _approval(ravi, pid, mei_id)

    dec = await ravi.post(f"/api/v1/tasks/{t['id']}/approval/decide", json={"decision": "approved"})
    activity_id = dec.json()["meta"]["activity_id"]

    u = await ravi.post("/api/v1/undo", json={"activity_id": activity_id})
    assert u.status_code == 200
    after = (await ravi.get(f"/api/v1/tasks/{t['id']}")).json()
    assert after["approval_state"] == "pending"
    assert after["completed_at"] is None


async def test_an_agent_cannot_decide(
    as_user: Clients, uow: UnitOfWork, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    mei_id = await _user_id(ravi, "mei")
    t = await _approval(ravi, pid, mei_id)

    ctx = await ctx_for(uow, settings, "mei")
    agent_ctx: Ctx = dataclasses.replace(ctx, actor=dataclasses.replace(ctx.actor, is_agent=True))
    async with uow.transaction() as s:
        with pytest.raises(Forbidden):
            await decide_approval(s, agent_ctx, t["id"], "approved")


async def test_approval_decided_trigger_fires_a_rule(
    as_user: Clients, uow: UnitOfWork, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    mei_id = await _user_id(ravi, "mei")
    t = await _approval(ravi, pid, mei_id)
    rule = await ravi.post(
        "/api/v1/rules",
        json={
            "name": "On rejection",
            "project_id": pid,
            "trigger": {"type": "approval.decided", "decision": "rejected"},
            "actions": [{"type": "add_comment", "text": "Please revise and resubmit."}],
        },
    )
    assert rule.status_code == 201, rule.text

    mei = await as_user("mei")
    dec = await mei.post(f"/api/v1/tasks/{t['id']}/approval/decide", json={"decision": "rejected"})
    assert dec.status_code == 200, dec.text

    async with uow.transaction() as s:
        await run_rules(s, settings)
    feed = await ravi.get(f"/api/v1/tasks/{t['id']}/feed")
    comments = [i["comment"] for i in feed.json()["data"] if i.get("kind") == "comment"]
    texts = [
        span["text"]
        for c in comments
        for para in c["body"]["content"]
        for span in para.get("content", [])
    ]
    assert any("Please revise and resubmit." in t for t in texts)


async def test_approval_decided_trigger_with_no_decision_filter_is_accepted(
    as_user: Clients,
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    rule = await ravi.post(
        "/api/v1/rules",
        json={
            "name": "On any decision",
            "project_id": pid,
            "trigger": {"type": "approval.decided"},
            "actions": [{"type": "mark_complete"}],
        },
    )
    assert rule.status_code == 201, rule.text
