"""S1.4.3: undo coverage. Every Phase 1 mutation type is undoable and restores the exact state.

Each row: take a snapshot, run the mutation, check something changed, undo it (by activity or
batch), and check the snapshot is back to what it was. Plus a static check that every undo op the
code records has a registered handler."""

from __future__ import annotations

import ast
import importlib
import pkgutil
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx

import momentum
from momentum.core.undo import _HANDLERS
from tests.helpers import Clients

BASE = "/api/v1"
VOLATILE = {"version", "updated_at", "edited_at", "followers", "description_hash", "my_role"}


def normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    return value


def test_every_recorded_undo_op_has_a_handler() -> None:
    root = Path(momentum.__file__).parent
    # handlers register when their service modules are imported
    for mod in pkgutil.walk_packages([str(root / "domain")], "momentum.domain."):
        if mod.name.endswith(".service"):
            importlib.import_module(mod.name)
    # AI modules that record undoable changes (S3.1.5 memory); without this the check passed
    # only when another test had imported them first
    for mod in pkgutil.walk_packages([str(root / "ai")], "momentum.ai."):
        if not mod.ispkg:
            importlib.import_module(mod.name)
    ops = set()
    for path in root.rglob("*.py"):
        ops |= set(re.findall(r'undo_op\(\s*"([a-z_.]+)"', path.read_text(encoding="utf-8")))
    assert ops, "no undo ops found"
    missing = ops - set(_HANDLERS)
    assert not missing, f"undo ops without a handler: {sorted(missing)}"


async def _roundtrip(
    c: httpx.AsyncClient,
    snap: Callable[[], Awaitable[Any]],
    action: Callable[[], Awaitable[httpx.Response]],
    label: str,
) -> None:
    before = normalize(await snap())
    r = await action()
    assert r.status_code in (200, 201), f"{label}: {r.text}"
    meta = r.json()["meta"]
    after = normalize(await snap())
    assert after != before, f"{label}: nothing changed"
    body = (
        {"batch_id": meta["batch_id"]}
        if meta.get("batch_id")
        else {"activity_id": meta["activity_id"]}
    )
    assert body.get("batch_id") or body.get("activity_id"), f"{label}: no undo handle"
    u = await c.post(f"{BASE}/undo", json=body)
    assert u.status_code == 200, f"{label}: undo failed {u.text}"
    assert normalize(await snap()) == before, f"{label}: not restored"


async def _status_snap(c: httpx.AsyncClient, pid: str) -> Any:
    project = (await c.get(f"{BASE}/projects/{pid}")).json()
    history = (await c.get(f"{BASE}/projects/{pid}/status-updates")).json()["data"]
    return [project, history]


