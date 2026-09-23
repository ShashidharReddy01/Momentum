"""S1.2.5: list filters (assignee, due buckets), sort, and saved view prefs."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from tests.helpers import Clients

BASE = "/api/v1"


async def _fixture(c):  # type: ignore[no-untyped-def]
    pid = next(
        p["id"]
        for p in (await c.get(f"{BASE}/projects")).json()["data"]
        if p["name"] == "Website Revamp"
    )
    sec = (await c.post(f"{BASE}/projects/{pid}/sections", json={"name": "V"})).json()["data"]["id"]
    users = {
        u["email"].split("@")[0]: u["id"] for u in (await c.get(f"{BASE}/users")).json()["data"]
    }
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()  # Ravi's day, as the API sees it
    monday = today - timedelta(days=today.weekday())
    spec = {
        "past": {"assignee_id": users["ana"], "due_on": str(today - timedelta(days=3))},
        "now": {"assignee_id": users["ravi"], "due_on": str(today)},
        "nextwk": {"assignee_id": None, "due_on": str(monday + timedelta(days=9))},
        "nodate": {"assignee_id": users["ravi"]},
        "zeta": {},
    }
    ids = {}
    for title, patch in spec.items():
        t = (
            await c.post(f"{BASE}/projects/{pid}/tasks", json={"title": title, "section_id": sec})
        ).json()["data"]
        ids[title] = t["id"]
        if patch:
            await c.patch(f"{BASE}/tasks/{t['id']}", json=patch)
    return pid, sec, users


async def _titles(c, pid, sec, **params):  # type: ignore[no-untyped-def]
    r = await c.get(f"{BASE}/projects/{pid}/tasks", params=params)
    assert r.status_code == 200, r.text
    return [t["title"] for t in r.json()["data"] if t["section_id"] == sec]


async def test_filters(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid, sec, users = await _fixture(ravi)
    assert await _titles(ravi, pid, sec, assignee="me") == ["now", "nodate"]
    assert await _titles(ravi, pid, sec, assignee="none") == ["nextwk", "zeta"]
    assert await _titles(ravi, pid, sec, assignee=[users["ana"], "none"]) == [
        "past",
        "nextwk",
        "zeta",
    ]
    assert await _titles(ravi, pid, sec, due="overdue") == ["past"]
    assert await _titles(ravi, pid, sec, due="today") == ["now"]
    assert await _titles(ravi, pid, sec, due="next_week") == ["nextwk"]
    assert await _titles(ravi, pid, sec, due="no_date") == ["nodate", "zeta"]
    assert await _titles(ravi, pid, sec, due="no_date", assignee="me") == ["nodate"]
    r = await ravi.get(f"{BASE}/projects/{pid}/tasks", params={"assignee": "bogus"})
    assert r.status_code == 422
    r = await ravi.get(f"{BASE}/projects/{pid}/tasks", params={"due": "someday"})
    assert r.status_code == 422


async def test_sorts(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid, sec, _ = await _fixture(ravi)
    assert await _titles(ravi, pid, sec) == ["past", "now", "nextwk", "nodate", "zeta"]
    assert await _titles(ravi, pid, sec, sort="due") == ["past", "now", "nextwk", "nodate", "zeta"]
    # Ana Souza < Ravi Kumar; unassigned last (manual order among equals)
    assert await _titles(ravi, pid, sec, sort="assignee") == [
        "past",
        "now",
        "nodate",
        "nextwk",
        "zeta",
    ]
    assert await _titles(ravi, pid, sec, sort="title") == [
        "nextwk",
        "nodate",
        "now",
        "past",
        "zeta",
    ]
    assert await _titles(ravi, pid, sec, sort="created") == [
        "past",
        "now",
        "nextwk",
        "nodate",
        "zeta",
    ]


async def test_view_prefs_roundtrip_and_isolation(as_user: Clients) -> None:
    ravi, ana = await as_user("ravi"), await as_user("ana")
    projects = {p["name"]: p["id"] for p in (await ravi.get(f"{BASE}/projects")).json()["data"]}
    pid, other = projects["Website Revamp"], projects["Mobile App v2"]
    url = f"{BASE}/me/prefs/views/{pid}"
    assert (await ravi.get(url)).json() == {
        "assignees": [],
        "due": "any",
        "show_completed": False,
        "sort": "manual",
        "group": "section",
    }
    view = {
        "assignees": ["me", "none"],
        "due": "this_week",
        "show_completed": True,
        "sort": "due",
        "group": "assignee",
    }
    assert (await ravi.put(url, json=view)).status_code == 200
    # a second project's prefs don't clobber the first
    await ravi.put(f"{BASE}/me/prefs/views/{other}", json={**view, "sort": "title"})
    assert (await ravi.get(url)).json() == view
    assert (await ravi.get(f"{BASE}/me/prefs/views/{other}")).json()["sort"] == "title"
    # per user
    assert (await ana.get(url)).json()["sort"] == "manual"
    # validation and visibility
    assert (await ravi.put(url, json={**view, "group": "color"})).status_code == 422
    assert (await ravi.put(url, json={**view, "assignees": ["x' OR 1=1"]})).status_code == 422
    assert (await ravi.put(url, json={**view, "extra": 1})).status_code == 422
    tom = await as_user("tom")
    assert (await tom.put(f"{BASE}/me/prefs/views/{other}", json=view)).status_code == 404
