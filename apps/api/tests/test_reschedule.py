"""S6.1.2 Dependency-aware rescheduling: moving a task pushes the work that waits on it (preview
first, apply as one undo batch), push-only, and never touches tasks the caller can't edit."""

from __future__ import annotations

from tests.helpers import Clients


async def _project(c, name: str = "Website Revamp") -> str:  # type: ignore[no-untyped-def]
    return next(
        p["id"] for p in (await c.get("/api/v1/projects")).json()["data"] if p["name"] == name
    )


async def _task(c, pid: str, title: str, start: str | None, due: str | None) -> str:  # type: ignore[no-untyped-def]
    r = await c.post(f"/api/v1/projects/{pid}/tasks", json={"title": title})
    assert r.status_code == 201, r.text
    tid = r.json()["data"]["id"]
    if start or due:
        r = await c.patch(f"/api/v1/tasks/{tid}", json={"start_on": start, "due_on": due})
        assert r.status_code == 200, r.text
    return tid


async def _block(c, task: str, on: str) -> None:  # type: ignore[no-untyped-def]
    r = await c.post(f"/api/v1/tasks/{task}/dependencies", json={"depends_on_id": on})
    assert r.status_code == 201, r.text


async def _dates(c, tid: str) -> tuple[str | None, str | None]:  # type: ignore[no-untyped-def]
    t = (await c.get(f"/api/v1/tasks/{tid}")).json()
    return t["start_on"], t["due_on"]


async def _chain(c):  # type: ignore[no-untyped-def]
    """A (Oct 1-5) → B (Oct 6-10) → C (Oct 11-12): each waits on the one before."""
    pid = await _project(c)
    a = await _task(c, pid, "A", "2026-10-01", "2026-10-05")
    b = await _task(c, pid, "B", "2026-10-06", "2026-10-10")
    cc = await _task(c, pid, "C", "2026-10-11", "2026-10-12")
    await _block(c, b, a)
    await _block(c, cc, b)
    return pid, a, b, cc