async def test_undo_restores_every_phase_1_mutation(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    users = {
        u["email"].split("@")[0]: u["id"] for u in (await ravi.get(f"{BASE}/users")).json()["data"]
    }
    teams = {t["name"]: t["id"] for t in (await ravi.get(f"{BASE}/teams")).json()["data"]}
    team = teams["Product"]
    pid = next(
        p["id"]
        for p in (await ravi.get(f"{BASE}/projects")).json()["data"]
        if p["name"] == "Website Revamp"
    )
    secs = {
        s["name"]: s["id"]
        for s in (await ravi.get(f"{BASE}/projects/{pid}/sections")).json()["data"]
    }

    async def get(url: str) -> Any:
        r = await ravi.get(url)
        return r.json() if r.status_code == 200 else r.status_code

    async def team_snap() -> Any:
        return [await get(f"{BASE}/teams/{team}"), await get(f"{BASE}/teams/{team}/members")]

    async def project_snap() -> Any:
        return [await get(f"{BASE}/projects/{pid}"), await get(f"{BASE}/projects/{pid}/members")]

    async def list_snap() -> Any:
        return [
            await get(f"{BASE}/projects/{pid}/sections"),
            await get(f"{BASE}/projects/{pid}/tasks"),
        ]

    t = (await ravi.post(f"{BASE}/projects/{pid}/tasks", json={"title": "Undo me"})).json()["data"]
    t2 = (await ravi.post(f"{BASE}/projects/{pid}/tasks", json={"title": "Undo me too"})).json()[
        "data"
    ]
    parent_sub = (
        await ravi.post(f"{BASE}/tasks/{t['id']}/subtasks", json={"title": "Sub A"})
    ).json()["data"]
    await ravi.post(f"{BASE}/tasks/{t['id']}/subtasks", json={"title": "Sub B"})
    task_url = f"{BASE}/tasks/{t['id']}"

    async def task_snap() -> Any:
        return [
            await get(task_url),
            await get(f"{task_url}/subtasks"),
            await get(f"{BASE}/projects/{pid}/tasks"),
            await get(f"{task_url}/comments"),
        ]

    async def followers() -> Any:
        # the set matters; a re-added follower is listed last
        return sorted((await ravi.get(task_url)).json()["followers"])

    doc = {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Text"}]}],
    }
    comment = (await ravi.post(f"{task_url}/comments", json={"body": doc})).json()["data"]
    project_file = (
        await ravi.post(
            f"{BASE}/projects/{pid}/files", files={"file": ("plan.txt", b"v1", "text/plain")}
        )
    ).json()["data"]

    async def files_snap() -> Any:
        return [
            await get(f"{BASE}/projects/{pid}/files"),
            await get(f"{BASE}/attachments/{project_file['id']}/versions"),
        ]

    cases: list[
        tuple[str, Callable[[], Awaitable[Any]], Callable[[], Awaitable[httpx.Response]]]
    ] = [
        # status updates (S3.4.3): the update and the project's status
        (
            "status update posted",
            lambda: _status_snap(ravi, pid),
            lambda: ravi.post(
                f"{BASE}/projects/{pid}/status-updates",
                json={"status": "at_risk", "title": "Late", "summary": "Copy is late"},
            ),
        ),
        # teams
        (
            "team rename",
            team_snap,
            lambda: ravi.patch(f"{BASE}/teams/{team}", json={"name": "Product 2"}),
        ),
        (
            "team add member",
            team_snap,
            lambda: ravi.post(
                f"{BASE}/teams/{team}/members", json={"user_id": users["tom"], "role": "member"}
            ),
        ),
        (
            "team set role",
            team_snap,
            lambda: ravi.patch(
                f"{BASE}/teams/{team}/members/{users['ana']}", json={"role": "lead"}
            ),
        ),
        (
            "team remove member",
            team_snap,
            lambda: ravi.delete(f"{BASE}/teams/{team}/members/{users['mei']}"),
        ),
        # projects
        (
            "project rename",
            project_snap,
            lambda: ravi.patch(f"{BASE}/projects/{pid}", json={"name": "WR 2"}),
        ),
        ("project archive", project_snap, lambda: ravi.post(f"{BASE}/projects/{pid}/archive")),
        (
            "project add member",
            project_snap,
            lambda: ravi.post(
                f"{BASE}/projects/{pid}/members", json={"user_id": users["tom"], "role": "viewer"}
            ),
        ),
        # sections
        (
            "section create",
            list_snap,
            lambda: ravi.post(f"{BASE}/projects/{pid}/sections", json={"name": "New"}),
        ),
        (
            "section rename",
            list_snap,
            lambda: ravi.patch(f"{BASE}/sections/{secs['Review']}", json={"name": "QA"}),
        ),
        (
            "section move",
            list_snap,
            lambda: ravi.post(
                f"{BASE}/sections/{secs['Done']}/move", json={"before_id": secs["Backlog"]}
            ),
        ),
        (
            "section delete (tasks move)",
            list_snap,
            lambda: ravi.delete(
                f"{BASE}/sections/{secs['Backlog']}",
                params={"tasks": "move_to", "target_section_id": secs["Review"]},
            ),
        ),
        # tasks
        (
            "task create",
            list_snap,
            lambda: ravi.post(f"{BASE}/projects/{pid}/tasks", json={"title": "Fresh"}),
        ),
        (
            "task batch create",
            list_snap,
            lambda: ravi.post(f"{BASE}/projects/{pid}/tasks/batch", json={"titles": ["a", "b"]}),
        ),
        ("task rename", task_snap, lambda: ravi.patch(task_url, json={"title": "Renamed"})),
        (
            "task assign",
            task_snap,
            lambda: ravi.patch(task_url, json={"assignee_id": users["ana"]}),
        ),
        (
            "task dates",
            task_snap,
            lambda: ravi.patch(
                task_url,
                json={
                    "start_on": "2026-10-01",
                    "due_on": "2026-10-05",
                    "due_at": "2026-10-05T17:00:00Z",
                },
            ),
        ),
        ("task description", task_snap, lambda: ravi.patch(task_url, json={"description": doc})),
        ("task complete", task_snap, lambda: ravi.post(f"{task_url}/complete")),
        ("task delete", list_snap, lambda: ravi.delete(task_url)),
        (
            "task move",
            list_snap,
            lambda: ravi.post(f"{task_url}/move", json={"section_id": secs["Done"]}),
        ),
        (
            "bulk update",
            list_snap,
            lambda: ravi.post(
                f"{BASE}/tasks/bulk",
                json={
                    "task_ids": [t["id"], t2["id"]],
                    "action": "update",
                    "patch": {"due_on": "2026-11-01"},
                },
            ),
        ),
        (
            "bulk complete",
            list_snap,
            lambda: ravi.post(
                f"{BASE}/tasks/bulk", json={"task_ids": [t["id"], t2["id"]], "action": "complete"}
            ),
        ),
        (
            "bulk move",
            list_snap,
            lambda: ravi.post(
                f"{BASE}/tasks/bulk",
                json={
                    "task_ids": [t["id"], t2["id"]],
                    "action": "move",
                    "section_id": secs["Review"],
                },
            ),
        ),
        (
            "bulk delete",
            list_snap,
            lambda: ravi.post(
                f"{BASE}/tasks/bulk", json={"task_ids": [t["id"], t2["id"]], "action": "delete"}
            ),
        ),
        # subtasks
        (
            "subtask create",
            task_snap,
            lambda: ravi.post(f"{task_url}/subtasks", json={"title": "Sub C"}),
        ),
        (
            "subtask reorder",
            task_snap,
            lambda: ravi.post(
                f"{BASE}/tasks/{parent_sub['id']}/subtask-move",
                json={"before_id": None, "after_id": None},
            ),
        ),
        (
            "subtask outdent",
            task_snap,
            lambda: ravi.post(f"{BASE}/tasks/{parent_sub['id']}/outdent"),
        ),
        # followers
        (
            "follower add",
            followers,
            lambda: ravi.post(f"{task_url}/followers", json={"user_id": users["priya"]}),
        ),
        (
            "follower remove",
            followers,
            lambda: ravi.delete(f"{task_url}/followers/{users['ravi']}"),
        ),
        # comments
        (
            "comment create",
            task_snap,
            lambda: ravi.post(f"{task_url}/comments", json={"body": doc}),
        ),
        (
            "comment edit",
            task_snap,
            lambda: ravi.patch(
                f"{BASE}/comments/{comment['id']}",
                json={
                    "body": {
                        **doc,
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "Edited"}]}
                        ],
                    }
                },
            ),
        ),
        ("comment delete", task_snap, lambda: ravi.delete(f"{BASE}/comments/{comment['id']}")),
        # Phase 7.5 S75-01: project files and versions
        (
            "project file upload",
            files_snap,
            lambda: ravi.post(
                f"{BASE}/projects/{pid}/files", files={"file": ("a.txt", b"a", "text/plain")}
            ),
        ),
        (
            "project file new version",
            files_snap,
            lambda: ravi.post(
                f"{BASE}/projects/{pid}/files",
                files={"file": ("plan.txt", b"v2", "text/plain")},
                data={"replace_id": project_file["id"]},
            ),
        ),
        (
            "project file delete",
            files_snap,
            lambda: ravi.delete(f"{BASE}/attachments/{project_file['id']}"),
        ),
    ]
    for label, snap, action in cases:
        await _roundtrip(ravi, snap, action, label)
    # project delete last (it hides everything else)
    await _roundtrip(
        ravi,
        lambda: get(f"{BASE}/projects/{pid}"),
        lambda: ravi.delete(f"{BASE}/projects/{pid}"),
        "project delete",
    )


