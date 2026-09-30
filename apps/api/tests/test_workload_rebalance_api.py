"""S6.4.2 ✦ Suggest rebalance through the API: proposes one action (apply → one undo), moves only
what the asker can see and edit, never hands work to someone without edit access, and never names
hidden work. The explanation is the model's only when its numbers are in the facts."""

from __future__ import annotations

from typing import Any

import httpx

from momentum.ai.workload_rebalance import RebalanceNote, _grounded
from tests.helpers import Clients

W1, W2 = "2030-01-07", "2030-01-14"  # Mondays, far from the seed's dates
FRI1 = "2030-01-11"
H = 60
PRODUCT = {"ravi", "ana", "priya", "mei", "admin"}  # can edit Website Revamp (team-visible)


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


async def _suggest(c: httpx.AsyncClient, **body: Any) -> dict[str, Any]:
    r = await c.post("/api/v1/ai/workload/rebalance", json={"start": W1, "weeks": 2, **body})
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


async def _overload_ana(ravi: httpx.AsyncClient, ana: str, web: str) -> dict[str, Any]:
    """Ana: 36h in the week of Jan 7 against the default 30h (6h over)."""
    await _task(
        ravi, web, "Design", assignee_id=ana, start_on=W1, due_on=FRI1, estimate_minutes=24 * H
    )
    return await _task(ravi, web, "Review", assignee_id=ana, due_on=FRI1, estimate_minutes=12 * H)


