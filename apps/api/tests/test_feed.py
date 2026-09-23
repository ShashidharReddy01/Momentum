"""S1.4.2 Activity feed: merged with comments, ordered, undone/reorders hidden, subtasks."""

from __future__ import annotations

from tests.helpers import Clients

BASE = "/api/v1"


def body(t: str) -> dict:  # type: ignore[type-arg]
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": t}]}],
    }


async def test_feed(as_user: Clients) -> None:
    ravi, tom = await as_user("ravi"), await as_user("tom")
    users = {
        u["email"].split("@")[0]: u["id"] for u in (await ravi.get(f"{BASE}/users")).json()["data"]
    }
    pid = next(
        p["id"]
        for p in (await ravi.get(f"{BASE}/projects")).json()["data"]
        if p["name"] == "Website Revamp"
    )
    secs = {
        s["name"]: s["id"]
        for s in (await ravi.get(f"{BASE}/projects/{pid}/sections")).json()["data"]
    }
    t = (await ravi.post(f"{BASE}/projects/{pid}/tasks", json={"title": "Feed me"})).json()["data"]
    other = (await ravi.post(f"{BASE}/projects/{pid}/tasks", json={"title": "Neighbor"})).json()[
        "data"
    ]
    url = f"{BASE}/tasks/{t['id']}"
    await ravi.patch(url, json={"title": "Feed me well"})
    await ravi.patch(url, json={"assignee_id": users["ana"]})
    await ravi.post(f"{url}/comments", json={"body": body("On it?")})
    undone = await ravi.patch(url, json={"due_on": "2026-10-10"})
    await ravi.post(f"{BASE}/undo", json={"activity_id": undone.json()["meta"]["activity_id"]})
    await ravi.post(
        f"{url}/move", json={"section_id": secs["Backlog"], "after_id": other["id"]}
    )  # reorder only
    await ravi.post(f"{url}/move", json={"section_id": secs["Review"]})  # section change
    await ravi.post(f"{url}/subtasks", json={"title": "Child step"})
    await ravi.post(f"{url}/complete")

    feed = (await ravi.get(f"{url}/feed")).json()
    assert feed["truncated"] is False
    kinds = [
        (
            i["kind"],
            i["activity"]["verb"] if i["activity"] else None,
            list(i["activity"]["changes"]) if i["activity"] else None,
        )
        for i in feed["data"]
    ]
    assert kinds == [
        ("activity", "task.created", ["title"]),
        ("activity", "task.updated", ["title"]),
        ("activity", "task.updated", ["assignee_id"]),
        ("comment", None, None),
        ("activity", "task.moved", ["position", "section_id"]),
        ("activity", "task.created", ["title", "parent_id"]),
        ("activity", "task.completed", ["completed_at"]),
    ]
    times = [i["at"] for i in feed["data"]]
    assert times == sorted(times)
    sub = feed["data"][5]["activity"]
    assert sub["subject"]["title"] == "Child step"
    assert feed["data"][2]["activity"]["changes"]["assignee_id"] == [None, users["ana"]]
    assert (await tom.get(f"{url}/feed")).status_code == 404