async def test_undo_restores_tags_fields_rules_forms_and_reactions(as_user: Clients) -> None:
    """Phase 7 E7.0 undo audit: tagging (H53), field management (H55), deleting a rule or a form
    (H56) and reactions (H57) are undoable and restore the exact state."""
    ravi = await as_user("ravi")
    pid = next(
        p["id"]
        for p in (await ravi.get(f"{BASE}/projects")).json()["data"]
        if p["name"] == "Website Revamp"
    )
    t = (await ravi.post(f"{BASE}/projects/{pid}/tasks", json={"title": "Undo tags"})).json()[
        "data"
    ]
    task_url = f"{BASE}/tasks/{t['id']}"

    async def get(url: str) -> Any:
        r = await ravi.get(url)
        return r.json() if r.status_code == 200 else r.status_code

    tag = (await ravi.post(f"{BASE}/tags", json={"name": "Undo tag"})).json()["data"]["id"]
    spare = (await ravi.post(f"{BASE}/tags", json={"name": "Spare tag"})).json()["data"]["id"]
    await ravi.post(f"{task_url}/tags", json={"tag_id": tag})
    fields_url = f"{BASE}/projects/{pid}/fields"
    effort = (await ravi.post(fields_url, json={"name": "Effort", "type": "number"})).json()[
        "data"
    ]["id"]
    notes = (await ravi.post(fields_url, json={"name": "Notes", "type": "text"})).json()["data"][
        "id"
    ]
    await ravi.put(f"{task_url}/fields/{effort}", json={"value": 5})
    rule = (
        await ravi.post(
            f"{BASE}/rules",
            json={
                "name": "R",
                "project_id": pid,
                "trigger": {"type": "task.completed"},
                "actions": [{"type": "add_comment", "text": "hi"}],
            },
        )
    ).json()["data"]["id"]
    form = (
        await ravi.post(
            f"{BASE}/forms",
            json={
                "project_id": pid,
                "name": "Requests",
                "public_enabled": True,
                "questions": [
                    {"id": "q_title", "label": "Title", "required": True, "maps_to": "title"}
                ],
            },
        )
    ).json()["data"]
    doc = {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Nice"}]}],
    }
    comment = (await ravi.post(f"{task_url}/comments", json={"body": doc})).json()["data"]

    async def tags() -> Any:
        return [
            await get(f"{BASE}/tags"),
            await get(f"{task_url}/tags"),
            await get(f"{BASE}/tags/{tag}/tasks"),
        ]

    async def fields() -> Any:
        return [await get(fields_url), await get(f"{task_url}/fields"), await get(f"{BASE}/fields")]

    cases: list[
        tuple[str, Callable[[], Awaitable[Any]], Callable[[], Awaitable[httpx.Response]]]
    ] = [
        ("tag a task", tags, lambda: ravi.post(f"{task_url}/tags", json={"tag_id": spare})),
        ("untag a task", tags, lambda: ravi.delete(f"{task_url}/tags/{tag}")),
        ("tag create", tags, lambda: ravi.post(f"{BASE}/tags", json={"name": "Another"})),
        (
            "tag rename",
            tags,
            lambda: ravi.patch(f"{BASE}/tags/{tag}", json={"name": "Renamed", "color": "#ef4444"}),
        ),
        ("tag delete", tags, lambda: ravi.delete(f"{BASE}/tags/{tag}")),
        (
            "field hide",
            fields,
            lambda: ravi.patch(f"{fields_url}/{effort}/visibility", json={"is_visible": False}),
        ),
        (
            "field move",
            fields,
            lambda: ravi.post(f"{fields_url}/{notes}/move", json={"before_id": effort}),
        ),
        ("field remove from project", fields, lambda: ravi.delete(f"{fields_url}/{effort}")),
        ("field archive", fields, lambda: ravi.post(f"{fields_url}/{effort}/archive")),
        (
            "rule delete",
            lambda: get(f"{BASE}/rules?project_id={pid}"),
            lambda: ravi.delete(f"{BASE}/rules/{rule}"),
        ),
        (
            "form delete",
            lambda: get(f"{BASE}/forms?project_id={pid}"),
            lambda: ravi.delete(f"{BASE}/forms/{form['id']}"),
        ),
        (
            "reaction",
            lambda: get(f"{task_url}/comments"),
            lambda: ravi.post(f"{BASE}/comments/{comment['id']}/reactions", json={"emoji": "🎉"}),
        ),
    ]
    for label, snap, action in cases:
        await _roundtrip(ravi, snap, action, label)
    # the restored form's public link works again
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=as_user.app), base_url="http://testserver"
    ) as anon:
        r = await anon.get(f"{BASE}/public/forms/{form['public_token']}")
    assert r.status_code == 200, r.text


