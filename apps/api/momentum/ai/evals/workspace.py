"""Build the eval workspace (``fixtures/workspaces/<name>.yaml``) on a seeded database, through
the normal services (so activity, notifications and search columns are real). Idempotent: a
project that already exists is left alone. Returns the task titles → keys map the cases use
(``{{key:Title}}``)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai.tools.write_tools import text_doc
from momentum.core.context import Actor, Ctx
from momentum.core.ids import task_key
from momentum.core.settings import Settings
from momentum.domain.comments.service import create_comment
from momentum.domain.projects.models import Project
from momentum.domain.projects.schemas import ProjectCreateIn
from momentum.domain.projects.service import create_project
from momentum.domain.sections.service import create_section, list_sections, rename_section
from momentum.domain.tasks import service as tasks
from momentum.domain.tasks.models import Task
from momentum.domain.teams.models import Team
from momentum.domain.users.models import User

WORKSPACES = Path(__file__).parent / "fixtures" / "workspaces"


@dataclass
class EvalWorld:
    users: dict[str, User] = field(default_factory=dict)  # local part → user
    keys: dict[str, str] = field(default_factory=dict)  # task title → key
    task_ids: dict[str, uuid.UUID] = field(default_factory=dict)
    projects: dict[str, uuid.UUID] = field(default_factory=dict)

    def ctx(self, local: str, settings: Settings) -> Ctx:
        u = self.users[local]
        actor = Actor(
            id=u.id,
            workspace_id=u.workspace_id,
            name=u.name,
            email=u.email,
            role=u.role,
            timezone=u.timezone,
        )
        return Ctx(actor=actor, settings=settings)


async def _users(session: AsyncSession) -> dict[str, User]:
    rows = (await session.execute(select(User))).scalars()
    return {u.email.split("@")[0]: u for u in rows}


async def load_world(session: AsyncSession) -> EvalWorld:
    """The users, and the keys/ids of every task, for placeholders and scoring."""
    world = EvalWorld(users=await _users(session))
    for t in (await session.execute(select(Task).where(Task.deleted_at.is_(None)))).scalars():
        world.keys.setdefault(t.title, task_key(t.number))
        world.task_ids.setdefault(t.title, t.id)
    for pid, name in (await session.execute(select(Project.id, Project.name))).tuples():
        world.projects[name] = pid
    return world


async def build_workspace(
    session: AsyncSession, settings: Settings, name: str = "launch_v1"
) -> EvalWorld:
    spec: dict[str, Any] = yaml.safe_load((WORKSPACES / f"{name}.yaml").read_text(encoding="utf-8"))
    world = EvalWorld(users=await _users(session))
    for p in spec["projects"]:
        exists = (
            await session.execute(select(Project.id).where(Project.name == p["name"]))
        ).scalar_one_or_none()
        if exists is not None:
            continue
        owner = world.ctx(p["owner"], settings)
        today = datetime.now(UTC).astimezone(ZoneInfo(owner.actor.timezone)).date()
        team_id = (
            await session.execute(select(Team.id).where(Team.name == p["team"]))
        ).scalar_one()
        project = (
            await create_project(
                session,
                owner,
                ProjectCreateIn(team_id=team_id, name=p["name"], privacy=p.get("privacy", "team")),
            )
        ).entity
        (first,) = await list_sections(session, project.id)
        await rename_section(session, owner, first.id, p["sections"][0])
        sections = {p["sections"][0]: first.id}
        prev = first.id
        for sname in p["sections"][1:]:
            prev = (
                await create_section(session, owner, project.id, sname, after_id=prev)
            ).entity.id
            sections[sname] = prev
        created: dict[str, uuid.UUID] = {}
        for t in p["tasks"]:
            created[t["title"]] = await _task(
                session, settings, world, owner, project.id, sections, t, today
            )
        for t in p["tasks"]:
            for blocker in t.get("blocked_by", []):
                await tasks.add_dependency(session, owner, created[t["title"]], created[blocker])
        for t in p["tasks"]:
            if t.get("completed"):
                await tasks.set_completed(session, owner, created[t["title"]], True)
    await session.flush()
    return await load_world(session)


async def _task(
    session: AsyncSession,
    settings: Settings,
    world: EvalWorld,
    owner: Ctx,
    project_id: uuid.UUID,
    sections: dict[str, uuid.UUID],
    t: dict[str, Any],
    today: date,
) -> uuid.UUID:
    assignee = world.users[t["assignee"]].id if t.get("assignee") else None
    due = today + timedelta(days=int(t["due"])) if "due" in t else None
    task = (
        await tasks.create_task(
            session,
            owner,
            project_id,
            t["title"],
            section_id=sections[t["section"]],
            assignee_id=assignee,
            due_on=due,
        )
    ).entity[0]
    patch: dict[str, Any] = {}
    if t.get("priority"):
        patch["priority"] = t["priority"]
    if t.get("description"):
        patch["description"] = text_doc(t["description"])
    if patch:
        await tasks.update_task(session, owner, task.id, patch)
    if "pushed_to" in t:
        await tasks.update_task(
            session, owner, task.id, {"due_on": today + timedelta(days=int(t["pushed_to"]))}
        )
    for sub in t.get("subtasks", []):
        await tasks.create_subtask(session, owner, task.id, sub)
    for c in t.get("comments", []):
        await create_comment(session, world.ctx(c["by"], settings), task.id, text_doc(c["text"]))
    return task.id
