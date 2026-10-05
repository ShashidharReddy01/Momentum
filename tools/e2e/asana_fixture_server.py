"""A recorded-fixture Asana API for J6 (`docs/engineering/testing-strategy.md`'s "Asana import
against a recorded fixture API"). It serves the synthetic workspace of
`momentum/integrations/asana_import/fixture.py` (the same data the backend tests import through
`FakeAsana`) over real HTTP, at the paths the real `AsanaClient` calls, since J6 drives the
import through the browser and a running server. Attachment downloads point back at this server.

Started by `serve.sh` alongside the real app; `MOMENTUM_ASANA_BASE_URL` points the app's
`AsanaClient` at it instead of the real Asana API for the duration of the E2E run.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse, Response

from momentum.integrations.asana_import.fixture import FILE_BYTES, FakeAsana

app = FastAPI()
asana = FakeAsana()


def _page(items: list[dict[str, Any]]) -> JSONResponse:
    return JSONResponse({"data": items, "next_page": None})


@app.get("/workspaces")
async def workspaces() -> JSONResponse:
    return _page(await asana.workspaces())


@app.get("/organizations/{workspace_gid}/teams")
async def teams(workspace_gid: str) -> JSONResponse:
    return _page(await asana.teams(workspace_gid))


@app.get("/workspaces/{workspace_gid}/users")
async def workspace_users(workspace_gid: str) -> JSONResponse:
    return _page(await asana.workspace_users(workspace_gid))


@app.get("/teams/{team_gid}/users")
async def team_users(team_gid: str) -> JSONResponse:
    return _page(await asana.team_users(team_gid))


@app.get("/teams/{team_gid}/projects")
async def projects(team_gid: str, archived: str | None = None) -> JSONResponse:
    return _page(await asana.projects(team_gid, include_archived=archived != "false"))


@app.get("/projects/{project_gid}/custom_field_settings")
async def custom_field_settings(project_gid: str) -> JSONResponse:
    return _page(await asana.custom_field_settings(project_gid))


@app.get("/projects/{project_gid}/sections")
async def sections(project_gid: str) -> JSONResponse:
    return _page(await asana.sections(project_gid))


@app.get("/sections/{section_gid}/tasks")
async def tasks(section_gid: str) -> JSONResponse:
    return _page(await asana.tasks(section_gid))


@app.get("/tasks/{task_gid}/subtasks")
async def subtasks(task_gid: str) -> JSONResponse:
    return _page(await asana.subtasks(task_gid))


@app.get("/tasks/{task_gid}/stories")
async def stories(task_gid: str) -> JSONResponse:
    return _page(await asana.stories(task_gid))


@app.get("/workspaces/{workspace_gid}/tags")
async def tags(workspace_gid: str) -> JSONResponse:
    return _page(await asana.tags(workspace_gid))


@app.get("/attachments")
async def attachments(parent: str, request: Request) -> JSONResponse:
    out = []
    for a in await asana.attachments(parent):
        if a.get("download_url"):  # files are served from here
            a = {**a, "download_url": f"{str(request.base_url).rstrip('/')}/files/{a['gid']}"}
        out.append(a)
    return _page(out)


@app.get("/status_updates")
async def status_updates(parent: str) -> JSONResponse:
    return _page(await asana.status_updates(parent))


@app.get("/files/{gid}")
async def file(gid: str) -> Response:
    return Response(FILE_BYTES, media_type="text/plain")


@app.get("/healthz")
async def healthz() -> dict[str, bool]:
    return {"ok": True}
