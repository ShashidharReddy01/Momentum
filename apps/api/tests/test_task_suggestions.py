"""Phase 7.5 S75-12: smart task creation (spec §9.3), no model call. Thresholds are exact on
constructed data: the assignee at 40%, the due offset with 5 neighbours, a field value and a tag
at 50%; inactive and agent assignees are never suggested; duplicates are open, visible tasks of
the project (trigram ≥ 0.6, or cosine ≥ 0.86 on the stored title embedding)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from momentum.ai.embeddings import reindex
from momentum.ai.llm import LLM
from momentum.ai.mock import MockTransport
from momentum.ai.task_suggestions import Suggestions, suggest
from momentum.ai.usage import NullUsageLog
from momentum.core.context import Ctx
from momentum.core.db import UnitOfWork
from momentum.core.settings import Settings
from momentum.domain.fields.schemas import FieldCreateIn, SelectOptionIn
from momentum.domain.fields.service import create_field, set_task_field_value
from momentum.domain.projects.schemas import ProjectCreateIn
from momentum.domain.projects.service import create_project
from momentum.domain.tags.schemas import TagCreateIn
from momentum.domain.tags.service import add_task_tag, create_tag
from momentum.domain.tasks import service as tasks
from momentum.domain.tasks.models import Task
from momentum.domain.tasks.service import today_for
from momentum.domain.teams.models import Team
from momentum.domain.users.models import User
from tests.helpers import Clients, ctx_for, user_by_local

TITLE = "Draft the launch newsletter"


@pytest.fixture
async def llm(settings: Settings) -> AsyncIterator[LLM]:
    gateway = LLM(settings, MockTransport(settings), NullUsageLog())
    yield gateway
    await gateway.aclose()


async def _project(uow: UnitOfWork, ctx: Ctx, name: str, privacy: str = "team") -> uuid.UUID:
    async with uow.transaction() as s:
        team = (await s.execute(select(Team).where(Team.name == "Product"))).scalar_one()
        p = await create_project(
            s, ctx, ProjectCreateIn(team_id=team.id, name=name, privacy=privacy)
        )
        return p.entity.id


async def _ask(
    uow: UnitOfWork, ctx: Ctx, pid: uuid.UUID, title: str = TITLE, llm: LLM | None = None
) -> Suggestions:
    async with uow.transaction() as s:
        return await suggest(s, llm, ctx, pid, title)


async def _ten(
    uow: UnitOfWork, ctx: Ctx, pid: uuid.UUID, assignees: list[uuid.UUID | None]
) -> list[uuid.UUID]:
    """Ten similar tasks: the given assignees, five with a due date 2..6 days after creation."""
    ids = []
    async with uow.transaction() as s:
        today = today_for(ctx)
        for i, who in enumerate(assignees):
            t, _ = (
                await tasks.create_task(s, ctx, pid, f"{TITLE} part {i + 1}", assignee_id=who)
            ).entity
            if i < 5:
                await tasks.update_task(s, ctx, t.id, {"due_on": today + timedelta(days=i + 2)})
            ids.append(t.id)
    return ids


async def test_thresholds_are_exact(uow: UnitOfWork, settings: Settings, seeded: None) -> None:
    ravi = await ctx_for(uow, settings, "ravi")
    mei = (await user_by_local(uow, "mei")).id
    ana = (await user_by_local(uow, "ana")).id
    pid = await _project(uow, ravi, "Newsletter Lab")
    # 4 of 10 (40%) to Mei: suggested
    ids = await _ten(uow, ravi, pid, [mei] * 4 + [ana] * 3 + [None] * 3)
    async with uow.transaction() as s:
        launch = (await create_tag(s, ravi, TagCreateIn(name="Launch"))).entity
        press = (await create_tag(s, ravi, TagCreateIn(name="Press"))).entity
        for t in ids[:5]:
            await add_task_tag(s, ravi, t, launch.id, None)  # 5 of 10: suggested
        for t in ids[:4]:
            await add_task_tag(s, ravi, t, press.id, None)  # 4 of 10: not
        risk = (
            await create_field(
                s,
                ravi,
                pid,
                FieldCreateIn(
                    name="Risk",
                    type="single_select",
                    options=[SelectOptionIn(label="High"), SelectOptionIn(label="Low")],
                ),
            )
        ).entity
        high = next(o["id"] for o in risk.options if o["label"] == "High")
        for t in ids[5:]:
            await set_task_field_value(s, ravi, t, risk.id, high)  # 5 of 10: suggested

    out = await _ask(uow, ravi, pid)
    assert out.enabled and out.neighbours == 10
    who = next(x for x in out.suggestions if x.kind == "assignee")
    assert who.value == str(mei) and who.reason.startswith("4 of 10 similar tasks were assigned to")
    due = next(x for x in out.suggestions if x.kind == "due")
    assert due.days == 4  # median of 2..6
    assert due.value == (today_for(ravi) + timedelta(days=4)).isoformat()
    assert [x.label for x in out.suggestions if x.kind == "tag"] == ["Launch"]
    field = next(x for x in out.suggestions if x.kind == "field")
    assert field.label == "Risk: High" and field.value == high and field.field_id == risk.id
    assert field.reason == "5 of 10 similar tasks had Risk High"

    # one below each line: 3 of 10 assigned, 4 due dates, 4 tags, 4 field values
    pid2 = await _project(uow, ravi, "Newsletter Lab 2")
    ids2 = await _ten(uow, ravi, pid2, [mei] * 3 + [ana] * 2 + [None] * 5)
    async with uow.transaction() as s:
        await tasks.update_task(s, ravi, ids2[0], {"due_on": None})
    out2 = await _ask(uow, ravi, pid2)
    assert {x.kind for x in out2.suggestions} == set()


async def test_inactive_and_agent_assignees_are_never_suggested(
    uow: UnitOfWork, settings: Settings, seeded: None
) -> None:
    ravi = await ctx_for(uow, settings, "ravi")
    mei = (await user_by_local(uow, "mei")).id
    pid = await _project(uow, ravi, "Assignee Lab")
    await _ten(uow, ravi, pid, [mei] * 8 + [None] * 2)
    assert any(x.kind == "assignee" for x in (await _ask(uow, ravi, pid)).suggestions)
    async with uow.transaction() as s:
        await s.execute(update(User).where(User.id == mei).values(status="disabled"))
    assert not any(x.kind == "assignee" for x in (await _ask(uow, ravi, pid)).suggestions)
    async with uow.transaction() as s:
        await s.execute(update(User).where(User.id == mei).values(status="active", is_agent=True))
    assert not any(x.kind == "assignee" for x in (await _ask(uow, ravi, pid)).suggestions)
    async with uow.transaction() as s:
        await s.execute(update(User).where(User.id == mei).values(is_agent=False))


async def test_duplicates_are_open_visible_tasks_of_the_project(
    uow: UnitOfWork, settings: Settings, seeded: None, llm: LLM
) -> None:
    ravi = await ctx_for(uow, settings, "ravi")
    priya = await ctx_for(uow, settings, "priya")
    pid = await _project(uow, ravi, "Duplicate Lab")
    secret = await _project(uow, priya, "Duplicate Secrets", privacy="private")
    async with uow.transaction() as s:
        open_t, _ = (await tasks.create_task(s, ravi, pid, "Prepare the press kit")).entity
        done_t, _ = (await tasks.create_task(s, ravi, pid, "Prepare the press kits")).entity
        await tasks.set_completed(s, ravi, done_t.id, True)
        await tasks.create_task(s, ravi, pid, "Book the venue")
        tidy, _ = (
            await tasks.create_task(s, ravi, pid, "Booked rooms painted walls cleaned windows")
        ).entity
        await tasks.create_task(s, priya, secret, "Prepare the press kit (confidential)")
    out = await _ask(uow, ravi, pid, "Prepare the press kit")
    assert [d.key for d in out.duplicates] == [f"T-{open_t.number}"]  # not the completed one
    assert out.duplicates[0].score == 1.0 and out.duplicates[0].title == "Prepare the press kit"
    assert all("confidential" not in d.title for d in out.duplicates)
    # trigram alone stays under 0.6 for a reworded title; the title embedding still finds it
    reworded = "Book room paint wall clean window"  # the same stems, other word forms
    async with uow.transaction() as s:
        tri = (
            await s.execute(
                select(func.similarity(Task.title, reworded)).where(Task.id == open_t.id)
            )
        ).scalar_one()
        assert tri < 0.6
        await reindex(s, llm, entity_types=["task"])
    assert (await _ask(uow, ravi, pid, reworded)).duplicates == []
    found = await _ask(uow, ravi, pid, reworded, llm=llm)
    assert [d.id for d in found.duplicates] == [tidy.id]
    assert found.duplicates[0].score >= 0.86
    # someone who can't see the project gets nothing at all
    with pytest.raises(Exception):
        await _ask(uow, ravi, secret, "Prepare the press kit")


async def test_off_by_setting_or_preference_and_short_titles(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = next(
        p["id"]
        for p in (await ravi.get("/api/v1/projects")).json()["data"]
        if p["name"] == "Website Revamp"
    )
    url = "/api/v1/ai/task-suggestions"
    short = (await ravi.post(url, json={"project_id": pid, "title": "Fix it"})).json()
    assert short["enabled"] is True and short["suggestions"] == [] and short["neighbours"] == 0
    r = await ravi.put(
        "/api/v1/ai/prefs", json={"auto_apply_low_risk": False, "task_suggestions": False}
    )
    assert r.status_code == 200, r.text
    off = (await ravi.post(url, json={"project_id": pid, "title": "Write the hero copy"})).json()
    assert off["enabled"] is False and off["duplicates"] == []
