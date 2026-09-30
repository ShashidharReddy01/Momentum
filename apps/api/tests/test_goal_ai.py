"""S6.3.2 AI for goals: the check-in draft (grounded, or built in code), and suggested projects
(hybrid retrieval, visible only, already-linked left out). Mock mode."""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from momentum.ai.goal_assist import CheckInDraft, _grounded, pace, plain_draft
from momentum.domain.goals.models import Goal
from tests.helpers import Clients

Q4 = {"period_start": "2026-10-01", "period_end": "2026-12-31", "period_label": "Q4 2026"}


async def _project(c: httpx.AsyncClient, name: str = "Website Revamp") -> str:
    return next(
        p["id"] for p in (await c.get("/api/v1/projects")).json()["data"] if p["name"] == name
    )


async def _goal(c: httpx.AsyncClient, name: str, **body: Any) -> dict[str, Any]:
    r = await c.post("/api/v1/goals", json={"name": name, **Q4, **body})
    assert r.status_code == 201, r.text
    return r.json()["data"]  # type: ignore[no-any-return]


async def test_check_in_draft_is_for_editors_and_marked(as_user: Clients) -> None:
    ravi, mei = await as_user("ravi"), await as_user("mei")
    g = await _goal(ravi, "Relaunch the website", progress_source="projects")
    await ravi.post(
        f"/api/v1/goals/{g['id']}/links",
        json={"entity_type": "project", "entity_id": await _project(ravi)},
    )
    r = await ravi.post(f"/api/v1/ai/goals/{g['id']}/check-in-draft")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ai"] is True  # the mock draft has no numbers, so it's grounded
    assert body["draft"]["status"] == "at_risk" and body["draft"]["title"]
    assert (await mei.post(f"/api/v1/ai/goals/{g['id']}/check-in-draft")).status_code == 403


def test_an_invented_number_falls_back_to_the_code_draft() -> None:
    facts = "Progress: 40%; 50% of the period has passed\nMetric: 140 now, from 100 towards 200"
    assert _grounded(CheckInDraft(status="at_risk", title="40% done, behind pace"), facts)
    assert not _grounded(CheckInDraft(status="on_track", title="Hit 180 customers"), facts)

    g = Goal(
        name="Grow",
        period_start=date(2026, 10, 1),
        period_end=date(2026, 12, 31),
        progress_source="manual",
    )
    today = date(2026, 11, 15)  # about half the quarter gone
    assert round(pace(g, today), 2) == 0.49
    assert plain_draft(g, 0.45, today).status == "on_track"  # within 10 points of pace
    assert plain_draft(g, 0.30, today).status == "at_risk"
    assert plain_draft(g, 0.10, today).status == "off_track"
    assert plain_draft(g, None, today).title == "No progress data yet"


async def test_suggested_projects_match_skip_linked_and_hidden(as_user: Clients) -> None:
    ravi, mei = await as_user("ravi"), await as_user("mei")
    web = await _project(ravi)
    # something to match on, by words: a task in Website Revamp
    await ravi.post(f"/api/v1/projects/{web}/tasks", json={"title": "Homepage relaunch checklist"})
    g = await _goal(ravi, "Homepage relaunch", description="A faster homepage relaunch")

    found = (await ravi.post(f"/api/v1/ai/goals/{g['id']}/suggest-links")).json()["suggestions"]
    assert [s["name"] for s in found][:1] == ["Website Revamp"]
    assert "Homepage relaunch checklist" in found[0]["reason"]

    await ravi.post(
        f"/api/v1/goals/{g['id']}/links", json={"entity_type": "project", "entity_id": web}
    )
    again = (await ravi.post(f"/api/v1/ai/goals/{g['id']}/suggest-links")).json()["suggestions"]
    assert web not in {s["id"] for s in again}

    # a project the asker can't see is never suggested
    private = await _project(ravi, "Mobile App v2")
    await ravi.post(
        f"/api/v1/projects/{private}/tasks", json={"title": "Homepage relaunch for mobile"}
    )
    hers = (await mei.post(f"/api/v1/ai/goals/{g['id']}/suggest-links")).json()["suggestions"]
    assert private not in {s["id"] for s in hers}
