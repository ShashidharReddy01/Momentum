"""S4.3.3 Template from description: a sentence → a draft project template (sections, tasks,
role placeholders, relative due days) → the caller saves it as an ordinary template. Mock-mode
fixtures: ``ai/evals/fixtures/mock_responses/template_from_brief.yaml``."""

from __future__ import annotations

from tests.helpers import Clients


async def test_draft_then_save_a_template_from_a_description(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    drafted = await ravi.post(
        "/api/v1/ai/templates/from-brief",
        json={
            "brief": "onboard a new hire: IT sets up equipment and accounts, manager does intros"
        },
    )
    assert drafted.status_code == 200, drafted.text
    draft = drafted.json()
    assert draft["name"] == "New hire onboarding"
    section_names = [s["name"] for s in draft["sections"]]
    assert section_names == ["Before day one", "Week one"]
    week_one = next(s for s in draft["sections"] if s["name"] == "Week one")
    setup = next(t for t in week_one["tasks"] if t["title"] == "Set up accounts")
    assert setup["role"] == "IT" and setup["subtasks"] == ["Email", "Chat", "VPN"]

    saved = await ravi.post(
        "/api/v1/ai/templates/from-brief/save",
        json={"name": draft["name"], "description": draft["description"], "draft": draft},
    )
    assert saved.status_code == 200, saved.text
    template = saved.json()["data"]
    assert template["kind"] == "project" and template["project_id"] is None
    payload = template["payload"]
    it_role = next(r for r in payload["roles"] if r["label"] == "IT")
    manager_role = next(r for r in payload["roles"] if r["label"] == "Manager")
    assert it_role["id"] != manager_role["id"]
    before = next(s for s in payload["sections"] if s["name"] == "Before day one")
    order_equipment = next(t for t in before["tasks"] if t["title"] == "Order equipment")
    assert order_equipment["role_id"] == it_role["id"]
    assert order_equipment["due_offset_days"] == 0
    assert payload["fields"] == [] and payload["rules"] == []

    # the ordinary "new from template" flow works unchanged on an AI-authored template
    team = (await ravi.get("/api/v1/teams")).json()["data"]
    team_id = next(t["id"] for t in team if t["name"] == "Product")
    made = await ravi.post(
        f"/api/v1/templates/{template['id']}/new-project",
        json={
            "team_id": team_id,
            "name": "Onboard Dana",
            "start_date": "2026-11-01",
            "role_mapping": [{"role_id": it_role["id"], "user_id": None}],
        },
    )
    assert made.status_code == 201, made.text


async def test_a_vague_description_still_produces_a_minimal_valid_draft(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    r = await ravi.post(
        "/api/v1/ai/templates/from-brief", json={"brief": "single step no details please"}
    )
    assert r.status_code == 200, r.text
    draft = r.json()
    assert len(draft["sections"]) == 1
    assert draft["sections"][0]["tasks"][0]["title"] == "Do the thing"


async def test_an_empty_brief_is_rejected(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    r = await ravi.post("/api/v1/ai/templates/from-brief", json={"brief": "   "})
    assert r.status_code == 422
