"""Phase 7.5 S75-11: plain-English filters on the task surfaces (spec §9.2). The draft is in each
surface's own schema (a project view's preferences, search params, My Tasks); names resolve among
what the viewer can see, and anything unresolvable or unsupported is asked back with the real
options; relative dates resolve in the viewer's timezone."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import httpx
import time_machine

from momentum.ai.nl_filters import FieldCondDraft
from momentum.ai.nl_filters_tasks import TaskFilterDraft, resolve_task_draft
from momentum.core.context import Ctx
from momentum.core.db import UnitOfWork
from momentum.core.settings import Settings
from momentum.domain.fields.service import list_project_fields
from tests.helpers import Clients, ctx_for

B = "/api/v1"


async def _project(c: httpx.AsyncClient, name: str = "Website Revamp") -> str:
    return next(p["id"] for p in (await c.get(f"{B}/projects")).json()["data"] if p["name"] == name)


async def _draft(c: httpx.AsyncClient, text: str, surface: str, **ids: Any) -> dict[str, Any]:
    r = await c.post(f"{B}/ai/filters", json={"text": text, "surface": surface, **ids})
    assert r.status_code == 200, r.text
    return dict(r.json())


async def test_a_project_view_draft_is_its_own_preferences(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    tag = (await ravi.post(f"{B}/tags", json={"name": "Escalated"})).json()["data"]
    d = await _draft(ravi, "My overdue tasks tagged escalated", "list", project_id=pid)
    assert d["question"] is None
    assert d["filters"] == {"assignees": ["me"], "tags": [tag["id"]], "due": "overdue"}
    assert [c["label"] for c in d["chips"]] == ["Assignee: me", "Tags: Escalated", "Overdue"]
    # Apply = saving the view's preferences: the server takes the draft as it is
    put = await ravi.put(f"{B}/me/prefs/views/{pid}", json=d["filters"])
    assert put.status_code == 200, put.text

    board = await _draft(
        ravi,
        "Everything including done, sorted by due date, grouped by person",
        "board",
        project_id=pid,
    )
    assert board["filters"] == {"show_completed": True, "sort": "due", "group": "assignee"}
    # a project view needs its project
    no_project = await ravi.post(f"{B}/ai/filters", json={"text": "x", "surface": "calendar"})
    assert no_project.status_code == 422


async def test_unresolvable_or_unsupported_is_asked_back_with_real_options(
    as_user: Clients,
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    await ravi.post(f"{B}/tags", json={"name": "Escalated"})
    tag = await _draft(ravi, "Tasks tagged urgent-ish", "list", project_id=pid)
    assert "urgent-ish" in tag["question"] and "Escalated" in tag["options"]
    words = await _draft(ravi, "Anything that mentions DataCo", "list", project_id=pid)
    assert "Search" in words["question"] and words["filters"] == {}
    due = await _draft(ravi, "Only my overdue ones", "my_tasks")
    assert "My Tasks" in due["question"]
    # a project the viewer can't see is never named back
    hidden = await _draft(ravi, "Search ideas in Secret Roadmap", "search")
    assert hidden["question"] and "Zenith" not in str(hidden)


async def test_search_draft_is_the_search_params(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    d = await _draft(ravi, "Finished tasks and comments about pricing", "search")
    assert d["filters"] == {"completed": True, "q": "pricing", "type": ["task", "comment"]}
    r = await ravi.get(
        f"{B}/search", params={"q": "pricing", "completed": "true", "type": "task,comment"}
    )
    assert r.status_code == 200


async def test_relative_dates_resolve_in_the_viewers_timezone(
    uow: UnitOfWork, settings: Settings, as_user: Clients
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    r = await ravi.post(f"{B}/projects/{pid}/fields", json={"name": "Launch day", "type": "date"})
    assert r.status_code == 201, r.text
    base = await ctx_for(uow, settings, "ravi")
    kolkata = Ctx(actor=replace(base.actor, timezone="Asia/Kolkata"), settings=settings)
    draft = TaskFilterDraft(
        fields=[FieldCondDraft(field="Launch day", on_or_after="today", on_or_before="today+6")]
    )
    # 23:30 UTC on 31 October is already 1 November in Kolkata
    with time_machine.travel(datetime(2026, 10, 31, 23, 30, tzinfo=UTC), tick=False):
        async with uow.transaction() as s:
            defs = [f for _pf, f in await list_project_fields(s, kolkata, uuid.UUID(pid))]
            out = await resolve_task_draft(s, kolkata, "list", draft, defs, uuid.UUID(pid))
    fid = next(f.id for f in defs if f.name == "Launch day")
    assert sorted(out.filters["fields"]) == sorted(
        [f"{fid}:min:2026-11-01", f"{fid}:max:2026-11-07"]
    )
    assert out.named["fields"] == [
        {"field": "Launch day", "on_or_after": "today", "on_or_before": "today+6"}
    ]
