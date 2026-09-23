"""S1.4.3: undo coverage. Every Phase 1 mutation type is undoable and restores the exact state.

Each row: take a snapshot, run the mutation, check something changed, undo it (by activity or
batch), and check the snapshot is back to what it was. Plus a static check that every undo op the
code records has a registered handler."""

from __future__ import annotations

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
    ops = set()
    for path in root.rglob("*.py"):
        ops |= set(re.findall(r'undo_op\(\s*"([a-z_.]+)"', path.read_text()))
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
    cases: list[
        tuple[str, Callable[[], Awaitable[Any]], Callable[[], Awaitable[httpx.Response]]]
    ] = [
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