async def test_a_deleted_tags_name_can_be_used_again(as_user: Clients) -> None:
    """H54: deleting a tag frees its name (creating it again used to fail with a 500); undoing
    the delete is then refused instead of making two tags with one name."""
    ravi = await as_user("ravi")
    first = (await ravi.post(f"{BASE}/tags", json={"name": "Blocked"})).json()["data"]["id"]
    deleted = await ravi.delete(f"{BASE}/tags/{first}")
    again = await ravi.post(f"{BASE}/tags", json={"name": "blocked"})
    assert again.status_code == 201, again.text
    u = await ravi.post(f"{BASE}/undo", json={"activity_id": deleted.json()["meta"]["activity_id"]})
    assert u.status_code == 409
    assert "Blocked" in u.json()["detail"]


def test_every_mutation_records_activity() -> None:
    """CLAUDE.md: every mutation records an activity row. A service function that emits an event
    must also record activity, except the reviewed ones below (system events, computed data, AI
    streaming). Found field detach / reorder / show-hide and reactions without any (H55, H57)."""
    allowed = {
        "agents/runtime.py:execute_run",  # agent_run.finished: the run row is the record
        "ai/chat.py:run_chat",  # SSE stream events, not the outbox
        "ai/chat.py:tracked",
        "ai/command.py:run_command",
        "ai/loop.py:run_tool_loop",
        "ai/loop.py:_stream_text",
        "ai/loop.py:_streamed_step",
        "ai/loop.py:emit_proposals",  # proposals: the ai_actions row is the record
        "domain/forecasts/service.py:store",  # computed data (realtime catalog: no activity)
        "domain/forms/service.py:submit_form",  # create_task records the task's activity
        "domain/notifications/service.py:_create_or_coalesce",  # a notification is the record
        "domain/rules/due_scan.py:scan_due_approaching",  # a system trigger, not a change
        "domain/rules/engine.py:_fire",  # rule_runs is the record; actions go through services
        "domain/tasks/service.py:_hand_off",  # task.unblocked: a trigger, nothing changed
    }
    root = Path(momentum.__file__).parent
    found = set()
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.AsyncFunctionDef):
                continue
            if any("undo_handler" in ast.unparse(d) for d in fn.decorator_list):
                continue
            calls = {
                getattr(n.func, "id", getattr(n.func, "attr", ""))
                for n in ast.walk(fn)
                if isinstance(n, ast.Call)
            }
            if "emit" in calls and "record_activity" not in calls:
                found.add(f"{path.relative_to(root).as_posix()}:{fn.name}")
    assert found - allowed == set(), "mutations without an activity row"
    assert allowed - found == set(), "stale allowlist entries"
