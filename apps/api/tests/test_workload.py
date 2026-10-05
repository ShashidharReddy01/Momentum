"""S6.4.1 Workload: effort spread over working days into weeks, capacity from the week override →
the person → the workspace → the setting, only work you can see (the rest counted), and capacity
changes by the person or an admin, with undo. Plus estimates on tasks."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx

from momentum.domain.workload.service import spread
from tests.helpers import Clients

W1, W2 = "2030-01-07", "2030-01-14"  # two Mondays, far from the seed's dates


async def _project(c: httpx.AsyncClient, name: str = "Website Revamp") -> str:
    return next(
        p["id"] for p in (await c.get("/api/v1/projects")).json()["data"] if p["name"] == name
    )


async def _user_id(c: httpx.AsyncClient, local: str) -> str:
    people = (await c.get("/api/v1/users", params={"q": local})).json()["data"]
    return next(u["id"] for u in people if u["email"].startswith(f"{local}@"))


async def _task(c: httpx.AsyncClient, pid: str, title: str, **patch: Any) -> dict[str, Any]:
    t = (await c.post(f"/api/v1/projects/{pid}/tasks", json={"title": title})).json()["data"]
    r = await c.patch(f"/api/v1/tasks/{t['id']}", json=patch)
    assert r.status_code == 200, r.text
    return r.json()["data"]  # type: ignore[no-any-return]


async def _load(c: httpx.AsyncClient, **params: Any) -> dict[str, Any]:
    r = await c.get("/api/v1/workload", params={"start": W1, "weeks": 2, **params})
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def _row(body: dict[str, Any], uid: str) -> dict[str, Any]:
    return next(p for p in body["people"] if p["user_id"] == uid)


def test_effort_spreads_over_working_days() -> None:
    today = date(2030, 1, 1)
    # Fri → Tue: three working days, the weekend skipped
    days = spread(date(2030, 1, 11), date(2030, 1, 15), 180, today)
    assert days == {date(2030, 1, 11): 60, date(2030, 1, 14): 60, date(2030, 1, 15): 60}
    assert spread(None, date(2030, 1, 15), 90, today) == {date(2030, 1, 15): 90}
    # overdue lands on today; underway spreads over what's left
    assert spread(date(2029, 12, 1), date(2029, 12, 5), 60, today) == {today: 60}
    assert sum(spread(date(2029, 12, 31), date(2030, 1, 2), 120, today).values()) == 120
    assert date(2029, 12, 31) not in spread(date(2029, 12, 31), date(2030, 1, 2), 120, today)


async def test_weeks_add_up_and_hidden_work_is_counted(as_user: Clients) -> None:
    ravi, mei = await as_user("ravi"), await as_user("mei")
    ana = await _user_id(ravi, "ana")
    web = await _project(ravi)
    await _task(
        ravi,
        web,
        "Design",
        assignee_id=ana,
        start_on="2030-01-07",
        due_on="2030-01-11",
        estimate_minutes=600,
    )
    await _task(
        ravi,
        web,
        "Review",
        assignee_id=ana,
        start_on="2030-01-11",
        due_on="2030-01-15",
        estimate_minutes=180,
    )
    await _task(ravi, web, "Copy", assignee_id=ana, due_on="2030-01-16")  # no estimate
    await _task(ravi, web, "Someday", assignee_id=ana)  # no date
    await _task(ravi, web, "Nobody's", due_on="2030-01-08", estimate_minutes=60)
    private = await _project(ravi, "Mobile App v2")  # mei can't see it
    await _task(ravi, private, "Secret", assignee_id=ana, due_on="2030-01-09", estimate_minutes=120)

    body = await _load(ravi)
    assert body["weeks"] == [W1, W2]
    row = _row(body, ana)
    w1, w2 = row["weeks"]
    assert (w1["planned_minutes"], w1["task_count"]) == (600 + 60 + 120, 3)
    assert (w2["planned_minutes"], w2["task_count"], w2["unestimated"]) == (120, 2, 1)
    assert w1["capacity_minutes"] == 30 * 60 and row["hours_source"] == "setting"
    assert row["no_date"] >= 1 and row["hidden"] == 0
    assert body["unassigned"]["weeks"][0]["planned_minutes"] == 60
    review = next(t for t in body["tasks"] if t["title"] == "Review")
    assert review["weeks"] == {W1: 60, W2: 120}

    hers = await _load(mei)
    assert "Secret" not in str(hers)
    assert _row(hers, ana)["weeks"][0]["planned_minutes"] == 600 + 60
    assert _row(hers, ana)["hidden"] >= 1  # counted, never named

    only_web = await _load(ravi, project_id=web)
    assert _row(only_web, ana)["weeks"][0]["planned_minutes"] == 600 + 60
    assert (await mei.get("/api/v1/workload", params={"project_id": private})).status_code == 404

    # the grid alone, then one row's tasks: same numbers, a much smaller payload
    grid = await _load(ravi, tasks_for="none")
    assert grid["tasks"] == [] and grid["people"] == body["people"] and grid["any_estimate"]
    anas = await _load(ravi, tasks_for=ana)
    assert anas["tasks"] and {t["assignee_id"] for t in anas["tasks"]} == {ana}
    nobody = await _load(ravi, tasks_for="unassigned")
    assert [t["title"] for t in nobody["tasks"] if t["title"] == "Nobody's"] == ["Nobody's"]
    assert all(t["assignee_id"] is None for t in nobody["tasks"])
    bad = await ravi.get("/api/v1/workload", params={"tasks_for": "everyone"})
    assert bad.status_code == 422


async def test_capacity_changes_by_the_person_or_an_admin(as_user: Clients) -> None:
    ana_c, mei, admin = await as_user("ana"), await as_user("mei"), await as_user("admin")
    ana = await _user_id(ana_c, "ana")

    # a week off, by Ana herself; Mei can't
    r = await ana_c.put(f"/api/v1/workload/people/{ana}/weeks/{W2}", json={"hours": 0})
    assert r.status_code == 200, r.text
    assert (
        await mei.put(f"/api/v1/workload/people/{ana}/weeks/{W2}", json={"hours": 10})
    ).status_code == 403
    assert (
        await ana_c.put(f"/api/v1/workload/people/{ana}/weeks/2030-01-08", json={"hours": 5})
    ).status_code == 422  # not a Monday
    w2 = _row(await _load(mei), ana)["weeks"][1]
    assert w2["capacity_minutes"] == 0 and w2["override"]

    # the workspace default (admins), then her own usual hours on top
    assert (await mei.put("/api/v1/workload/settings", json={"hours": 40})).status_code == 403
    r = await admin.put("/api/v1/workload/settings", json={"hours": 40})
    assert r.status_code == 200
    body = await _load(mei)
    assert body["default_minutes"] == 2400 and body["default_source"] == "workspace"
    assert _row(body, ana)["weekly_minutes"] == 2400
    own = await ana_c.put(f"/api/v1/workload/people/{ana}/hours", json={"hours": 20})
    row = _row(await _load(mei), ana)
    assert row["weekly_minutes"] == 1200 and row["hours_source"] == "person"
    assert row["weeks"][0]["capacity_minutes"] == 1200 and row["weeks"][1]["capacity_minutes"] == 0
    assert row["can_edit"] is False and _row(await _load(ana_c), ana)["can_edit"] is True

    # everything undoes
    for c, res in ((ana_c, own), (admin, r)):
        u = await c.post("/api/v1/undo", json={"activity_id": res.json()["meta"]["activity_id"]})
        assert u.status_code == 200, u.text
    row = _row(await _load(mei), ana)
    assert row["weekly_minutes"] == 1800 and row["hours_source"] == "setting"
    assert (
        await ana_c.put(f"/api/v1/workload/people/{ana}/weeks/{W2}", json={"hours": None})
    ).status_code == 200
    assert not _row(await _load(mei), ana)["weeks"][1]["override"]


async def test_estimates_are_validated_and_undoable(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    web = await _project(ravi)
    t = await _task(ravi, web, "Sized", estimate_minutes=90)
    assert t["estimate_minutes"] == 90
    r = await ravi.patch(f"/api/v1/tasks/{t['id']}", json={"estimate_minutes": 150})
    await ravi.post("/api/v1/undo", json={"activity_id": r.json()["meta"]["activity_id"]})
    assert (await ravi.get(f"/api/v1/tasks/{t['id']}")).json()["estimate_minutes"] == 90
    bad = await ravi.patch(f"/api/v1/tasks/{t['id']}", json={"estimate_minutes": -5})
    assert bad.status_code == 422


def test_spread_weeks_matches_the_per_day_spread() -> None:
    """Phase 7: the workload grid sums effort per week a week at a time; it must give exactly
    the per-day spread's numbers (random ranges, overdue and underway tasks, weekends)."""
    import random
    from collections import defaultdict

    from momentum.domain.workload.service import monday, spread, spread_weeks

    rng = random.Random(7)
    today = date(2026, 10, 7)  # a Wednesday
    for _ in range(2000):
        due = today + timedelta(days=rng.randint(-20, 120))
        start = due - timedelta(days=rng.randint(0, 90)) if rng.random() < 0.8 else None
        minutes = rng.choice([None, 30, 60, 480, 2400])
        per_day: dict[date, float] = defaultdict(float)
        for d, m in spread(start, due, minutes, today).items():
            per_day[monday(d)] += m
        got = spread_weeks(start, due, minutes, today)
        assert set(got) == set(per_day), (start, due)
        for w in got:
            assert abs(got[w] - per_day[w]) < 1e-6, (start, due, w)