async def test_preview_pushes_the_chain_without_writing(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    _, a, b, c = await _chain(ravi)
    r = await ravi.post(f"/api/v1/tasks/{a}/reschedule/preview", json={"due_on": "2026-10-08"})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["moved"]["to_due"] == "2026-10-08"
    shifted = {s["id"]: s for s in plan["shifted"]}
    # B must start once A is due (Oct 8): +2 days; C then starts on B's new due (Oct 12): +1
    assert shifted[b]["to_start"] == "2026-10-08" and shifted[b]["to_due"] == "2026-10-12"
    assert shifted[b]["shift_days"] == 2
    assert shifted[c]["to_start"] == "2026-10-12" and shifted[c]["to_due"] == "2026-10-13"
    assert plan["skipped"] == []
    assert await _dates(ravi, b) == ("2026-10-06", "2026-10-10")  # nothing written


async def test_apply_moves_everything_as_one_undo(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    _, a, b, c = await _chain(ravi)
    r = await ravi.post(
        f"/api/v1/tasks/{a}/reschedule", json={"start_on": "2026-10-03", "due_on": "2026-10-08"}
    )
    assert r.status_code == 200, r.text
    assert await _dates(ravi, a) == ("2026-10-03", "2026-10-08")
    assert await _dates(ravi, b) == ("2026-10-08", "2026-10-12")
    assert await _dates(ravi, c) == ("2026-10-12", "2026-10-13")

    u = await ravi.post("/api/v1/undo", json={"batch_id": r.json()["meta"]["batch_id"]})
    assert u.status_code == 200, u.text
    assert await _dates(ravi, a) == ("2026-10-01", "2026-10-05")
    assert await _dates(ravi, b) == ("2026-10-06", "2026-10-10")
    assert await _dates(ravi, c) == ("2026-10-11", "2026-10-12")


async def test_only_this_task_and_moving_earlier_leave_dependents_alone(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    _, a, b, _c = await _chain(ravi)
    r = await ravi.post(
        f"/api/v1/tasks/{a}/reschedule", json={"due_on": "2026-10-09", "cascade": False}
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["shifted"] == []
    assert await _dates(ravi, b) == ("2026-10-06", "2026-10-10")  # now a conflict, by choice

    # moving a blocker earlier never pulls its dependents with it
    r = await ravi.post(f"/api/v1/tasks/{a}/reschedule/preview", json={"due_on": "2026-10-02"})
    assert r.json()["shifted"] == []


async def test_same_day_completed_and_unscheduled_dependents_stay(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    a = await _task(ravi, pid, "A", "2026-10-01", "2026-10-05")
    same_day = await _task(ravi, pid, "Same day", "2026-10-07", "2026-10-09")
    done = await _task(ravi, pid, "Done", "2026-10-06", "2026-10-06")
    undated = await _task(ravi, pid, "Undated", None, None)
    for t in (same_day, done, undated):
        await _block(ravi, t, a)
    assert (await ravi.post(f"/api/v1/tasks/{done}/complete?force=true")).status_code == 200

    r = await ravi.post(f"/api/v1/tasks/{a}/reschedule/preview", json={"due_on": "2026-10-07"})
    assert r.json()["shifted"] == []


async def test_a_dependent_the_caller_cannot_edit_is_skipped(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    mei = await as_user("mei")  # edits Website Revamp, not a member of private Mobile App v2
    web = await _project(ravi)
    private = await _project(ravi, "Mobile App v2")
    a = await _task(ravi, web, "A", "2026-10-01", "2026-10-05")
    hidden = await _task(ravi, private, "Hidden", "2026-10-06", "2026-10-08")
    await _block(ravi, hidden, a)

    r = await mei.post(f"/api/v1/tasks/{a}/reschedule", json={"due_on": "2026-10-10"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["shifted"] == []
    assert await _dates(ravi, hidden) == ("2026-10-06", "2026-10-08")
    # a task Mei can't see is only counted: no id, key or title leaks out
    assert r.json()["data"]["skipped"] == []
    assert r.json()["data"]["hidden_skipped"] == 1
    assert hidden not in r.text and "Hidden" not in r.text


async def test_a_dependent_the_caller_can_only_view_is_listed(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    other = await _project(ravi, "Mobile App v2")
    a = await _task(ravi, pid, "A", "2026-10-01", "2026-10-05")
    b = await _task(ravi, other, "B", "2026-10-06", "2026-10-08")
    await _block(ravi, b, a)
    mei = await as_user("mei")  # edits Website Revamp; added to private Mobile App v2 as a viewer
    users = (await ravi.get("/api/v1/users")).json()["data"]
    mei_id = next(u["id"] for u in users if u["email"].startswith("mei@"))
    priya = await as_user("priya")  # Mobile App v2's admin
    r = await priya.post(
        f"/api/v1/projects/{other}/members", json={"user_id": mei_id, "role": "viewer"}
    )
    assert r.status_code in (200, 201), r.text

    r = await mei.post(f"/api/v1/tasks/{a}/reschedule/preview", json={"due_on": "2026-10-09"})
    assert r.status_code == 200, r.text
    assert [s["id"] for s in r.json()["skipped"]] == [b]
    assert r.json()["shifted"] == []


async def test_viewers_cannot_reschedule_and_dates_must_be_in_order(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    _, a, _b, _c = await _chain(ravi)
    r = await ravi.post(
        f"/api/v1/tasks/{a}/reschedule", json={"start_on": "2026-10-09", "due_on": "2026-10-02"}
    )
    assert r.status_code == 422
    assert r.json()["code"] == "dates_out_of_order"
    kim = await as_user("kim")  # not on the Product team
    r = await kim.post(f"/api/v1/tasks/{a}/reschedule/preview", json={"due_on": "2026-10-09"})
    assert r.status_code in (403, 404)
