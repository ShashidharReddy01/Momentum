"""S1.1.3 Project members and roles: role matrix, sharing private projects, last-admin guard."""

from __future__ import annotations

from tests.helpers import Clients


async def _users(c) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {
        u["email"].split("@")[0]: u["id"] for u in (await c.get("/api/v1/users")).json()["data"]
    }


async def _project(c, name: str) -> dict:  # type: ignore[no-untyped-def,type-arg]
    return next(p for p in (await c.get("/api/v1/projects")).json()["data"] if p["name"] == name)


async def test_explicit_role_overrides_team_default(as_user: Clients) -> None:
    ravi, mei = await as_user("ravi"), await as_user("mei")
    wr = await _project(ravi, "Website Revamp")
    users = await _users(ravi)
    for role, can_edit in (("viewer", False), ("commenter", False), ("editor", True)):
        await ravi.delete(f"/api/v1/projects/{wr['id']}/members/{users['mei']}")
        r = await ravi.post(
            f"/api/v1/projects/{wr['id']}/members", json={"user_id": users["mei"], "role": role}
        )
        assert r.status_code == 201, r.text
        assert (await _project(mei, "Website Revamp"))["my_role"] == role
        patch = await mei.patch(f"/api/v1/projects/{wr['id']}", json={"name": f"By {role}"})
        assert (patch.status_code == 200) is can_edit, (role, patch.status_code)


async def test_sharing_private_project_makes_it_visible(as_user: Clients) -> None:
    priya, mei = await as_user("priya"), await as_user("mei")
    mobile = await _project(priya, "Mobile App v2")
    users = await _users(priya)
    assert (await mei.get(f"/api/v1/projects/{mobile['id']}")).status_code == 404
    r = await priya.post(
        f"/api/v1/projects/{mobile['id']}/members", json={"user_id": users["mei"], "role": "viewer"}
    )
    assert r.status_code == 201
    got = await mei.get(f"/api/v1/projects/{mobile['id']}")
    assert got.status_code == 200 and got.json()["my_role"] == "viewer"
    # undo the share → hidden again
    await priya.post("/api/v1/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert (await mei.get(f"/api/v1/projects/{mobile['id']}")).status_code == 404


async def test_only_admins_share_and_last_admin_guard(as_user: Clients) -> None:
    ravi, mei = await as_user("ravi"), await as_user("mei")
    wr = await _project(ravi, "Website Revamp")
    users = await _users(ravi)
    r = await mei.post(f"/api/v1/projects/{wr['id']}/members", json={"user_id": users["tom"]})
    assert r.status_code == 403  # mei is only an (implicit) editor
    r = await ravi.patch(
        f"/api/v1/projects/{wr['id']}/members/{users['ravi']}", json={"role": "editor"}
    )
    assert r.status_code == 409 and r.json()["code"] == "last_admin"
    r = await ravi.delete(f"/api/v1/projects/{wr['id']}/members/{users['ravi']}")
    assert r.status_code == 409


async def test_role_change_takes_effect_on_next_request_and_undo(as_user: Clients) -> None:
    priya, ravi = await as_user("priya"), await as_user("ravi")
    mobile = await _project(priya, "Mobile App v2")
    users = await _users(priya)
    r = await priya.patch(
        f"/api/v1/projects/{mobile['id']}/members/{users['ravi']}", json={"role": "viewer"}
    )
    assert r.status_code == 200
    assert (
        await ravi.patch(f"/api/v1/projects/{mobile['id']}", json={"name": "x"})
    ).status_code == 403
    await priya.post("/api/v1/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert (await _project(ravi, "Mobile App v2"))["my_role"] == "editor"


async def test_member_can_leave(as_user: Clients) -> None:
    priya, ravi = await as_user("priya"), await as_user("ravi")
    mobile = await _project(priya, "Mobile App v2")
    users = await _users(ravi)
    assert (
        await ravi.delete(f"/api/v1/projects/{mobile['id']}/members/{users['ravi']}")
    ).status_code == 200
    assert (await ravi.get(f"/api/v1/projects/{mobile['id']}")).status_code == 404


async def test_validation(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    wr = await _project(ravi, "Website Revamp")
    users = await _users(ravi)
    r = await ravi.post(
        f"/api/v1/projects/{wr['id']}/members", json={"user_id": users["tom"], "role": "owner"}
    )
    assert r.status_code == 422
    r = await ravi.post(f"/api/v1/projects/{wr['id']}/members", json={"user_id": users["ravi"]})
    assert r.status_code == 409
