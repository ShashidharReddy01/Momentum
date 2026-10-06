"""S7.5.4 admin completeness: an admin changes roles and disables / re-enables members (undoable,
never the last admin or themselves), hands a departing member's work to someone else (privacy
kept), sees and retries failed background jobs, and searches the audit trail (which names only
what the admin may see). Members get none of it."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import text

from momentum.core.db import UnitOfWork
from tests.helpers import Clients

B = "/api/v1"


async def _id(c: httpx.AsyncClient, local: str) -> str:
    people = (await c.get(f"{B}/users/members")).json()["data"]
    return next(u["id"] for u in people if u["email"] == f"{local}@acme-demo.test")


async def _project(c: httpx.AsyncClient, name: str) -> str:
    return next(  # type: ignore[no-any-return]
        p["id"] for p in (await c.get(f"{B}/projects")).json()["data"] if p["name"] == name
    )


async def test_roles_and_disabling_with_their_guards(as_user: Clients) -> None:
    admin, ravi = await as_user("admin"), await as_user("ravi")
    ana, me = await _id(admin, "ana"), await _id(admin, "admin")

    r = await admin.patch(f"{B}/users/{ana}", json={"role": "admin"})
    assert r.status_code == 200 and r.json()["data"]["role"] == "admin"
    undo = await admin.post(f"{B}/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert undo.status_code == 200, undo.text
    assert (
        next(u for u in (await admin.get(f"{B}/users/members")).json()["data"] if u["id"] == ana)[
            "role"
        ]
        == "member"
    )

    # disabled: can't sign in any more; re-enabled: back (invited if they never signed in)
    r = await admin.patch(f"{B}/users/{ana}", json={"status": "disabled"})
    assert r.json()["data"]["status"] == "disabled"
    r = await admin.patch(f"{B}/users/{ana}", json={"status": "active"})
    assert r.json()["data"]["status"] in ("active", "invited")

    # never yourself, never the last admin, never by a member
    assert (await admin.patch(f"{B}/users/{me}", json={"status": "disabled"})).status_code == 409
    assert (await admin.patch(f"{B}/users/{me}", json={"role": "member"})).status_code == 409
    assert (await ravi.patch(f"{B}/users/{ana}", json={"role": "admin"})).status_code == 403
    assert (await admin.patch(f"{B}/users/{ana}", json={"role": "owner"})).status_code == 422


async def test_a_disabled_member_is_signed_out_of_everything(as_user: Clients) -> None:
    admin, ravi = await as_user("admin"), await as_user("ravi")
    rid = await _id(admin, "ravi")
    assert (await ravi.get(f"{B}/me")).status_code == 200
    await admin.patch(f"{B}/users/{rid}", json={"status": "disabled"})
    assert (await ravi.get(f"{B}/me")).status_code in (401, 403)


async def test_handing_work_on_keeps_privacy(as_user: Clients) -> None:
    admin, ravi = await as_user("admin"), await as_user("ravi")
    ravi_id, mei_id = await _id(admin, "ravi"), await _id(admin, "mei")
    web, private = await _project(ravi, "Website Revamp"), await _project(ravi, "Mobile App v2")
    for pid, title in ((web, "Visible work"), (private, "Private work")):
        t = (await ravi.post(f"{B}/projects/{pid}/tasks", json={"title": title})).json()["data"]
        await ravi.patch(f"{B}/tasks/{t['id']}", json={"assignee_id": ravi_id})
    r = await admin.post(f"{B}/users/{ravi_id}/transfer", json={"to_user_id": mei_id})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["tasks"] >= 1 and out["not_visible"] >= 1  # the private task stays for its admins
    mine = (await ravi.get(f"{B}/me/tasks")).json()["data"]
    titles = {t["title"] for t in mine}
    assert "Private work" in titles and "Visible work" not in titles
    assert (
        await admin.post(f"{B}/users/{ravi_id}/transfer", json={"to_user_id": ravi_id})
    ).status_code == 422


async def test_failed_jobs_can_be_seen_and_retried(as_user: Clients, uow: UnitOfWork) -> None:
    admin, ravi = await as_user("admin"), await as_user("ravi")
    async with uow.transaction() as s:
        job_id = (
            await s.execute(
                text(
                    "insert into procrastinate_jobs (queue_name, task_name, args, status) "
                    "values ('momentum_default', 'momentum:example', '{}', 'failed') returning id"
                )
            )
        ).scalar_one()
    listed = (await admin.get(f"{B}/admin/jobs", params={"status": "failed"})).json()
    assert listed["counts"]["failed"] >= 1
    assert any(j["id"] == job_id and j["task_name"] == "momentum:example" for j in listed["jobs"])
    r = await admin.post(f"{B}/admin/jobs/{job_id}/retry")
    assert r.status_code == 200 and r.json()["status"] == "todo"
    assert (await admin.post(f"{B}/admin/jobs/{job_id}/retry")).status_code == 404  # not failed now
    assert (await ravi.get(f"{B}/admin/jobs")).status_code == 403


async def test_the_audit_trail_names_only_what_the_admin_may_see(as_user: Clients) -> None:
    admin, ravi = await as_user("admin"), await as_user("ravi")
    web, private = await _project(ravi, "Website Revamp"), await _project(ravi, "Mobile App v2")
    seen = (await ravi.post(f"{B}/projects/{web}/tasks", json={"title": "Audited open"})).json()
    hidden = (
        await ravi.post(f"{B}/projects/{private}/tasks", json={"title": "Secret plan"})
    ).json()
    entries: list[dict[str, Any]] = (
        await admin.get(f"{B}/admin/activity", params={"verb": "task.", "limit": 100})
    ).json()["data"]
    by_entity = {e["entity_id"]: e for e in entries}
    assert by_entity[seen["data"]["id"]]["entity_label"] == "Audited open"
    assert by_entity[seen["data"]["id"]]["actor_name"] == "Ravi Kumar"
    assert by_entity[hidden["data"]["id"]]["entity_label"] is None  # private: not named
    assert "Secret plan" not in str(entries)
    ravi_id = await _id(admin, "ravi")
    only_ravi = (await admin.get(f"{B}/admin/activity", params={"actor_id": ravi_id})).json()[
        "data"
    ]
    assert only_ravi and {e["actor_id"] for e in only_ravi} == {ravi_id}
    assert (await ravi.get(f"{B}/admin/activity")).status_code == 403
