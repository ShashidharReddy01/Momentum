"""S3.4.2 break into subtasks: a previewed AI action (nothing created until applied), assignees
from the project's people only, dates and duplicates corrected with notes, apply + undo, and
permissions."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from momentum.ai.actions import apply_action
from momentum.ai.breakdown import BreakdownResult, break_down, project_people
from momentum.ai.llm import build_llm
from momentum.ai.models import AiAction
from momentum.core.context import Ctx
from momentum.core.db import UnitOfWork
from momentum.core.errors import Forbidden, NotFound
from momentum.domain.projects.models import Project
from momentum.domain.tasks import service as tasks
from momentum.domain.tasks.models import Task
from tests.ai_fixtures import REG, World, undo_batch, world
from tests.conftest import make_settings
from tests.helpers import Clients, user_by_local

_ = world
NOW = datetime(2026, 9, 26, 9, 0, tzinfo=UTC)


async def run(
    uow: UnitOfWork, ctx: Ctx, task_id: uuid.UUID, hint: str | None = None
) -> BreakdownResult:
    llm = build_llm(make_settings())
    async with uow.transaction() as s:
        return await break_down(s, llm, ctx.with_(via="ai"), REG, task_id, hint=hint, now=NOW)


async def subtasks(uow: UnitOfWork, parent_id: uuid.UUID) -> list[Task]:
    async with uow.transaction() as s:
        return list(
            (
                await s.execute(
                    select(Task)
                    .where(Task.parent_id == parent_id, Task.deleted_at.is_(None))
                    .order_by(Task.parent_position)
                )
            ).scalars()
        )


async def test_preview_then_apply_then_undo(uow: UnitOfWork, world: World) -> None:
    copy_id = world.copy.id
    r = await run(uow, world.ravi, copy_id)
    assert r.count == 3 and r.notes == []
    assert await subtasks(uow, copy_id) == []  # a preview only
    async with uow.transaction() as s:
        action = await s.get(AiAction, r.action_id)
        assert action is not None and action.source == "inline" and action.source_id == copy_id
        assert action.summary.startswith("Break T-") and action.risk == "low"
    async with uow.transaction() as s:
        assert r.action_id is not None
        applied = await apply_action(s, world.ravi, REG, r.action_id)
    subs = await subtasks(uow, copy_id)
    ana = await user_by_local(uow, "ana")
    assert [t.title for t in subs] == [
        "(mock) Gather what's needed",
        "(mock) Do the main work",
        "(mock) Review and wrap up",
    ]
    assert subs[0].assignee_id == ana.id and subs[0].created_via == "ai"
    await undo_batch(uow, world.ravi, applied.action.applied_batch_id)
    assert await subtasks(uow, copy_id) == []


async def test_output_is_checked_not_trusted(uow: UnitOfWork, world: World) -> None:
    copy_id = world.copy.id
    async with uow.transaction() as s:
        await tasks.update_task(s, world.ravi, copy_id, {"due_on": date(2030, 1, 1)})
        await tasks.create_subtask(s, world.ravi, copy_id, "Collect competitor prices")
    r = await run(uow, world.ravi, copy_id, hint="test every correction")
    async with uow.transaction() as s:
        action = await s.get(AiAction, r.action_id)
        assert action is not None
        (op,) = action.operations
    items = op["args"]["subtasks"]
    ana = await user_by_local(uow, "ana")
    assert [i["title"] for i in items] == [
        "Draft the copy",
        "Check with an outsider",
        "Ask a viewer",
        "Ask someone unknown",
        "Review with legal",
        "Ship after the deadline",
        "Publish the page",
    ]
    by_title = {i["title"]: i for i in items}
    assert by_title["Draft the copy"]["assignee"] == str(ana.id)  # first name, on the project
    for t in ("Check with an outsider", "Ask a viewer", "Ask someone unknown"):
        assert "assignee" not in by_title[t]  # tom: other team; lena: viewer; unknown
    assert "due_on" not in by_title["Review with legal"]  # past
    assert "due_on" not in by_title["Ship after the deadline"]  # after the parent's due date
    assert by_title["Publish the page"]["due_on"] == "2029-12-01"
    text = "\n".join(r.notes)
    assert "Skipped “Collect competitor prices”" in text  # already a subtask
    assert "Skipped “draft the COPY”" in text  # listed twice
    assert "Tom Becker isn't someone on this project" in text
    assert "Lena Novak isn't someone on this project" in text
    assert "Nobody Atall" in text
    assert "in the past (2020-01-01)" in text and "(2031-01-01)" in text


async def test_project_people(uow: UnitOfWork, world: World) -> None:
    async with uow.transaction() as s:
        project = await s.get(Project, world.project.id)
        secret = await s.get(Project, world.secret.id)
        assert project is not None and secret is not None
        names = {u.name for u in await project_people(s, project)}
        secret_names = {u.name for u in await project_people(s, secret)}
    assert {"Ravi Kumar", "Ana Souza"} <= names
    assert "Tom Becker" not in names and "Lena Novak" not in names
    assert secret_names == {"Priya Nair"}  # private: explicit members only


async def test_permissions(uow: UnitOfWork, world: World) -> None:
    copy_id, hidden_id = world.copy.id, world.hidden.id
    with pytest.raises(Forbidden):
        await run(uow, world.lena, copy_id)  # viewer
    with pytest.raises(NotFound):
        await run(uow, world.ravi, hidden_id)  # private to priya


async def test_endpoint(as_user: Clients, world: World) -> None:
    ravi = await as_user("ravi")
    r = await ravi.post(f"/api/v1/ai/tasks/{world.copy.id}/subtasks", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 3 and body["notes"] == []
    got = await ravi.get(f"/api/v1/ai/actions/{body['action_id']}")
    assert got.json()["data"]["operations"][0]["tool"] == "create_subtasks"
    lena = await as_user("lena")
    assert (
        await lena.post(f"/api/v1/ai/tasks/{world.copy.id}/subtasks", json={})
    ).status_code == 403


async def test_an_explicit_viewer_is_not_assignable_even_on_the_team(
    uow: UnitOfWork, world: World
) -> None:
    from momentum.domain.projects.service import add_member

    ana = await user_by_local(uow, "ana")  # a Product team member (editor by default)
    async with uow.transaction() as s:
        await add_member(s, world.ravi, world.project.id, ana.id, "viewer")
        project = await s.get(Project, world.project.id)
        assert project is not None
        names = {u.name for u in await project_people(s, project)}
    assert "Ana Souza" not in names and "Ravi Kumar" in names


def test_ambiguous_names_are_never_guessed() -> None:
    from momentum.ai.breakdown import match_person
    from momentum.domain.users.models import User

    ana = User(name="Ana Souza", email="ana@x.test")
    ana2 = User(name="Ana Lima", email="ana.lima@x.test")
    tom = User(name="Tom Becker", email="tom@x.test")
    people = [ana, ana2, tom]
    assert match_person("Ana", people) is None
    assert match_person("Ana Lima", people) is ana2
    assert match_person("@tom", people) is tom
    assert match_person("ANA@X.TEST", people) is ana
    assert match_person("  ", people) is None
