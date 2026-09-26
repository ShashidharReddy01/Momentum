"""S2.7.3: invite users (admin-only, idempotent) and the first-run onboarding checklist."""

from __future__ import annotations

from tests.helpers import Clients


async def test_admin_can_invite_a_new_member(as_user: Clients) -> None:
    admin = await as_user("admin")
    r = await admin.post(
        "/api/v1/users/invite",
        json={"email": "New.Hire@ACME-demo.test", "name": "New Hire", "role": "member"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "new.hire@acme-demo.test"  # normalized
    assert body["status"] == "invited"
    assert body["role"] == "member"

    members = (await admin.get("/api/v1/users/members")).json()["data"]
    invited = next(m for m in members if m["email"] == "new.hire@acme-demo.test")
    assert invited["status"] == "invited"


async def test_inviting_an_existing_email_is_idempotent_not_an_error(as_user: Clients) -> None:
    admin = await as_user("admin")
    r = await admin.post(
        "/api/v1/users/invite", json={"email": "ravi@acme-demo.test", "role": "member"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active"  # ravi is already a real, active seeded user


async def test_non_admin_cannot_invite(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    r = await ravi.post(
        "/api/v1/users/invite", json={"email": "someone@acme-demo.test", "role": "member"}
    )
    assert r.status_code == 403, r.text


async def test_non_admin_cannot_list_members(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    r = await ravi.get("/api/v1/users/members")
    assert r.status_code == 403, r.text


async def test_onboarding_checklist_reflects_real_activity(as_user: Clients) -> None:
    lena = await as_user("lena")  # a seeded member who (per fixtures) hasn't created a project
    status = (await lena.get("/api/v1/me/onboarding")).json()
    assert status == {
        "created_project": False,
        "tried_import": False,
        "used_command_palette": False,
        "dismissed": False,
    }

    r = await lena.post("/api/v1/teams", json={"name": "Lena's New Team"})
    assert r.status_code == 201, r.text
    team_id = r.json()["data"]["id"]
    r = await lena.post(
        "/api/v1/projects",
        json={"name": "Lena's Project", "team_id": team_id, "color": "proj-1"},
    )
    assert r.status_code == 201, r.text

    status = (await lena.get("/api/v1/me/onboarding")).json()
    assert status["created_project"] is True
    assert status["tried_import"] is False


async def test_patch_onboarding_sets_palette_and_dismissed_flags(as_user: Clients) -> None:
    noor = await as_user("noor")
    r = await noor.patch("/api/v1/me/onboarding", json={"used_command_palette": True})
    assert r.status_code == 200, r.text
    assert r.json()["used_command_palette"] is True
    assert r.json()["dismissed"] is False

    r = await noor.patch("/api/v1/me/onboarding", json={"dismissed": True})
    assert r.status_code == 200, r.text
    assert r.json()["dismissed"] is True
    assert r.json()["used_command_palette"] is True  # earlier flag not clobbered


async def test_csv_import_marks_tried_import(as_user: Clients) -> None:
    ravi = await as_user("ravi")  # owns "Website Revamp", so has editor access to import into it
    pid = next(
        p["id"]
        for p in (await ravi.get("/api/v1/projects")).json()["data"]
        if p["name"] == "Website Revamp"
    )
    r = await ravi.post(
        f"/api/v1/projects/{pid}/import/csv",
        files={"file": ("t.csv", "Title\nA task\n", "text/csv")},
        data={"mapping": '{"title_col": "Title"}'},
    )
    assert r.status_code == 200, r.text
    status = (await ravi.get("/api/v1/me/onboarding")).json()
    assert status["tried_import"] is True