async def test_the_grid_sums_match_the_tasks_spread_one_by_one(as_user: Clients) -> None:
    """Phase 7: one-week tasks are summed in SQL, multi-week ones spread in Python. Whatever the
    mix (overdue, underway, weekend-only, multi-week, unestimated, in two projects), the grid
    must equal the listed tasks added up per person and week."""
    ravi = await as_user("ravi")
    ana = await _user_id(ravi, "ana")
    web, other = await _project(ravi), await _project(ravi, "Mobile App v2")
    today = date.today()
    sat = today + timedelta(days=(5 - today.weekday()) % 7 or 7)

    def d(days: int) -> str:
        return (today + timedelta(days=days)).isoformat()

    await _task(ravi, web, "Overdue", assignee_id=ana, due_on=d(-10), estimate_minutes=90)
    await _task(
        ravi, web, "Underway", assignee_id=ana, start_on=d(-3), due_on=d(9), estimate_minutes=600
    )
    await _task(
        ravi, web, "Long", assignee_id=ana, start_on=d(2), due_on=d(20), estimate_minutes=900
    )
    await _task(ravi, web, "Unestimated long", start_on=d(1), due_on=d(15))
    await _task(
        ravi,
        web,
        "Weekend",
        assignee_id=ana,
        start_on=sat.isoformat(),
        due_on=(sat + timedelta(days=1)).isoformat(),
        estimate_minutes=120,
    )
    both = await _task(ravi, web, "Two projects", assignee_id=ana, due_on=d(4), estimate_minutes=60)
    r = await ravi.post(f"/api/v1/tasks/{both['id']}/projects", json={"project_id": other})
    assert r.status_code == 201, r.text

    params = {"start": today.isoformat(), "weeks": 5}
    grid = (await ravi.get("/api/v1/workload", params={**params, "tasks_for": "none"})).json()
    every = (await ravi.get("/api/v1/workload", params={**params, "tasks_for": "all"})).json()
    assert grid["people"] == every["people"] and grid["unassigned"] == every["unassigned"]
    ids = [t["id"] for t in every["tasks"]]
    assert len(ids) == len(set(ids)) and both["id"] in ids  # multi-homed: listed once
    for row in [*every["people"], every["unassigned"]]:
        mine = [t for t in every["tasks"] if t["assignee_id"] == row["user_id"]]
        for w in row["weeks"]:
            here = [t for t in mine if w["week_start"] in t["weeks"]]
            assert w["task_count"] == len(here), (row["name"], w)
            assert abs(
                w["planned_minutes"] - sum(t["weeks"][w["week_start"]] for t in here)
            ) <= len(here)
            assert w["unestimated"] == sum(1 for t in here if t["estimate_minutes"] is None)
    anas = (await ravi.get("/api/v1/workload", params={**params, "tasks_for": ana})).json()
    assert sorted(t["id"] for t in anas["tasks"]) == sorted(
        t["id"] for t in every["tasks"] if t["assignee_id"] == ana
    )
    assert {"Overdue", "Underway", "Long", "Weekend", "Two projects"} <= {
        t["title"] for t in anas["tasks"]
    }
