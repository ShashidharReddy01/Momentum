"""S1.1.1 Teams: acceptance criteria, permission matrix, undo, events."""

from __future__ import annotations

from sqlalchemy import select

from momentum.core.activity import Activity
from momentum.core.db import UnitOfWork
from momentum.core.events import OutboxEvent
from tests.helpers import Clients


async def _create(c, name: str = "Design", **extra):  # type: ignore[no-untyped-def]
    r = await c.post("/api/v1/teams", json={"name": name, **extra})
    assert r.status_code == 201, r.text
    return r.json()


async def test_member_creates_team_and_becomes_lead(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    body = await _create(ravi, "Design", color="proj-3")
    assert body["data"]["my_role"] == "lead"
    assert body["data"]["member_count"] == 1
    assert body["data"]["members"][0]["user"]["email"] == "ravi@acme-demo.test"
    assert body["meta"]["activity_id"]
    names = [t["name"] for t in (await ravi.get("/api/v1/teams")).json()["data"]]
    assert "Design" in names and "Marketing" not in names  # Ravi is not in Marketing


async def test_visibility_members_vs_admin(as_user: Clients) -> None:
    ravi, ana, admin = await as_user("ravi"), await as_user("ana"), await as_user("admin")
    team = (await _create(ravi))["data"]
    assert (await ana.get(f"/api/v1/teams/{team['id']}")).status_code == 404
    assert "Design" not in [t["name"] for t in (await ana.get("/api/v1/teams")).json()["data"]]
    admin_teams = (await admin.get("/api/v1/teams")).json()["data"]
    assert [t["name"] for t in admin_teams if t["name"] == "Design"] == ["Design"]
    assert next(t for t in admin_teams if t["name"] == "Design")["my_role"] is None


async def test_only_leads_and_admins_edit(as_user: Clients) -> None:
    ravi, ana, admin = await as_user("ravi"), await as_user("ana"), await as_user("admin")
    team = (await _create(ravi))["data"]
    users = {
        u["email"].split("@")[0]: u["id"] for u in (await ravi.get("/api/v1/users")).json()["data"]
    }
    assert (
        await ravi.post(f"/api/v1/teams/{team['id']}/members", json={"user_id": users["ana"]})
    ).status_code == 201
    r = await ana.patch(f"/api/v1/teams/{team['id']}", json={"name": "Nope"})
    assert r.status_code == 403
    assert (
        await admin.patch(f"/api/v1/teams/{team['id']}", json={"name": "Design 2"})
    ).status_code == 200
    assert (
        await ravi.patch(f"/api/v1/teams/{team['id']}", json={"description": "UI + UX"})
    ).status_code == 200


async def test_rename_then_undo(as_user: Clients, uow: UnitOfWork) -> None:
    ravi = await as_user("ravi")
    team = (await _create(ravi))["data"]
    r = await ravi.patch(f"/api/v1/teams/{team['id']}", json={"name": "Design Systems"})
    assert r.json()["data"]["name"] == "Design Systems"
    undo = await ravi.post("/api/v1/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert undo.status_code == 200, undo.text
    assert (await ravi.get(f"/api/v1/teams/{team['id']}")).json()["name"] == "Design"
    again = await ravi.post("/api/v1/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert again.status_code == 409


async def test_undo_blocked_when_changed_since(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    team = (await _create(ravi))["data"]
    first = await ravi.patch(f"/api/v1/teams/{team['id']}", json={"name": "A"})
    await ravi.patch(f"/api/v1/teams/{team['id']}", json={"name": "B"})
    r = await ravi.post("/api/v1/undo", json={"activity_id": first.json()["meta"]["activity_id"]})
    assert r.status_code == 409
    assert r.json()["code"] == "undo_conflict"


async def test_only_actor_can_undo(as_user: Clients) -> None:
    ravi, ana = await as_user("ravi"), await as_user("ana")
    team = (await _create(ravi))["data"]
    r = await ravi.patch(f"/api/v1/teams/{team['id']}", json={"name": "X"})
    assert (
        await ana.post("/api/v1/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    ).status_code == 403


async def test_delete_and_undo_restore(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    team = (await _create(ravi))["data"]
    r = await ravi.delete(f"/api/v1/teams/{team['id']}")
    assert r.status_code == 200
    assert (await ravi.get(f"/api/v1/teams/{team['id']}")).status_code == 404
    await ravi.post("/api/v1/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert (await ravi.get(f"/api/v1/teams/{team['id']}")).status_code == 200


async def test_last_lead_cannot_leave_or_be_demoted(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    team = (await _create(ravi))["data"]
    me = team["members"][0]["user"]["id"]
    r = await ravi.delete(f"/api/v1/teams/{team['id']}/members/{me}")
    assert r.status_code == 409 and r.json()["code"] == "last_lead"
    assert "lead" in r.json()["detail"]
    r = await ravi.patch(f"/api/v1/teams/{team['id']}/members/{me}", json={"role": "member"})
    assert r.status_code == 409


async def test_member_management_and_leave(as_user: Clients) -> None:
    ravi, ana = await as_user("ravi"), await as_user("ana")
    team = (await _create(ravi))["data"]
    users = {
        u["email"].split("@")[0]: u["id"] for u in (await ravi.get("/api/v1/users")).json()["data"]
    }
    tid = team["id"]
    assert (
        await ravi.post(f"/api/v1/teams/{tid}/members", json={"user_id": users["ana"]})
    ).status_code == 201
    dup = await ravi.post(f"/api/v1/teams/{tid}/members", json={"user_id": users["ana"]})
    assert dup.status_code == 409 and dup.json()["code"] == "duplicate"
    # Ana (member) can't add others, but can leave
    assert (
        await ana.post(f"/api/v1/teams/{tid}/members", json={"user_id": users["tom"]})
    ).status_code == 403
    promote = await ravi.patch(f"/api/v1/teams/{tid}/members/{users['ana']}", json={"role": "lead"})
    assert promote.status_code == 200
    # now Ravi can leave because Ana is also a lead
    assert (await ravi.delete(f"/api/v1/teams/{tid}/members/{users['ravi']}")).status_code == 200
    detail = (await ana.get(f"/api/v1/teams/{tid}")).json()
    assert [m["user"]["email"] for m in detail["members"]] == ["ana@acme-demo.test"]


async def test_remove_member_undo_readds(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    team = (await _create(ravi))["data"]
    users = {
        u["email"].split("@")[0]: u["id"] for u in (await ravi.get("/api/v1/users")).json()["data"]
    }
    await ravi.post(f"/api/v1/teams/{team['id']}/members", json={"user_id": users["mei"]})
    r = await ravi.delete(f"/api/v1/teams/{team['id']}/members/{users['mei']}")
    await ravi.post("/api/v1/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert (await ravi.get(f"/api/v1/teams/{team['id']}")).json()["member_count"] == 2


async def test_validation(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    assert (await ravi.post("/api/v1/teams", json={"name": ""})).status_code == 422
    assert (
        await ravi.post("/api/v1/teams", json={"name": "X", "color": "#fff"})
    ).status_code == 422
    assert (await ravi.post("/api/v1/teams", json={"name": "X", "bogus": 1})).status_code == 422


async def test_activity_and_outbox_written(as_user: Clients, uow: UnitOfWork) -> None:
    ravi = await as_user("ravi")
    team = (await _create(ravi))["data"]
    async with uow.transaction() as s:
        acts = (
            (await s.execute(select(Activity.verb).where(Activity.entity_type == "team")))
            .scalars()
            .all()
        )
        events = (
            (await s.execute(select(OutboxEvent).where(OutboxEvent.entity_type == "team")))
            .scalars()
            .all()
        )
    assert "team.created" in acts
    assert events and events[-1].payload["channels"] == [f"team:{team['id']}"]


async def test_users_search(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    r = await ravi.get("/api/v1/users", params={"q": "sou"})
    assert [u["name"] for u in r.json()["data"]] == ["Ana Souza"]
