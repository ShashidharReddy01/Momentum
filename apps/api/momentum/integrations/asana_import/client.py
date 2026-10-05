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
# everything the importer reads from a task, in one listing call (S7.4.2)
TASK_FIELDS = (
    "gid,name,html_notes,notes,resource_subtype,approval_status,assignee.email,start_on,"
    "due_on,due_at,completed,completed_at,created_at,created_by.email,parent,tags,num_subtasks,"
    "followers.email,dependencies,memberships.project.gid,memberships.section.gid,permalink_url,"
    "likes.user.email,custom_fields.gid,custom_fields.resource_subtype,custom_fields.text_value,"
    "custom_fields.number_value,custom_fields.enum_value.gid,custom_fields.multi_enum_values.gid,"
    "custom_fields.date_value.date,custom_fields.date_value.date_time,"
    "custom_fields.people_value.email,custom_fields.display_value"
)
PAGE_LIMIT = 100
MAX_RETRIES = 5


class AsanaClient:
    def __init__(
        self, pat: str, *, base_url: str = BASE_URL, http: httpx.AsyncClient | None = None
    ) -> None:
        # The PAT lives only in this instance's memory for the lifetime of one import request —
        # never written to the database, a log, or a job queue (see `service.py`'s docstring for
        # why this importer runs synchronously rather than as a background job).
        self._http = http or httpx.AsyncClient(
            base_url=base_url,
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

    async def projects(self, team_gid: str, include_archived: bool = True) -> list[dict[str, Any]]:
        """A team's projects; archived ones too by default (they import archived)."""
        return await self._get_all(
            f"/teams/{team_gid}/projects",
            opt_fields=(
                "gid,name,archived,color,html_notes,notes,owner.email,team,privacy_setting,"
                "default_view,start_on,due_on,created_at,completed,permalink_url"
            ),
            params={} if include_archived else {"archived": "false"},
        )

    async def sections(self, project_gid: str) -> list[dict[str, Any]]:
        return await self._get_all(f"/projects/{project_gid}/sections", opt_fields="gid,name")

    async def tasks(self, section_gid: str) -> list[dict[str, Any]]:
        return await self._get_all(f"/sections/{section_gid}/tasks", opt_fields=TASK_FIELDS)

    async def subtasks(self, task_gid: str) -> list[dict[str, Any]]:
        return await self._get_all(f"/tasks/{task_gid}/subtasks", opt_fields=TASK_FIELDS)

    # ---- S7.4.2: the full import ----

    async def workspace_users(self, workspace_gid: str) -> list[dict[str, Any]]:
        """Everyone in the workspace (assignees, followers and authors can be outside the team)."""
        return await self._get_all(
            f"/workspaces/{workspace_gid}/users", opt_fields="gid,name,email"
        )

    async def custom_field_settings(self, project_gid: str) -> list[dict[str, Any]]:
        return await self._get_all(
            f"/projects/{project_gid}/custom_field_settings",
            opt_fields=(
                "custom_field.gid,custom_field.name,custom_field.resource_subtype,"
                "custom_field.description,custom_field.precision,custom_field.format,"
                "custom_field.currency_code,custom_field.is_global_to_workspace,"
                "custom_field.enum_options.gid,custom_field.enum_options.name,"
                "custom_field.enum_options.color,custom_field.enum_options.enabled"
            ),
        )

    async def stories(self, task_gid: str) -> list[dict[str, Any]]:
        return await self._get_all(
            f"/tasks/{task_gid}/stories",
            opt_fields=(
                "gid,resource_subtype,type,text,html_text,created_at,created_by.email,"
                "created_by.name,likes.user.email"
            ),
        )

    async def attachments(self, task_gid: str) -> list[dict[str, Any]]:
        return await self._get_all(
            "/attachments",
            opt_fields="gid,name,host,download_url,view_url,permanent_url,size,created_at",
            params={"parent": task_gid},
        )

    async def status_updates(self, project_gid: str) -> list[dict[str, Any]]:
        return await self._get_all(
            "/status_updates",
            opt_fields="gid,status_type,title,text,html_text,created_at,created_by.email",
            params={"parent": project_gid},
        )

    async def download(self, url: str, max_bytes: int) -> bytes | None:
        """An attachment's short-lived download URL (pre-signed: no token is sent with it), or
        None when it's larger than ``max_bytes``."""
        async with (
            httpx.AsyncClient(timeout=60.0, follow_redirects=True) as plain,
            plain.stream("GET", url) as resp,
        ):
            resp.raise_for_status()
            chunks: list[bytes] = []
            size = 0
            async for chunk in resp.aiter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    return None
                chunks.append(chunk)
            return b"".join(chunks)

    async def tags(self, workspace_gid: str) -> list[dict[str, Any]]:
        return await self._get_all(f"/workspaces/{workspace_gid}/tags", opt_fields="gid,name,color")
