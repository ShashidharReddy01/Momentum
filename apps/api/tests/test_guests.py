"""E7.0 (H61): a guest sees only the projects explicitly shared with them (auth-and-permissions.md
§4), never a project through a team they're in, and only the people of those projects in
pickers, @mentions, the directory and workload."""

from __future__ import annotations

from tests.helpers import Clients

B = "/api/v1"


async def test_a_guest_sees_only_shared_projects_and_their_people(as_user: Clients) -> None:
    admin, priya = await as_user("admin"), await as_user("priya")
    users = {
        u["email"].split("@")[0]: u["id"] for u in (await admin.get(f"{B}/users")).json()["data"]
    }
    as_member = {p["id"]: p["name"] for p in (await priya.get(f"{B}/projects")).json()["data"]}
    shared = set()
    for pid in as_member:
        members = (await priya.get(f"{B}/projects/{pid}")).json()["members"]
        if any(m["user"]["id"] == users["priya"] for m in members):
            shared.add(pid)
    assert shared and shared != set(as_member), "seed: priya needs both kinds of project"

    r = await admin.patch(f"{B}/users/{users['priya']}", json={"role": "guest"})
    assert r.status_code == 200, r.text

    as_guest = {p["id"] for p in (await priya.get(f"{B}/projects")).json()["data"]}
    assert as_guest == shared
    team_only = next(iter(set(as_member) - shared))
    assert (await priya.get(f"{B}/projects/{team_only}")).status_code == 404
    assert (await priya.get(f"{B}/projects/{team_only}/tasks")).status_code == 404

    people = {users["priya"]}
    for pid in shared:
        detail = (await priya.get(f"{B}/projects/{pid}")).json()
        people |= {m["user"]["id"] for m in detail["members"]}
        if detail["privacy"] == "team":
            team = (await admin.get(f"{B}/teams/{detail['team_id']}/members")).json()["data"]
            people |= {m["user"]["id"] for m in team}
    seen = {u["id"] for u in (await priya.get(f"{B}/users")).json()["data"]}
    assert users["priya"] in seen
    assert seen <= people
    assert len(seen) < len(users)
    mentions = (await priya.get(f"{B}/mentions/search?q=")).json()["users"]
    assert {u["id"] for u in mentions} <= seen
    grid = (await priya.get(f"{B}/workload")).json()
    assert {row["user_id"] for row in grid["people"]} <= seen

    # back to member: everything returns
    await admin.patch(f"{B}/users/{users['priya']}", json={"role": "member"})
    assert {p["id"] for p in (await priya.get(f"{B}/projects")).json()["data"]} == set(as_member)
