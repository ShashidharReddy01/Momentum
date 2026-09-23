"""S1.3.3 Followers: follow/leave, collaborators, permissions, undo, access through following."""

from __future__ import annotations

from tests.helpers import Clients

BASE = "/api/v1"


async def _users(c) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {
        u["email"].split("@")[0]: u["id"] for u in (await c.get(f"{BASE}/users")).json()["data"]
    }


async def _task(c, project: str = "Website Revamp") -> dict:  # type: ignore[no-untyped-def]
    pid = next(
        p["id"] for p in (await c.get(f"{BASE}/projects")).json()["data"] if p["name"] == project
    )
    return (await c.post(f"{BASE}/projects/{pid}/tasks", json={"title": "Follow me"})).json()[
        "data"
    ]  # type: ignore[no-any-return]


async def test_creator_and_assignee_follow_and_self_follow_leave(as_user: Clients) -> None:
    ravi, ana = await as_user("ravi"), await as_user("ana")
    u = await _users(ravi)
    t = await _task(ravi)
    url = f"{BASE}/tasks/{t['id']}"
    assert (await ravi.get(url)).json()["followers"] == [u["ravi"]]
    await ravi.patch(url, json={"assignee_id": u["priya"]})
    assert (await ravi.get(url)).json()["followers"] == [u["ravi"], u["priya"]]
    # ana (team member, editor) follows herself, then leaves
    r = await ana.post(f"{url}/followers", json={"user_id": u["ana"]})
    assert r.status_code == 200 and u["ana"] in r.json()["data"]["followers"]
    again = await ana.post(f"{url}/followers", json={"user_id": u["ana"]})
    assert again.json()["meta"]["activity_id"] is None  # idempotent
    r = await ana.delete(f"{url}/followers/{u['ana']}")
    assert u["ana"] not in r.json()["data"]["followers"]
    # undo the leave
    await ana.post(f"{BASE}/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert u["ana"] in (await ravi.get(url)).json()["followers"]


async def test_permissions(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    u = await _users(ravi)
    t = await _task(ravi)
    pid = t["project_id"]
    await ravi.post(f"{BASE}/projects/{pid}/members", json={"user_id": u["mei"], "role": "viewer"})
    await ravi.post(
        f"{BASE}/projects/{pid}/members", json={"user_id": u["priya"], "role": "commenter"}
    )
    mei, priya = await as_user("mei"), await as_user("priya")
    url = f"{BASE}/tasks/{t['id']}/followers"
    assert (
        await mei.post(url, json={"user_id": u["mei"]})
    ).status_code == 403  # viewers can't follow
    assert (
        await priya.post(url, json={"user_id": u["priya"]})
    ).status_code == 200  # commenters can
    assert (
        await priya.post(url, json={"user_id": u["ana"]})
    ).status_code == 403  # but not add others
    assert (await priya.delete(f"{url}/{u['ravi']}")).status_code == 403
    r = await ravi.post(url, json={"user_id": "00000000-0000-7000-8000-000000000000"})
    assert r.status_code == 422


async def test_collaborator_on_a_private_task_gets_access_to_that_task_only(
    as_user: Clients,
) -> None:
    priya, tom = await as_user("priya"), await as_user("tom")
    u = await _users(priya)
    t = await _task(priya, "Mobile App v2")
    assert (await tom.get(f"{BASE}/tasks/{t['id']}")).status_code == 404
    await priya.post(f"{BASE}/tasks/{t['id']}/followers", json={"user_id": u["tom"]})
    assert (await tom.get(f"{BASE}/tasks/{t['id']}")).status_code == 200
    assert (await tom.get(f"{BASE}/projects/{t['project_id']}/tasks")).status_code == 404
    # read + comment level only
    assert (await tom.patch(f"{BASE}/tasks/{t['id']}", json={"title": "x"})).status_code == 403
    # leaving removes the access again
    await tom.delete(f"{BASE}/tasks/{t['id']}/followers/{u['tom']}")
    assert (await tom.get(f"{BASE}/tasks/{t['id']}")).status_code == 404
