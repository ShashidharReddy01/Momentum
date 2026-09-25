"""A thin, paginated Asana REST client (`docs/integrations/asana-import.md §1`).

`AsanaClient` is the only piece of this importer that makes real HTTP calls — everything else
(`mapping.py`, `service.py`) takes plain dicts, so tests drive the importer through a fake client
(`AsanaClient`-shaped, same method signatures) loaded from a recorded synthetic fixture, per the
roadmap's own "VCR-style recorded responses (synthetic data only)" testing note. There's no
`respx`/`vcrpy` dependency added for this — a plain fake with the same interface is simpler for
the handful of endpoints this importer actually calls, and needs no cassette-recording tooling.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

BASE_URL = "https://app.asana.com/api/1.0"
PAGE_LIMIT = 100
MAX_RETRIES = 5


class AsanaClient:
    def __init__(self, pat: str, *, http: httpx.AsyncClient | None = None) -> None:
        # The PAT lives only in this instance's memory for the lifetime of one import request —
        # never written to the database, a log, or a job queue (see `service.py`'s docstring for
        # why this importer runs synchronously rather than as a background job).
        self._http = http or httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {pat}"},
            timeout=30.0,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        for _attempt in range(MAX_RETRIES):
            resp = await self._http.get(path, params=params)
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", "1"))
                await asyncio.sleep(min(retry_after, 30))
                continue
            resp.raise_for_status()
            result: dict[str, Any] = resp.json()
            return result
        resp.raise_for_status()
        return {}

    async def _get_all(
        self, path: str, *, opt_fields: str | None = None, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        query: dict[str, Any] = {"limit": PAGE_LIMIT, **(params or {})}
        if opt_fields:
            query["opt_fields"] = opt_fields
        offset: str | None = None
        while True:
            if offset:
                query["offset"] = offset
            body = await self._get(path, params=query)
            out.extend(body.get("data", []))
            offset = (body.get("next_page") or {}).get("offset")
            if not offset:
                return out

    async def workspaces(self) -> list[dict[str, Any]]:
        return await self._get_all("/workspaces", opt_fields="gid,name,is_organization")

    async def teams(self, workspace_gid: str) -> list[dict[str, Any]]:
        return await self._get_all(
            f"/organizations/{workspace_gid}/teams", opt_fields="gid,name,description"
        )

    async def team_users(self, team_gid: str) -> list[dict[str, Any]]:
        return await self._get_all(f"/teams/{team_gid}/users", opt_fields="gid,name,email")

    async def projects(self, team_gid: str) -> list[dict[str, Any]]:
        return await self._get_all(
            f"/teams/{team_gid}/projects",
            opt_fields=(
                "gid,name,archived,color,html_notes,notes,owner,team,privacy_setting,"
                "default_view,start_on,due_on,created_at,completed"
            ),
            params={"archived": "false"},
        )

    async def sections(self, project_gid: str) -> list[dict[str, Any]]:
        return await self._get_all(f"/projects/{project_gid}/sections", opt_fields="gid,name")

    async def tasks(self, section_gid: str) -> list[dict[str, Any]]:
        return await self._get_all(
            f"/sections/{section_gid}/tasks",
            opt_fields=(
                "gid,name,html_notes,notes,resource_subtype,approval_status,assignee,"
                "assignee.email,start_on,due_on,due_at,completed,completed_at,created_at,"
                "created_by,created_by.email,parent,tags,num_subtasks"
            ),
        )

    async def subtasks(self, task_gid: str) -> list[dict[str, Any]]:
        return await self._get_all(
            f"/tasks/{task_gid}/subtasks",
            opt_fields=(
                "gid,name,html_notes,notes,resource_subtype,approval_status,assignee,"
                "assignee.email,start_on,due_on,due_at,completed,completed_at,created_at,"
                "created_by,created_by.email,parent,tags"
            ),
        )

    async def tags(self, workspace_gid: str) -> list[dict[str, Any]]:
        return await self._get_all(f"/workspaces/{workspace_gid}/tags", opt_fields="gid,name,color")
