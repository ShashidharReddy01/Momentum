"""Shared data for the AI tests: a fresh project with two similarly named tasks, a viewer, an
outsider and a private project (Phase 1/2 retros: journey-scoped data, two candidates)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import func, select

from momentum.ai.tools.catalog import build_registry
from momentum.ai.tools.registry import ToolOutcome, ToolRegistry
from momentum.core.activity import Activity
from momentum.core.context import Ctx
from momentum.core.db import UnitOfWork
from momentum.core.events import OutboxEvent
from momentum.core.ids import task_key
from momentum.core.settings import Settings
from momentum.core.undo import undo
from momentum.domain.comments.models import Comment
from momentum.domain.notifications.models import Notification
from momentum.domain.projects.models import Project
from momentum.domain.projects.schemas import ProjectCreateIn
from momentum.domain.projects.service import add_member, create_project
from momentum.domain.sections.models import Section
from momentum.domain.sections.service import create_section, list_sections
from momentum.domain.tasks import service as tasks
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.teams.models import Team
from momentum.domain.workspace.models import Workspace
from tests.helpers import ctx_for, user_by_local

REG = build_registry()


@dataclass
class World:
    ravi: Ctx  # project admin (owner)
    ana: Ctx  # Product team member → editor on the team project
    lena: Ctx  # explicit viewer on the project
    tom: Ctx  # other team only: can't see the project at all
    priya: Ctx
    project: Project
    backlog: Section
    doing: Section
    other: Project  # a second visible project (for cross-project moves)
    secret: Project  # priya's private project
    copy: Task  # "Draft pricing copy"
    faq: Task  # "Draft pricing FAQ" (a second candidate for "pricing")
    hidden: Task  # in the private project


async def _team(uow: UnitOfWork, name: str) -> Team:
    async with uow.transaction() as s:
        return (await s.execute(select(Team).where(Team.name == name))).scalar_one()


@pytest.fixture
async def world(uow: UnitOfWork, settings: Settings, seeded: None) -> World:
    ravi = await ctx_for(uow, settings, "ravi")
    ana = await ctx_for(uow, settings, "ana")
    lena = await ctx_for(uow, settings, "lena")
    tom = await ctx_for(uow, settings, "tom")
    priya = await ctx_for(uow, settings, "priya")
    product = await _team(uow, "Product")
    async with uow.transaction() as s:
        project = (
            await create_project(s, ravi, ProjectCreateIn(team_id=product.id, name="AI Tools Lab"))
        ).entity
        other = (
            await create_project(s, ravi, ProjectCreateIn(team_id=product.id, name="Side Quest"))
        ).entity
        secret = (
            await create_project(
                s,
                priya,
                ProjectCreateIn(team_id=product.id, name="Secret Plans", privacy="private"),
            )
        ).entity
        (backlog,) = await list_sections(s, project.id)
        doing = (await create_section(s, ravi, project.id, "Doing", after_id=backlog.id)).entity
        lena_user = await user_by_local(uow, "lena")
        await add_member(s, ravi, project.id, lena_user.id, "viewer")
        copy = (await tasks.create_task(s, ravi, project.id, "Draft pricing copy")).entity[0]
        faq = (await tasks.create_task(s, ravi, project.id, "Draft pricing FAQ")).entity[0]
        hidden = (await tasks.create_task(s, priya, secret.id, "Draft pricing secret")).entity[0]
    return World(
        ravi, ana, lena, tom, priya, project, backlog, doing, other, secret, copy, faq, hidden
    )


async def call(
    uow: UnitOfWork,
    ctx: Ctx,
    name: str,
    args: dict[str, Any] | str,
    mode: str = "dry_run",
    registry: ToolRegistry = REG,
) -> ToolOutcome:
    async with uow.transaction() as s:
        return await registry.invoke(s, ctx, name, args, mode=mode)  # type: ignore[arg-type]


async def state(uow: UnitOfWork) -> dict[str, Any]:
    """Everything a write tool could touch, for "a preview changed nothing" assertions."""
    async with uow.transaction() as s:

        async def rows(stmt: Any) -> list[tuple[Any, ...]]:
            return sorted((tuple(r) for r in (await s.execute(stmt)).all()), key=str)

        async def count(model: Any) -> int:
            return int((await s.execute(select(func.count()).select_from(model))).scalar_one())

        return {
            "tasks": await rows(
                select(
                    Task.id,
                    Task.title,
                    Task.assignee_id,
                    Task.start_on,
                    Task.due_on,
                    Task.completed_at,
                    Task.deleted_at,
                    Task.description_text,
                    Task.version,
                    Task.parent_id,
                )
            ),
            "placements": await rows(
                select(TaskProject.task_id, TaskProject.project_id, TaskProject.section_id)
            ),
            "sections": await rows(select(Section.id, Section.name, Section.deleted_at)),
            "projects": await rows(select(Project.id, Project.name, Project.deleted_at)),
            "task_seq": (await s.execute(select(Workspace.task_seq))).scalar_one(),
            "comments": await count(Comment),
            "activity": await count(Activity),
            "outbox": await count(OutboxEvent),
            "notifications": await count(Notification),
        }


async def task_row(uow: UnitOfWork, task_id: uuid.UUID) -> Task:
    async with uow.transaction() as s:
        t = await s.get(Task, task_id)
        assert t is not None
        await s.refresh(t)
        return t


async def undo_batch(uow: UnitOfWork, ctx: Ctx, batch_id: uuid.UUID | None) -> None:
    assert batch_id is not None
    async with uow.transaction() as s:
        await undo(s, ctx, batch_id=batch_id)


async def batch_rows(uow: UnitOfWork, batch_id: uuid.UUID | None) -> list[Activity]:
    async with uow.transaction() as s:
        return list(
            (await s.execute(select(Activity).where(Activity.batch_id == batch_id))).scalars()
        )


def key(t: Task) -> str:
    return task_key(t.number)
