"""E7.0 edge-case matrix, "deleted or archived parents": delete or archive each kind of parent
(section, parent task, task, project) or disable a person, then try everything that hangs off it.
Nothing may fail with a 5xx, and the outcomes found wrong by the first run stay fixed: a task
restored after its section was deleted is visible again (H58) and a form whose section was deleted
still takes submissions (H59). Run with ``-s`` to print every outcome."""

from __future__ import annotations

from typing import Any

import httpx

from tests.helpers import Clients

B = "/api/v1"
DOC = {
    "type": "doc",
    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "x"}]}],
}
LOG: list[str] = []


async def call(
    c: httpx.AsyncClient, label: str, method: str, url: str, **kw: Any
) -> httpx.Response:
    r = await c.request(method, url, **kw)
    body = r.text[:160].replace("\n", " ")
    LOG.append(f"{r.status_code} {label}: {body}")
    return r


async def test_probe_deleted_and_archived_parents(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    projects = {p["name"]: p["id"] for p in (await ravi.get(f"{B}/projects")).json()["data"]}
    pid = projects["Website Revamp"]
    other = next(v for k, v in projects.items() if k != "Website Revamp")
    users = {
        u["email"].split("@")[0]: u["id"] for u in (await ravi.get(f"{B}/users")).json()["data"]
    }

    async def task(title: str, **extra: Any) -> dict[str, Any]:
        r = await ravi.post(f"{B}/projects/{pid}/tasks", json={"title": title, **extra})
        assert r.status_code == 201, r.text
        return r.json()["data"]

    # ---- a deleted section
    sec = (await ravi.post(f"{B}/projects/{pid}/sections", json={"name": "Doomed"})).json()["data"]
    keep = (await ravi.post(f"{B}/projects/{pid}/sections", json={"name": "Keep"})).json()["data"]
    in_sec = await task("Lives in doomed", section_id=sec["id"])
    rule = await call(
        ravi,
        "rule moving into the section",
        "POST",
        f"{B}/rules",
        json={
            "name": "To doomed",
            "project_id": pid,
            "trigger": {"type": "task.completed"},
            "actions": [{"type": "move_section", "section_id": sec["id"]}],
        },
    )
    form = await call(
        ravi,
        "form into the section",
        "POST",
        f"{B}/forms",
        json={
            "project_id": pid,
            "name": "F",
            "section_id": sec["id"],
            "questions": [{"id": "q", "label": "T", "required": True, "maps_to": "title"}],
        },
    )
    deleted_sec = await call(
        ravi, "delete section (tasks deleted)", "DELETE", f"{B}/sections/{sec['id']}?tasks=delete"
    )
    await call(
        ravi,
        "create task in deleted section",
        "POST",
        f"{B}/projects/{pid}/tasks",
        json={"title": "x", "section_id": sec["id"]},
    )
    t1 = await task("Mover")
    await call(
        ravi,
        "move task into deleted section",
        "POST",
        f"{B}/tasks/{t1['id']}/move",
        json={"section_id": sec["id"]},
    )
    await call(
        ravi,
        "rename deleted section",
        "PATCH",
        f"{B}/sections/{sec['id']}",
        json={"name": "Zombie"},
    )
    await call(
        ravi,
        "add task to project in deleted section",
        "POST",
        f"{B}/tasks/{t1['id']}/projects",
        json={"project_id": pid, "section_id": sec["id"]},
    )
    await call(
        ravi,
        "complete a task (rule moves to deleted section)",
        "POST",
        f"{B}/tasks/{t1['id']}/complete",
    )
    await call(ravi, "task after the rule ran", "GET", f"{B}/tasks/{t1['id']}")
    if rule.status_code == 201:
        await call(ravi, "rule runs", "GET", f"{B}/rules/{rule.json()['data']['id']}/runs")
    if form.status_code == 201:
        f = form.json()["data"]
        sub = await call(
            ravi,
            "submit form whose section was deleted",
            "POST",
            f"{B}/forms/{f['id']}/submit",
            json={"answers": {"q": "From form"}},
        )
        assert sub.status_code == 200, sub.text  # H59
        titles = [t["title"] for t in (await ravi.get(f"{B}/projects/{pid}/tasks")).json()["data"]]
        assert "From form" in titles
    await call(ravi, "deleted section's task (deleted with it)", "GET", f"{B}/tasks/{in_sec['id']}")
    # undo the delete of an individual task whose section is gone
    t2 = await task("Undo into gone section", section_id=keep["id"])
    d2 = await call(ravi, "delete task in Keep", "DELETE", f"{B}/tasks/{t2['id']}")
    await call(
        ravi, "delete section Keep (move tasks to default)", "DELETE", f"{B}/sections/{keep['id']}"
    )
    await call(
        ravi,
        "undo task delete after its section went",
        "POST",
        f"{B}/undo",
        json={"activity_id": d2.json()["meta"]["activity_id"]},
    )
    await call(ravi, "restored task", "GET", f"{B}/tasks/{t2['id']}")
    listed = (await ravi.get(f"{B}/projects/{pid}/tasks")).json()["data"]
    assert any(t["id"] == t2["id"] for t in listed), "restored task invisible (H58)"
    await call(
        ravi,
        "undo the section delete (tasks deleted)",
        "POST",
        f"{B}/undo",
        json={"activity_id": deleted_sec.json().get("meta", {}).get("activity_id")},
    )

    # ---- a deleted parent task
    parent = await task("Parent")
    sub = (await ravi.post(f"{B}/tasks/{parent['id']}/subtasks", json={"title": "Child"})).json()[
        "data"
    ]
    dp = await call(ravi, "delete parent", "DELETE", f"{B}/tasks/{parent['id']}")
    await call(ravi, "subtask of deleted parent", "GET", f"{B}/tasks/{sub['id']}")
    await call(
        ravi,
        "add subtask to deleted parent",
        "POST",
        f"{B}/tasks/{parent['id']}/subtasks",
        json={"title": "Late child"},
    )
    await call(ravi, "complete child of deleted parent", "POST", f"{B}/tasks/{sub['id']}/complete")
    await call(
        ravi,
        "comment on child of deleted parent",
        "POST",
        f"{B}/tasks/{sub['id']}/comments",
        json={"body": DOC},
    )
    await call(ravi, "outdent child of deleted parent", "POST", f"{B}/tasks/{sub['id']}/outdent")
    await call(
        ravi,
        "undo parent delete",
        "POST",
        f"{B}/undo",
        json={"activity_id": dp.json()["meta"]["activity_id"]},
    )
    await call(ravi, "child after parent restored", "GET", f"{B}/tasks/{sub['id']}")

    # ---- a deleted task as the target of everything
    gone = await task("Gone")
    blocker = await task("Blocker")
    await ravi.post(f"{B}/tasks/{blocker['id']}/dependencies", json={"depends_on_id": gone["id"]})
    await call(ravi, "delete task that blocks another", "DELETE", f"{B}/tasks/{gone['id']}")
    await call(
        ravi,
        "blocked task's dependencies after its blocker was deleted",
        "GET",
        f"{B}/tasks/{blocker['id']}/dependencies",
    )
    await call(
        ravi, "blocked task after its blocker was deleted", "GET", f"{B}/tasks/{blocker['id']}"
    )
    for label, method, url, kw in [
        (
            "comment on deleted task",
            "POST",
            f"{B}/tasks/{gone['id']}/comments",
            {"json": {"body": DOC}},
        ),
        ("tag deleted task", "POST", f"{B}/tasks/{gone['id']}/tags", {"json": {"name": "zz"}}),
        (
            "depend on deleted task",
            "POST",
            f"{B}/tasks/{t1['id']}/dependencies",
            {"json": {"depends_on_id": gone["id"]}},
        ),
        (
            "deleted task depends on",
            "POST",
            f"{B}/tasks/{gone['id']}/dependencies",
            {"json": {"depends_on_id": t1["id"]}},
        ),
        ("edit deleted task", "PATCH", f"{B}/tasks/{gone['id']}", {"json": {"title": "Back?"}}),
        (
            "follow deleted task",
            "POST",
            f"{B}/tasks/{gone['id']}/followers",
            {"json": {"user_id": users["ana"]}},
        ),
        (
            "multi-home deleted task",
            "POST",
            f"{B}/tasks/{gone['id']}/projects",
            {"json": {"project_id": other}},
        ),
        (
            "reschedule deleted task",
            "POST",
            f"{B}/tasks/{gone['id']}/reschedule",
            {"json": {"due_on": "2026-12-01"}},
        ),
        (
            "convert deleted task",
            "POST",
            f"{B}/tasks/{gone['id']}/convert",
            {"json": {"type": "milestone"}},
        ),
        ("attachments of deleted task", "GET", f"{B}/tasks/{gone['id']}/attachments", {}),
        ("feed of deleted task", "GET", f"{B}/tasks/{gone['id']}/feed", {}),
    ]:
        r = await call(ravi, label, method, url, **kw)
        assert r.status_code == 404, f"{label}: {r.status_code}"

    # ---- an archived project
    arch = await task("In archived project")
    await call(ravi, "archive project", "POST", f"{B}/projects/{pid}/archive")
    await call(
        ravi,
        "create task in archived project",
        "POST",
        f"{B}/projects/{pid}/tasks",
        json={"title": "New in archive"},
    )
    await call(
        ravi,
        "edit task in archived project",
        "PATCH",
        f"{B}/tasks/{arch['id']}",
        json={"title": "Edited in archive"},
    )
    await call(
        ravi, "complete task in archived project", "POST", f"{B}/tasks/{arch['id']}/complete"
    )
    await call(
        ravi,
        "add section to archived project",
        "POST",
        f"{B}/projects/{pid}/sections",
        json={"name": "S"},
    )
    await call(
        ravi,
        "multi-home into archived project",
        "POST",
        f"{B}/tasks/{t1['id']}/projects",
        json={"project_id": pid},
    )
    pf = await call(ravi, "create portfolio", "POST", f"{B}/portfolios", json={"name": "P"})
    if pf.status_code == 201:
        await call(
            ravi,
            "add archived project to portfolio",
            "POST",
            f"{B}/portfolios/{pf.json()['data']['id']}/projects",
            json={"project_id": pid},
        )
    await call(ravi, "my tasks (archived project's task assigned?)", "GET", f"{B}/me/tasks")
    await call(ravi, "unarchive project", "POST", f"{B}/projects/{pid}/unarchive")

    # ---- a disabled person
    admin = await as_user("admin")
    await call(
        admin, "disable tom", "PATCH", f"{B}/users/{users['tom']}", json={"status": "disabled"}
    )
    t3 = await task("For tom")
    await call(
        ravi,
        "assign task to disabled tom",
        "PATCH",
        f"{B}/tasks/{t3['id']}",
        json={"assignee_id": users["tom"]},
    )
    await call(
        ravi,
        "create task assigned to disabled tom",
        "POST",
        f"{B}/projects/{pid}/tasks",
        json={"title": "x", "assignee_id": users["tom"]},
    )
    r = await call(
        ravi,
        "add disabled tom as follower",
        "POST",
        f"{B}/tasks/{t3['id']}/followers",
        json={"user_id": users["tom"]},
    )
    assert r.status_code == 422 and "follower" in r.json()["detail"]
    await call(
        ravi,
        "add disabled tom to project",
        "POST",
        f"{B}/projects/{pid}/members",
        json={"user_id": users["tom"], "role": "editor"},
    )
    await call(ravi, "mention search lists disabled tom?", "GET", f"{B}/mentions/search?q=tom")
    await call(
        admin, "re-enable tom", "PATCH", f"{B}/users/{users['tom']}", json={"status": "active"}
    )

    print("\n".join(LOG))
    assert not [line for line in LOG if line.startswith("5")], "server errors"
