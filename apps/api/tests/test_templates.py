"""S4.3.1 Project templates: save a project's structure (sections, tasks, subtasks, dates
relative to a reference date, assignees as roles, fields, rules) and replay it into a new
project (pick a start date, map roles to people)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx

from tests.helpers import Clients


async def _team_id(c: httpx.AsyncClient, name: str) -> str:
    teams = (await c.get("/api/v1/teams")).json()["data"]
    return next(t["id"] for t in teams if t["name"] == name)


async def _project(c: httpx.AsyncClient, name: str = "Website Revamp") -> str:
    return next(
        p["id"] for p in (await c.get("/api/v1/projects")).json()["data"] if p["name"] == name
    )


async def _sections(c: httpx.AsyncClient, pid: str) -> dict[str, str]:
    rows = (await c.get(f"/api/v1/projects/{pid}/sections")).json()["data"]
    return {s["name"]: s["id"] for s in rows}


async def _task(c: httpx.AsyncClient, pid: str, section: str, title: str, **body: Any) -> str:
    r = await c.post(
        f"/api/v1/projects/{pid}/tasks", json={"title": title, "section_id": section, **body}
    )
    assert r.status_code == 201, r.text
    return str(r.json()["data"]["id"])


async def _user_id(c: httpx.AsyncClient, local: str) -> str:
    users = (await c.get("/api/v1/dev/users")).json()
    return str(next(u["id"] for u in users if u["email"] == f"{local}@acme-demo.test"))


async def test_save_and_instantiate_a_project_template(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    sections = await _sections(ravi, pid)
    mei_id = await _user_id(ravi, "mei")

    field = await ravi.post(f"/api/v1/projects/{pid}/fields", json={"name": "Risk", "type": "text"})
    assert field.status_code == 201, field.text
    field_id = field.json()["data"]["id"]

    parent = await _task(
        ravi,
        pid,
        sections["Backlog"],
        "Kickoff",
        assignee_id=mei_id,
        due_on="2026-10-05",
        priority="high",
    )
    await ravi.put(f"/api/v1/tasks/{parent}/fields/{field_id}", json={"value": "Watch the vendor"})
    sub = await ravi.post(f"/api/v1/tasks/{parent}/subtasks", json={"title": "Book the room"})
    assert sub.status_code == 201, sub.text

    rule = await ravi.post(
        "/api/v1/rules",
        json={
            "name": "Notify on move",
            "project_id": pid,
            "trigger": {"type": "task.moved", "to_section": sections["Review"]},
            "actions": [{"type": "assign", "user_id": mei_id}],
        },
    )
    assert rule.status_code == 201, rule.text

    saved = await ravi.post(
        "/api/v1/templates/from-project",
        json={"project_id": pid, "name": "Website launch", "description": "Standard launch"},
    )
    assert saved.status_code == 201, saved.text
    template = saved.json()["data"]
    payload = template["payload"]
    mei_role = next(r for r in payload["roles"] if r["label"] == "Mei Chen")
    role_id = mei_role["id"]
    backlog = next(s for s in payload["sections"] if s["name"] == "Backlog")
    kickoff = next(t for t in backlog["tasks"] if t["title"] == "Kickoff")
    assert kickoff["role_id"] == role_id
    due_offset = kickoff["due_offset_days"]
    assert due_offset is not None  # relative to the earliest date among the project's tasks
    assert kickoff["field_values"] == {field_id: "Watch the vendor"}
    assert [s["title"] for s in kickoff["subtasks"]] == ["Book the room"]
    assert field_id in payload["fields"]
    the_rule = next(r for r in payload["rules"] if r["name"] == "Notify on move")
    assert the_rule["actions"][0]["role_id"] == role_id
    assert "user_id" not in the_rule["actions"][0]

    team = await _team_id(ravi, "Product")
    made = await ravi.post(
        f"/api/v1/templates/{template['id']}/new-project",
        json={
            "team_id": team,
            "name": "Website launch v2",
            "start_date": "2026-11-01",
            "role_mapping": [{"role_id": role_id, "user_id": mei_id}],
        },
    )
    assert made.status_code == 201, made.text
    new_pid = made.json()["data"]["id"]

    new_sections = await _sections(ravi, new_pid)
    assert set(new_sections) == set(sections)
    tasks = (await ravi.get(f"/api/v1/projects/{new_pid}/tasks")).json()["data"]
    new_kickoff = next(t for t in tasks if t["title"] == "Kickoff")
    assert new_kickoff["assignee_id"] == mei_id
    expected_due = date(2026, 11, 1) + timedelta(days=due_offset)
    assert new_kickoff["due_on"] == expected_due.isoformat()
    assert new_kickoff["priority"] == "high"
    field_values = await ravi.get(f"/api/v1/tasks/{new_kickoff['id']}/fields")
    assert field_values.json()["data"][0]["value"] == "Watch the vendor"
    subtasks = await ravi.get(f"/api/v1/tasks/{new_kickoff['id']}/subtasks")
    assert [t["title"] for t in subtasks.json()["data"]] == ["Book the room"]

    new_rules = (await ravi.get(f"/api/v1/rules?project_id={new_pid}")).json()["data"]
    assert len(new_rules) == 1
    assert new_rules[0]["trigger"]["to_section"] == new_sections["Review"]
    assert new_rules[0]["actions"][0]["user_id"] == mei_id


async def test_only_a_project_admin_can_save_a_template(as_user: Clients) -> None:
    mei = await as_user("mei")
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    r = await mei.post("/api/v1/templates/from-project", json={"project_id": pid, "name": "Nope"})
    assert r.status_code == 403


async def test_a_new_project_without_a_role_mapping_leaves_tasks_unassigned(
    as_user: Clients,
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    sections = await _sections(ravi, pid)
    mei_id = await _user_id(ravi, "mei")
    await _task(ravi, pid, sections["Backlog"], "Solo task", assignee_id=mei_id)
    saved = await ravi.post(
        "/api/v1/templates/from-project", json={"project_id": pid, "name": "No mapping"}
    )
    template = saved.json()["data"]
    team = await _team_id(ravi, "Product")
    made = await ravi.post(
        f"/api/v1/templates/{template['id']}/new-project",
        json={"team_id": team, "name": "Unassigned copy", "start_date": "2026-11-01"},
    )
    assert made.status_code == 201, made.text
    new_pid = made.json()["data"]["id"]
    tasks = (await ravi.get(f"/api/v1/projects/{new_pid}/tasks")).json()["data"]
    assert tasks[0]["assignee_id"] is None


async def test_anyone_can_list_and_a_creator_or_admin_can_delete(as_user: Clients) -> None:
    ravi, mei, admin = await as_user("ravi"), await as_user("mei"), await as_user("admin")
    pid = await _project(ravi)
    saved = await ravi.post(
        "/api/v1/templates/from-project", json={"project_id": pid, "name": "Shared template"}
    )
    template_id = saved.json()["data"]["id"]
    listed = await mei.get("/api/v1/templates?kind=project")
    assert any(t["id"] == template_id for t in listed.json()["data"])
    assert (await mei.delete(f"/api/v1/templates/{template_id}")).status_code == 403
    assert (await admin.delete(f"/api/v1/templates/{template_id}")).status_code == 200
