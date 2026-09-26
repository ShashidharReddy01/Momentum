"""A tiny recorded-fixture Asana API for J6 (`docs/engineering/testing-strategy.md`'s "Asana
import against a recorded fixture API"). Serves the exact same synthetic workspace as the backend
unit test's `FakeAsanaClient` (`apps/api/tests/test_asana_import.py`) — same gids, same expected
import counts — just over real HTTP, since J6 drives the import through the browser UI and a real
running server, which can't take a Python-level fake client the way a unit test can.

Started by `serve.sh` alongside the real app; `MOMENTUM_ASANA_BASE_URL` points the app's
`AsanaClient` at it instead of the real Asana API for the duration of the E2E run.
"""

from __future__ import annotations

from fastapi import FastAPI
from starlette.responses import JSONResponse

app = FastAPI()


def _page(items: list[dict]) -> JSONResponse:
    return JSONResponse({"data": items, "next_page": None})


@app.get("/teams/{team_gid}/users")
async def team_users(team_gid: str) -> JSONResponse:
    return _page(
        [
            {"gid": "u1", "name": "Ravi Kumar", "email": "ravi@acme-demo.test"},
            {"gid": "u2", "name": "Someone Else", "email": "someone@example.com"},
        ]
    )


@app.get("/teams/{team_gid}/projects")
async def projects(team_gid: str) -> JSONResponse:
    return _page(
        [
            {
                "gid": "p1",
                "name": "Imported Project",
                "archived": False,
                "privacy_setting": "private_to_team",
                "start_on": "2026-01-01",
                "due_on": None,
            }
        ]
    )


@app.get("/projects/{project_gid}/sections")
async def sections(project_gid: str) -> JSONResponse:
    return _page([{"gid": "s1", "name": "To do"}, {"gid": "s2", "name": "Done"}])


@app.get("/sections/{section_gid}/tasks")
async def tasks(section_gid: str) -> JSONResponse:
    if section_gid == "s1":
        return _page(
            [
                {
                    "gid": "t1",
                    "name": "Ship the release",
                    "html_notes": "<body><p>Careful with <strong>prod</strong>.</p></body>",
                    "resource_subtype": "default_task",
                    "assignee": {"email": "ravi@acme-demo.test"},
                    "created_by": {"email": "ravi@acme-demo.test"},
                    "completed": False,
                    "tags": [{"gid": "tag1"}],
                    "num_subtasks": 1,
                },
                {
                    "gid": "t2",
                    "name": "Kickoff milestone",
                    "resource_subtype": "milestone",
                    "completed": True,
                    "completed_at": "2026-01-05T10:00:00.000Z",
                },
            ]
        )
    return _page([{"gid": "t3", "name": "Legacy separator row", "resource_subtype": "section"}])


@app.get("/tasks/{task_gid}/subtasks")
async def subtasks(task_gid: str) -> JSONResponse:
    return _page([{"gid": "t1-sub1", "name": "Notify support", "resource_subtype": "default_task"}])


@app.get("/workspaces/{workspace_gid}/tags")
async def tags(workspace_gid: str) -> JSONResponse:
    return _page([{"gid": "tag1", "name": "Urgent", "color": "red"}])


@app.get("/healthz")
async def healthz() -> dict[str, bool]:
    return {"ok": True}
