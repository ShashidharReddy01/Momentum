"""E7.4 parity: duplicate a task, export a project to CSV and like a task, as people coming from
Asana expect."""

from __future__ import annotations

import csv
import io
from typing import Any

from tests.helpers import Clients

B = "/api/v1"


async def _project(c: Any, name: str = "Website Revamp") -> str:
    return next(p["id"] for p in (await c.get(f"{B}/projects")).json()["data"] if p["name"] == name)


async def test_duplicate_copies_the_work_below_the_original_and_undoes_in_one(
    as_user: Clients,
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    users = {
        u["email"].split("@")[0]: u["id"] for u in (await ravi.get(f"{B}/users")).json()["data"]
    }
    t = (
        await ravi.post(
            f"{B}/projects/{pid}/tasks",
            json={"title": "Launch email", "due_on": "2026-11-02", "assignee_id": users["ana"]},
        )
    ).json()["data"]
    url = f"{B}/tasks/{t['id']}"
    doc = {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Brief"}]}],
    }
    await ravi.patch(url, json={"description": doc, "priority": "high", "start_on": "2026-10-28"})
    effort = (
        await ravi.post(f"{B}/projects/{pid}/fields", json={"name": "Effort", "type": "number"})
    ).json()["data"]["id"]
    await ravi.put(f"{url}/fields/{effort}", json={"value": 3})
    await ravi.post(f"{url}/tags", json={"name": "Email"})
    sub = (await ravi.post(f"{url}/subtasks", json={"title": "Write copy"})).json()["data"]
    await ravi.post(f"{B}/tasks/{sub['id']}/subtasks", json={"title": "Proofread"})
    await ravi.post(f"{url}/comments", json={"body": doc})

    r = await ravi.post(f"{url}/duplicate")
    assert r.status_code == 201, r.text
    copy = r.json()["data"]
    assert copy["title"] == "Copy of Launch email"
    got = (await ravi.get(f"{B}/tasks/{copy['id']}")).json()
    assert (got["due_on"], got["start_on"], got["priority"]) == ("2026-11-02", "2026-10-28", "high")
    assert got["assignee_id"] == users["ana"]
    assert got["description"] == doc
    assert got["completed_at"] is None
    values = (await ravi.get(f"{B}/tasks/{copy['id']}/fields")).json()["data"]
    assert any(v["field_id"] == effort and v["value"] == 3 for v in values)
    assert [x["name"] for x in (await ravi.get(f"{B}/tasks/{copy['id']}/tags")).json()["data"]] == [
        "Email"
    ]
    subs = (await ravi.get(f"{B}/tasks/{copy['id']}/subtasks")).json()["data"]
    assert [s["title"] for s in subs] == ["Write copy"]
    grand = (await ravi.get(f"{B}/tasks/{subs[0]['id']}/subtasks")).json()["data"]
    assert [s["title"] for s in grand] == ["Proofread"]
    assert (await ravi.get(f"{B}/tasks/{copy['id']}/comments")).json()["data"] == []
    # right below the original
    ids = [x["id"] for x in (await ravi.get(f"{B}/projects/{pid}/tasks")).json()["data"]]
    assert ids.index(copy["id"]) == ids.index(t["id"]) + 1
    # one undo removes the copy
    u = await ravi.post(f"{B}/undo", json={"batch_id": r.json()["meta"]["batch_id"]})
    assert u.status_code == 200, u.text
    assert (await ravi.get(f"{B}/tasks/{copy['id']}")).status_code == 404
    # a subtask duplicates under its own parent; a viewer can't duplicate
    r2 = await ravi.post(f"{B}/tasks/{sub['id']}/duplicate")
    assert r2.status_code == 201
    assert [s["title"] for s in (await ravi.get(f"{url}/subtasks")).json()["data"]] == [
        "Write copy",
        "Copy of Write copy",
    ]


async def test_export_a_project_to_csv(as_user: Clients) -> None:
    ravi, tom = await as_user("ravi"), await as_user("tom")
    pid = await _project(ravi)
    t = (
        await ravi.post(
            f"{B}/projects/{pid}/tasks", json={"title": '=HYPERLINK("x")', "due_on": "2026-11-02"}
        )
    ).json()["data"]
    await ravi.post(f"{B}/tasks/{t['id']}/subtasks", json={"title": "Child step"})
    await ravi.post(f"{B}/tasks/{t['id']}/tags", json={"name": "Café ☕"})
    r = await ravi.get(f"{B}/projects/{pid}/export/csv")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert "Website Revamp.csv" in r.headers["content-disposition"]
    text = r.content.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    mine = next(x for x in rows if x["Name"].endswith('HYPERLINK("x")'))
    assert mine["Name"].startswith("'=")  # never a live formula in a spreadsheet
    assert (mine["Due Date"], mine["Tags"]) == ("2026-11-02", "Café ☕")
    child = rows[rows.index(mine) + 1]
    assert (child["Name"], child["Parent task"]) == ("Child step", mine["Name"])
    assert {"Task ID", "Section/Column", "Assignee", "Assignee Email", "Notes"} <= set(rows[0])
    # only people who can see the project can export it
    priv = (await ravi.get(f"{B}/projects")).json()["data"]
    hidden = [
        p["id"]
        for p in priv
        if p["id"] not in {x["id"] for x in (await tom.get(f"{B}/projects")).json()["data"]}
    ]
    if hidden:
        assert (await tom.get(f"{B}/projects/{hidden[0]}/export/csv")).status_code == 404


async def test_like_a_task(as_user: Clients) -> None:
    ravi, ana = await as_user("ravi"), await as_user("ana")
    pid = await _project(ravi)
    users = {
        u["email"].split("@")[0]: u["id"] for u in (await ravi.get(f"{B}/users")).json()["data"]
    }
    t = (await ravi.post(f"{B}/projects/{pid}/tasks", json={"title": "Nice work"})).json()["data"]
    url = f"{B}/tasks/{t['id']}"
    r = await ravi.post(f"{url}/likes", json={})
    assert r.status_code == 200, r.text
    await ana.post(f"{url}/likes", json={})
    await ana.post(f"{url}/likes", json={})  # twice is still one like
    assert (await ravi.get(url)).json()["likes"] == [users["ravi"], users["ana"]]
    # a like isn't a line in the task's feed
    feed = (await ravi.get(f"{url}/feed")).json()
    assert "liked" not in str(feed)
    # undo takes it back
    u = await ravi.post(f"{B}/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert u.status_code == 200, u.text
    assert (await ravi.get(url)).json()["likes"] == [users["ana"]]
    off = await ana.post(f"{url}/likes", json={"active": False})
    assert off.json()["data"]["likes"] == []
