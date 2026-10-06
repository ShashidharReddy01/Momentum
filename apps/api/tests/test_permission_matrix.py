"""Phase 1 exit: the task permission matrix (auth-and-permissions.md §5-6) in one table.

Every kind of user x every task action, on a private project, so a change to access rules
shows up here as a readable diff. Destructive actions each run on their own fresh task.
"""

from __future__ import annotations

from typing import Any

from tests.helpers import Clients

BASE = "/api/v1"
DOC = {
    "type": "doc",
    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "hi"}]}],
}

# who → (how they relate to the private project / task)
#   admin: project admin (owner) · editor/commenter/viewer: explicit project members
#   outsider: not a member · assignee: not a member, assigned the task
#   collaborator: not a member, added as a follower of the task
# An assignee gets editor access to that one task (incl. moving it between the project's
# sections and deleting it, both undoable) but still can't see or add to the project.
ACTIONS = [
    "view",
    "comment",
    "follow_self",
    "edit",
    "complete",
    "subtask",
    "move",
    "delete",
    "create",
]
EXPECTED: dict[str, dict[str, int]] = {
    #               view comment follow edit complete subtask move delete create
    "admin":        dict(zip(ACTIONS, [200, 201, 200, 200, 200, 201, 200, 200, 201], strict=True)),
    "editor":       dict(zip(ACTIONS, [200, 201, 200, 200, 200, 201, 200, 200, 201], strict=True)),
    "commenter":    dict(zip(ACTIONS, [200, 201, 200, 403, 403, 403, 403, 403, 403], strict=True)),
    "viewer":       dict(zip(ACTIONS, [200, 403, 403, 403, 403, 403, 403, 403, 403], strict=True)),
    "outsider":     dict(zip(ACTIONS, [404, 404, 404, 404, 404, 404, 404, 404, 404], strict=True)),
    "assignee":     dict(zip(ACTIONS, [200, 201, 200, 200, 200, 201, 200, 200, 404], strict=True)),
    "collaborator": dict(zip(ACTIONS, [200, 201, 200, 403, 403, 403, 403, 403, 404], strict=True)),
}  # fmt: skip
WHO = {
    "admin": "priya",
    "editor": "mei",
    "commenter": "sam",
    "viewer": "kim",
    "outsider": "tom",
    "assignee": "diego",
    "collaborator": "noor",
}


async def test_task_permission_matrix(as_user: Clients) -> None:
    priya = await as_user("priya")
    users = {
        u["email"].split("@")[0]: u["id"] for u in (await priya.get(f"{BASE}/users")).json()["data"]
    }
    pid = next(
        p["id"]
        for p in (await priya.get(f"{BASE}/projects")).json()["data"]
        if p["name"] == "Mobile App v2"  # private, owned by Priya
    )
    for local, role in (("mei", "editor"), ("sam", "commenter"), ("kim", "viewer")):
        r = await priya.post(
            f"{BASE}/projects/{pid}/members", json={"user_id": users[local], "role": role}
        )
        assert r.status_code == 201, r.text
    sections = (await priya.get(f"{BASE}/projects/{pid}/sections")).json()["data"]
    other_section = sections[-1]["id"]

    async def fresh_task() -> str:
        t = (await priya.post(f"{BASE}/projects/{pid}/tasks", json={"title": "Matrix"})).json()
        tid = str(t["data"]["id"])
        await priya.patch(f"{BASE}/tasks/{tid}", json={"assignee_id": users["diego"]})
        r = await priya.post(f"{BASE}/tasks/{tid}/followers", json={"user_id": users["noor"]})
        assert r.status_code == 200, r.text
        return tid

    got: dict[str, dict[str, int]] = {}
    for kind, local in WHO.items():
        c = await as_user(local)
        me = users[local]
        row: dict[str, int] = {}
        for action in ACTIONS:
            tid = await fresh_task()
            calls: dict[str, tuple[str, str, Any]] = {
                "view": ("GET", f"/tasks/{tid}", None),
                "comment": ("POST", f"/tasks/{tid}/comments", {"body": DOC}),
                "follow_self": ("POST", f"/tasks/{tid}/followers", {"user_id": me}),
                "edit": ("PATCH", f"/tasks/{tid}", {"title": f"By {kind}"}),
                "complete": ("POST", f"/tasks/{tid}/complete", None),
                "subtask": ("POST", f"/tasks/{tid}/subtasks", {"title": "Child"}),
                "move": ("POST", f"/tasks/{tid}/move", {"section_id": other_section}),
                "delete": ("DELETE", f"/tasks/{tid}", None),
                "create": ("POST", f"/projects/{pid}/tasks", {"title": "New"}),
            }
            method, path, body = calls[action]
            r = await c.request(method, f"{BASE}{path}", json=body)
            row[action] = r.status_code
        got[kind] = row
    for kind in EXPECTED:
        assert got[kind] == EXPECTED[kind], f"{kind}: {got[kind]}"