async def test_suggests_applies_and_undoes_in_one_step(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    ana, web = await _user_id(ravi, "ana"), await _project(ravi)
    review = await _overload_ana(ravi, ana, web)

    body = await _suggest(ravi)
    assert body["status"] == "balanced" and body["action_id"]
    [mv] = body["moves"]
    assert (mv["kind"], mv["key"], mv["from_person"]["user_id"]) == (
        "reassign",
        f"T-{review['number']}",
        ana,
    )
    receiver = mv["to_person"]["user_id"]
    assert mv["due_moved"] is False and "→" in mv["text"]
    row = next(p for p in body["people"] if p["user_id"] == ana)
    assert (row["weeks"][0]["before_minutes"], row["weeks"][0]["after_minutes"]) == (36 * H, 24 * H)
    assert body["headline"] and body["ai"] is True  # the mock's text has no numbers: kept

    # nothing is saved by suggesting
    assert (await ravi.get(f"/api/v1/tasks/{review['id']}")).json()["assignee_id"] == ana

    r = await ravi.post(f"/api/v1/ai/actions/{body['action_id']}/apply", json={})
    assert r.status_code == 200 and r.json()["outcome"] == "applied", r.text
    assert (await ravi.get(f"/api/v1/tasks/{review['id']}")).json()["assignee_id"] == receiver
    again = await _suggest(ravi)
    assert again["status"] == "nothing_to_do" and again["action_id"] is None

    assert (await ravi.post(f"/api/v1/ai/actions/{body['action_id']}/undo")).status_code == 200
    assert (await ravi.get(f"/api/v1/tasks/{review['id']}")).json()["assignee_id"] == ana


async def test_never_gives_work_to_someone_without_edit_access(as_user: Clients) -> None:
    ravi, admin = await as_user("ravi"), await as_user("admin")
    ana, web = await _user_id(ravi, "ana"), await _project(ravi)
    review = await _overload_ana(ravi, ana, web)
    # everyone who can edit Website Revamp is away that week; Marketing has room but no access
    for local in PRODUCT - {"ana"}:
        uid = await _user_id(ravi, local)
        r = await admin.put(f"/api/v1/workload/people/{uid}/weeks/{W1}", json={"hours": 0})
        assert r.status_code == 200, r.text

    body = await _suggest(ravi)
    [mv] = body["moves"]
    # due-only, so it can't start later: the last resort moves its due date, and says so
    assert (mv["kind"], mv["key"], mv["due_moved"]) == ("push", f"T-{review['number']}", True)
    assert (mv["to_due"], mv["weeks_later"]) == ("2030-01-18", 1)
    assert "due date" in mv["why"]
    r = await ravi.post(f"/api/v1/ai/actions/{body['action_id']}/apply", json={})
    assert r.json()["outcome"] == "applied", r.text
    assert (await ravi.get(f"/api/v1/tasks/{review['id']}")).json()["due_on"] == "2030-01-18"


async def test_only_moves_what_the_asker_can_edit(as_user: Clients) -> None:
    ravi, mei = await as_user("ravi"), await as_user("mei")
    ana, web = await _user_id(ravi, "ana"), await _project(ravi)
    await _overload_ana(ravi, ana, web)
    r = await ravi.post(
        f"/api/v1/projects/{web}/members",
        json={"user_id": await _user_id(ravi, "mei"), "role": "viewer"},
    )
    assert r.status_code in (200, 201), r.text

    body = await _suggest(mei)  # mei can see Website Revamp but only view it
    assert body["moves"] == [] and body["action_id"] is None
    assert body["status"] == "partial"
    assert [(u["user_id"], u["reason"]) for u in body["unresolved"]] == [(ana, "nothing_movable")]


async def test_hidden_work_is_never_named_or_moved(as_user: Clients) -> None:
    ravi, mei = await as_user("ravi"), await as_user("mei")
    ana, web = await _user_id(ravi, "ana"), await _project(ravi)
    await _overload_ana(ravi, ana, web)
    private = await _project(ravi, "Mobile App v2")  # mei can't see it
    secret = await _task(
        ravi,
        private,
        "Secret acquisition memo",
        assignee_id=ana,
        due_on=FRI1,
        estimate_minutes=4 * H,
    )

    body = await _suggest(mei)
    text = str(body)
    assert "Secret acquisition memo" not in text and secret["id"] not in text
    assert all(m["task_id"] != secret["id"] for m in body["moves"])
    # ravi sees it, so for him it's just more of Ana's load
    for_ravi = await _suggest(ravi)
    row = next(p for p in for_ravi["people"] if p["user_id"] == ana)
    assert row["weeks"][0]["before_minutes"] == 40 * H


async def test_project_filter_and_errors(as_user: Clients) -> None:
    ravi, tom = await as_user("ravi"), await as_user("tom")
    ana, web = await _user_id(ravi, "ana"), await _project(ravi)
    await _overload_ana(ravi, ana, web)
    mobile = await _project(ravi, "Mobile App v2")
    body = await _suggest(ravi, project_id=mobile)  # Ana's overload is all Website Revamp work
    assert body["moves"] == [] and body["unresolved"][0]["reason"] == "nothing_movable"
    r = await tom.post(
        "/api/v1/ai/workload/rebalance", json={"start": W1, "weeks": 2, "project_id": web}
    )
    assert r.status_code == 404  # a project tom can't see
    r = await ravi.post("/api/v1/ai/workload/rebalance", json={"start": W1, "weeks": 0})
    assert r.status_code == 422


async def test_no_estimates_says_so(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    ana, web = await _user_id(ravi, "ana"), await _project(ravi)
    await _task(ravi, web, "Unsized", assignee_id=ana, due_on=FRI1)
    body = await _suggest(ravi)
    assert body["status"] in ("no_estimates", "nothing_to_do")
    assert body["action_id"] is None


def test_the_models_numbers_must_come_from_the_facts() -> None:
    facts = (
        "Before: Ana had 36h of 30h in the week of Jan 7 (6h over)\n"
        "Move 1: T-12 Review (12h): Ana → Ravi"
    )
    assert _grounded(RebalanceNote(headline="Ana was 6h over", summary=""), facts) is True
    assert _grounded(RebalanceNote(headline="T-12 goes to Ravi", summary="Ana had 36h."), facts)
    assert not _grounded(RebalanceNote(headline="Saves 9 hours", summary=""), facts)
