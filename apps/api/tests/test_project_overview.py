"""S6.2.1 Project overview: project dates and brief are editable (editors, activity, undo,
sanitized), and one call returns progress, overdue count and milestones."""

from __future__ import annotations

from datetime import date, timedelta

import httpx

from tests.helpers import Clients


async def _project(c: httpx.AsyncClient, name: str = "Website Revamp") -> str:
    return next(
        p["id"] for p in (await c.get("/api/v1/projects")).json()["data"] if p["name"] == name
    )


def _doc(text: str) -> dict:  # type: ignore[type-arg]
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


async def test_dates_and_brief_round_trip_with_undo(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    r = await ravi.patch(
        f"/api/v1/projects/{pid}",
        json={"start_on": "2026-10-01", "due_on": "2026-12-15", "brief": _doc("Relaunch the site")},
    )
    assert r.status_code == 200, r.text
    d = (await ravi.get(f"/api/v1/projects/{pid}")).json()
    assert (d["start_on"], d["due_on"]) == ("2026-10-01", "2026-12-15")
    assert d["brief"]["content"][0]["content"][0]["text"] == "Relaunch the site"
    listed = next(p for p in (await ravi.get("/api/v1/projects")).json()["data"] if p["id"] == pid)
    assert listed["due_on"] == "2026-12-15"

    u = await ravi.post("/api/v1/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert u.status_code == 200, u.text
    d = (await ravi.get(f"/api/v1/projects/{pid}")).json()
    assert (d["start_on"], d["due_on"], d["brief"]) == (None, None, None)


async def test_brief_is_sanitized_and_searchable_and_dates_checked(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    evil = {
        "type": "doc",
        "content": [{"type": "script", "text": "alert(1)"}, *_doc("Quarterly goals")["content"]],
    }
    r = await ravi.patch(f"/api/v1/projects/{pid}", json={"brief": evil})
    assert r.status_code in (200, 422), r.text
    if r.status_code == 200:
        assert "script" not in str((await ravi.get(f"/api/v1/projects/{pid}")).json()["brief"])

    r = await ravi.patch(
        f"/api/v1/projects/{pid}", json={"start_on": "2026-12-20", "due_on": "2026-12-01"}
    )
    assert r.status_code == 422 and r.json()["code"] == "dates_out_of_order"


async def test_viewers_cannot_edit_dates_or_brief(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    kim = await as_user("kim")  # not on the team
    pid = await _project(ravi)
    r = await kim.patch(f"/api/v1/projects/{pid}", json={"due_on": "2026-12-01"})
    assert r.status_code in (403, 404)


async def test_overview_counts_and_milestones(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    before = (await ravi.get(f"/api/v1/projects/{pid}/overview")).json()
    yesterday = (date.today() - timedelta(days=2)).isoformat()

    late = (await ravi.post(f"/api/v1/projects/{pid}/tasks", json={"title": "Late"})).json()["data"]
    await ravi.patch(f"/api/v1/tasks/{late['id']}", json={"due_on": yesterday})
    done = (await ravi.post(f"/api/v1/projects/{pid}/tasks", json={"title": "Done"})).json()["data"]
    await ravi.post(f"/api/v1/tasks/{done['id']}/complete")
    ms = (await ravi.post(f"/api/v1/projects/{pid}/tasks", json={"title": "Beta ships"})).json()[
        "data"
    ]
    await ravi.post(f"/api/v1/tasks/{ms['id']}/convert", json={"type": "milestone"})
    await ravi.patch(f"/api/v1/tasks/{ms['id']}", json={"due_on": "2026-11-20"})

    o = (await ravi.get(f"/api/v1/projects/{pid}/overview")).json()
    assert o["total_tasks"] == before["total_tasks"] + 3
    assert o["completed_tasks"] == before["completed_tasks"] + 1
    assert o["overdue_tasks"] == before["overdue_tasks"] + 1
    assert any(m["title"] == "Beta ships" and m["due_on"] == "2026-11-20" for m in o["milestones"])

    kim = await as_user("kim")
    assert (
        await kim.get(f"/api/v1/projects/{await _project(ravi, 'Mobile App v2')}/overview")
    ).status_code == 404