# Phase 7.5 S75-01: a project's own files (spec §3.2) on the same private project. Viewers list
# and download; editors upload and add versions; the uploader or a project admin deletes.
FILE_ACTIONS = ["list", "download", "upload", "version", "delete_own_upload", "delete_others"]
FILE_EXPECTED: dict[str, dict[str, int]] = {
    #               list download upload version del_own del_others
    "admin":     dict(zip(FILE_ACTIONS, [200, 200, 201, 201, 200, 200], strict=True)),
    "editor":    dict(zip(FILE_ACTIONS, [200, 200, 201, 201, 200, 403], strict=True)),
    "commenter": dict(zip(FILE_ACTIONS, [200, 200, 403, 403, 403, 403], strict=True)),
    "viewer":    dict(zip(FILE_ACTIONS, [200, 200, 403, 403, 403, 403], strict=True)),
    "outsider":  dict(zip(FILE_ACTIONS, [404, 404, 404, 404, 404, 404], strict=True)),
}  # fmt: skip


async def test_project_files_permission_matrix(as_user: Clients) -> None:
    priya = await as_user("priya")
    users = {
        u["email"].split("@")[0]: u["id"] for u in (await priya.get(f"{BASE}/users")).json()["data"]
    }
    pid = next(
        p["id"]
        for p in (await priya.get(f"{BASE}/projects")).json()["data"]
        if p["name"] == "Mobile App v2"
    )
    for local, role in (("mei", "editor"), ("sam", "commenter"), ("kim", "viewer")):
        await priya.post(
            f"{BASE}/projects/{pid}/members", json={"user_id": users[local], "role": role}
        )

    async def upload(c: Any, **form: str) -> Any:
        return await c.post(
            f"{BASE}/projects/{pid}/files", files={"file": ("f.txt", b"x", "text/plain")}, data=form
        )

    got: dict[str, dict[str, int]] = {}
    for kind, local in {k: WHO[k] for k in FILE_EXPECTED}.items():
        c = await as_user(local)
        mine = (await upload(priya)).json()["data"]["id"]
        theirs = (await upload(priya)).json()["data"]["id"]
        row: dict[str, int] = {
            "list": (await c.get(f"{BASE}/projects/{pid}/files")).status_code,
            "download": (await c.get(f"{BASE}/attachments/{mine}/download")).status_code,
        }
        up = await upload(c)
        row["upload"] = up.status_code
        row["version"] = (await upload(c, replace_id=mine)).status_code
        own = up.json()["data"]["id"] if up.status_code == 201 else theirs
        row["delete_own_upload"] = (
            (await c.delete(f"{BASE}/attachments/{own}")).status_code
            if up.status_code == 201
            else row["upload"]
        )
        row["delete_others"] = (await c.delete(f"{BASE}/attachments/{theirs}")).status_code
        got[kind] = row
    for kind in FILE_EXPECTED:
        assert got[kind] == FILE_EXPECTED[kind], f"{kind}: {got[kind]}"
