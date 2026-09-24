"""S1.1.2 Projects: visibility matrix, archive, delete, undo, favorites, permissions."""

from __future__ import annotations

from tests.helpers import Clients


async def _team_id(c, name: str) -> str:  # type: ignore[no-untyped-def]
    teams = (await c.get("/api/v1/teams")).json()["data"]
    return next(t["id"] for t in teams if t["name"] == name)


async def _project(c, name: str) -> dict:  # type: ignore[no-untyped-def,type-arg]
    projects = (await c.get("/api/v1/projects")).json()["data"]
    return next(p for p in projects if p["name"] == name)


async def _names(c, **params) -> set[str]:  # type: ignore[no-untyped-def]
    return {p["name"] for p in (await c.get("/api/v1/projects", params=params)).json()["data"]}


async def test_visibility_matrix(as_user: Clients) -> None:
    # Seed: Product = ravi(lead), ana, priya, mei, admin.
    # Marketing = ana(lead), tom, lena, noor.
    # "Website Revamp" (Product, team), "Mobile App v2" (Product, private: priya + ravi),
    # "Q4 Launch Campaign" (Marketing, team).
    ravi, mei, tom, admin = [await as_user(u) for u in ("ravi", "mei", "tom", "admin")]
    assert {"Website Revamp", "Mobile App v2"} <= await _names(ravi)
    assert "Q4 Launch Campaign" not in await _names(ravi)
    assert "Website Revamp" in await _names(mei)
    assert "Mobile App v2" not in await _names(mei)  # private, not a member
    assert await _names(tom) == {"Q4 Launch Campaign"}
    admin_sees = await _names(admin)
    assert {"Website Revamp", "Q4 Launch Campaign", "Vendor Onboarding"} <= admin_sees
    assert "Mobile App v2" not in admin_sees  # private projects stay private even for admins


async def test_private_project_is_404_for_non_members(as_user: Clients) -> None:
    ravi, mei = await as_user("ravi"), await as_user("mei")
    private = await _project(ravi, "Mobile App v2")
    assert (await mei.get(f"/api/v1/projects/{private['id']}")).status_code == 404
    assert (
        await mei.patch(f"/api/v1/projects/{private['id']}", json={"name": "x"})
    ).status_code == 404


async def test_roles_team_member_editor_explicit_admin(as_user: Clients) -> None:
    ravi, mei, admin = await as_user("ravi"), await as_user("mei"), await as_user("admin")
    wr = await _project(ravi, "Website Revamp")  # ravi is owner/admin
    assert wr["my_role"] == "admin"
    assert (await _project(mei, "Website Revamp"))["my_role"] == "editor"
    assert (await _project(admin, "Vendor Onboarding"))["my_role"] == "admin"
    # editors can rename, only admins change privacy or archive
    assert (
        await mei.patch(f"/api/v1/projects/{wr['id']}", json={"name": "Website 2.0"})
    ).status_code == 200
    r = await mei.patch(f"/api/v1/projects/{wr['id']}", json={"privacy": "private"})
    assert r.status_code == 403
    assert (await mei.post(f"/api/v1/projects/{wr['id']}/archive")).status_code == 403
    # S2.2.3: the default view is admin-only too (roadmap AC: "per-project default view (project
    # admin)") — editors used to be able to set it alongside name/color; not anymore.
    r = await mei.patch(f"/api/v1/projects/{wr['id']}", json={"default_view": "board"})
    assert r.status_code == 403
    r = await ravi.patch(f"/api/v1/projects/{wr['id']}", json={"default_view": "board"})
    assert r.status_code == 200
    assert r.json()["data"]["default_view"] == "board"


async def test_create_requires_team_membership_and_adds_default_section(as_user: Clients) -> None:
    ravi, tom = await as_user("ravi"), await as_user("tom")
    product = await _team_id(ravi, "Product")
    r = await ravi.post(
        "/api/v1/projects", json={"team_id": product, "name": "Pricing", "color": "proj-2"}
    )
    assert r.status_code == 201, r.text
    body = r.json()["data"]
    assert body["my_role"] == "admin" and body["team_name"] == "Product"
    assert [s["name"] for s in body["sections"]] == ["To do"]
    assert body["members"][0]["user"]["email"] == "ravi@acme-demo.test"
    denied = await tom.post("/api/v1/projects", json={"team_id": product, "name": "Sneaky"})
    assert denied.status_code == 404  # tom can't see the Product team


async def test_archive_hides_from_list_but_reachable(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    wr = await _project(ravi, "Website Revamp")
    r = await ravi.post(f"/api/v1/projects/{wr['id']}/archive")
    assert r.status_code == 200 and r.json()["data"]["archived_at"]
    assert "Website Revamp" not in await _names(ravi)
    assert "Website Revamp" in await _names(ravi, archived=True)
    assert (await ravi.get(f"/api/v1/projects/{wr['id']}")).status_code == 200
    # undo archive
    await ravi.post("/api/v1/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert "Website Revamp" in await _names(ravi)


async def test_rename_undo_and_delete_undo(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    wr = await _project(ravi, "Website Revamp")
    r = await ravi.patch(f"/api/v1/projects/{wr['id']}", json={"name": "Site"})
    await ravi.post("/api/v1/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert (await ravi.get(f"/api/v1/projects/{wr['id']}")).json()["name"] == "Website Revamp"
    d = await ravi.delete(f"/api/v1/projects/{wr['id']}")
    assert (await ravi.get(f"/api/v1/projects/{wr['id']}")).status_code == 404
    await ravi.post("/api/v1/undo", json={"activity_id": d.json()["meta"]["activity_id"]})
    assert (await ravi.get(f"/api/v1/projects/{wr['id']}")).status_code == 200


async def test_deleted_team_hides_its_projects(as_user: Clients) -> None:
    jordan, admin = await as_user("jordan"), await as_user("admin")
    ops = await _team_id(jordan, "Operations")
    await jordan.delete(f"/api/v1/teams/{ops}")
    assert "Vendor Onboarding" not in await _names(admin)


async def test_favorites_order_and_unstar(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    wr, mobile = await _project(ravi, "Website Revamp"), await _project(ravi, "Mobile App v2")
    assert (await ravi.put(f"/api/v1/favorites/projects/{wr['id']}")).status_code == 200
    await ravi.put(f"/api/v1/favorites/projects/{mobile['id']}")
    favs = [p["name"] for p in (await ravi.get("/api/v1/favorites")).json()["data"]]
    assert favs == ["Website Revamp", "Mobile App v2"]
    # move Mobile before Website
    await ravi.put(f"/api/v1/favorites/projects/{mobile['id']}", json={"before_id": wr["id"]})
    favs = [p["name"] for p in (await ravi.get("/api/v1/favorites")).json()["data"]]
    assert favs == ["Mobile App v2", "Website Revamp"]
    assert (await _project(ravi, "Website Revamp"))["is_favorite"] is True
    await ravi.delete(f"/api/v1/favorites/projects/{wr['id']}")
    assert [p["name"] for p in (await ravi.get("/api/v1/favorites")).json()["data"]] == [
        "Mobile App v2"
    ]


async def test_validation(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    product = await _team_id(ravi, "Product")
    assert (
        await ravi.post("/api/v1/projects", json={"team_id": product, "name": ""})
    ).status_code == 422
    assert (
        await ravi.post(
            "/api/v1/projects", json={"team_id": product, "name": "x", "privacy": "public"}
        )
    ).status_code == 422
    wr = await _project(ravi, "Website Revamp")
    assert (
        await ravi.patch(f"/api/v1/projects/{wr['id']}", json={"default_view": "gantt"})
    ).status_code == 422
