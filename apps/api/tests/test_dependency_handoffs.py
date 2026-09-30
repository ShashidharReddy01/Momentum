"""S6.1.3 Dependency hand-offs: when a task's last open blocker is completed its assignee hears
"You're up" (without leaking a blocker they may not see), a ``task.unblocked`` rules trigger
fires, and project templates (captured or AI-drafted) keep their "waits on" links."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.ai.template_from_brief import DraftSection, DraftTask, TemplateDraft, to_payload
from momentum.core.settings import Settings
from momentum.domain.comments.models import Comment
from momentum.domain.rules.engine import run_rules
from tests.helpers import Clients

SessionFactory = async_sessionmaker[AsyncSession]


async def _project(c: httpx.AsyncClient, name: str = "Website Revamp") -> str:
    return next(
        p["id"] for p in (await c.get("/api/v1/projects")).json()["data"] if p["name"] == name
    )


async def _user_id(c: httpx.AsyncClient, local: str) -> str:
    users = (await c.get("/api/v1/users")).json()["data"]
    return next(u["id"] for u in users if u["email"].startswith(f"{local}@"))


async def _task(c: httpx.AsyncClient, pid: str, title: str, **body: Any) -> str:
    r = await c.post(f"/api/v1/projects/{pid}/tasks", json={"title": title, **body})
    assert r.status_code == 201, r.text
    return str(r.json()["data"]["id"])


async def _block(c: httpx.AsyncClient, task: str, on: str) -> None:
    r = await c.post(f"/api/v1/tasks/{task}/dependencies", json={"depends_on_id": on})
    assert r.status_code == 201, r.text


async def _complete(c: httpx.AsyncClient, task: str) -> httpx.Response:
    r = await c.post(f"/api/v1/tasks/{task}/complete?force=true")
    assert r.status_code == 200, r.text
    return r


async def _youre_up(c: httpx.AsyncClient) -> list[dict[str, Any]]:
    return [
        n for n in (await c.get("/api/v1/notifications")).json()["data"] if n["kind"] == "unblocked"
    ]


async def test_last_blocker_done_tells_the_assignee(as_user: Clients) -> None:
    ravi, mei = await as_user("ravi"), await as_user("mei")
    pid = await _project(ravi)
    mei_id = await _user_id(ravi, "mei")
    design = await _task(ravi, pid, "Design")
    copy = await _task(ravi, pid, "Copy")
    build = await _task(ravi, pid, "Build", assignee_id=mei_id)
    await _block(ravi, build, design)
    await _block(ravi, build, copy)

    await _complete(ravi, design)
    assert await _youre_up(mei) == []  # still waiting on Copy

    await _complete(ravi, copy)
    (note,) = await _youre_up(mei)
    assert note["entity_id"] == build
    assert note["title"] == 'You\'re up: "Build" is ready to start'
    assert note["snippet"].endswith("Copy is done")  # same project: the blocker is named


async def test_a_blocker_in_another_project_is_not_named(as_user: Clients) -> None:
    ravi, mei = await as_user("ravi"), await as_user("mei")
    web = await _project(ravi)
    private = await _project(ravi, "Mobile App v2")  # mei can't see this one
    mei_id = await _user_id(ravi, "mei")
    secret = await _task(ravi, private, "Secret vendor deal")
    build = await _task(ravi, web, "Build", assignee_id=mei_id)
    await _block(ravi, build, secret)

    await _complete(ravi, secret)
    (note,) = await _youre_up(mei)
    assert "Secret" not in note["snippet"] and "Secret" not in note["title"]
    assert note["snippet"] == "The last task it was waiting on is done"


async def test_prefs_self_and_undo_stay_quiet(as_user: Clients) -> None:
    ravi, mei = await as_user("ravi"), await as_user("mei")
    pid = await _project(ravi)
    mei_id, ravi_id = await _user_id(ravi, "mei"), await _user_id(ravi, "ravi")
    a = await _task(ravi, pid, "A")
    mine = await _task(ravi, pid, "Mine", assignee_id=ravi_id)
    hers = await _task(ravi, pid, "Hers", assignee_id=mei_id)
    await _block(ravi, mine, a)
    await _block(ravi, hers, a)

    prefs = (await mei.get("/api/v1/me/prefs/notifications")).json()
    assert prefs["unblocked"] == "in_app"
    prefs["unblocked"] = "off"
    assert (await mei.put("/api/v1/me/prefs/notifications", json=prefs)).status_code == 200

    done = await _complete(ravi, a)
    assert await _youre_up(mei) == []  # she turned it off
    assert await _youre_up(ravi) == []  # never told about your own action

    # undoing the completion re-blocks quietly
    u = await ravi.post("/api/v1/undo", json={"activity_id": done.json()["meta"]["activity_id"]})
    assert u.status_code == 200, u.text
    assert await _youre_up(ravi) == []


async def test_task_unblocked_is_a_rules_trigger(
    as_user: Clients, session_factory: SessionFactory, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    a = await _task(ravi, pid, "A")
    b = await _task(ravi, pid, "B")
    await _block(ravi, b, a)
    r = await ravi.post(
        "/api/v1/rules",
        json={
            "name": "Kick off",
            "project_id": pid,
            "trigger": {"type": "task.unblocked"},
            "actions": [{"type": "add_comment", "text": "Ready to start"}],
        },
    )
    assert r.status_code == 201, r.text

    await _complete(ravi, a)
    async with session_factory() as s, s.begin():
        await run_rules(s, settings)
    async with session_factory() as s:
        comments = list(
            (await s.execute(select(Comment).where(Comment.task_id == b))).scalars()  # type: ignore[arg-type]
        )
    assert [c.body_text for c in comments] == ["Ready to start"]


async def test_project_templates_keep_dependencies(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    sign = await _task(ravi, pid, "Sign contract")
    launch = await _task(ravi, pid, "Launch")
    await _block(ravi, launch, sign)

    saved = await ravi.post(
        "/api/v1/templates/from-project", json={"project_id": pid, "name": "With deps"}
    )
    assert saved.status_code == 201, saved.text
    template = saved.json()["data"]
    assert len(template["payload"]["dependencies"]) == 1

    teams = (await ravi.get("/api/v1/teams")).json()["data"]
    team = next(t["id"] for t in teams if t["name"] == "Product")
    made = await ravi.post(
        f"/api/v1/templates/{template['id']}/new-project",
        json={"team_id": team, "name": "From template", "start_date": "2026-11-02"},
    )
    assert made.status_code == 201, made.text
    new_pid = made.json()["data"]["id"]
    tasks = {
        t["title"]: t["id"]
        for t in (await ravi.get(f"/api/v1/projects/{new_pid}/tasks")).json()["data"]
    }
    edges = (await ravi.get(f"/api/v1/projects/{new_pid}/dependencies")).json()["data"]
    assert [(e["task_id"], e["depends_on_id"]) for e in edges] == [
        (tasks["Launch"], tasks["Sign contract"])
    ]


def test_ai_drafted_templates_map_after_titles_to_dependencies() -> None:
    draft = TemplateDraft(
        name="Vendor onboarding",
        sections=[
            DraftSection(name="Legal", tasks=[DraftTask(title="Sign contract")]),
            DraftSection(
                name="Setup",
                tasks=[
                    DraftTask(title="Create accounts", after=["sign contract"]),  # any case
                    DraftTask(
                        title="Kickoff call", after=["Create accounts", "Made up", "Kickoff call"]
                    ),
                ],
            ),
        ],
    )
    payload = to_payload(draft)
    # unknown titles and self-references are dropped, not guessed
    assert payload["dependencies"] == [
        {"task": [1, 0], "blocked_by": [0, 0]},
        {"task": [1, 1], "blocked_by": [1, 0]},
    ]
