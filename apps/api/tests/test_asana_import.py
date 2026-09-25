"""S2.7.1 Asana importer: a synthetic recorded fixture drives `run_import` through a fake
`AsanaClient`-shaped object (no real network — see `integrations/asana_import/client.py`'s own
docstring for why this replaces VCR-style cassettes here), covering the mapping rules and the
idempotent-re-run AC."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from momentum.core.db import UnitOfWork
from momentum.core.settings import Settings
from momentum.domain.integrations.models import ExternalLink, ImportJob
from momentum.domain.projects.models import Project
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.teams.models import Team
from momentum.integrations.asana_import.mapping import (
    html_to_plain,
    map_approval_state,
    map_privacy,
    map_task_type,
)
from momentum.integrations.asana_import.service import run_import
from tests.helpers import Clients, ctx_for


class FakeAsanaClient:
    """A small, fixed synthetic workspace: 1 team, 2 members (1 matches a seeded user, 1
    doesn't), 1 tag, 1 project with 2 sections, 3 tasks (one with a subtask)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def team_users(self, team_gid: str) -> list[dict[str, Any]]:
        self.calls.append("team_users")
        return [
            {"gid": "u1", "name": "Ravi Kumar", "email": "ravi@acme-demo.test"},
            {"gid": "u2", "name": "Someone Else", "email": "someone@example.com"},
        ]

    async def projects(self, team_gid: str) -> list[dict[str, Any]]:
        self.calls.append("projects")
        return [
            {
                "gid": "p1",
                "name": "Imported Project",
                "archived": False,
                "privacy_setting": "private_to_team",
                "start_on": "2026-01-01",
                "due_on": None,
            }
        ]

    async def sections(self, project_gid: str) -> list[dict[str, Any]]:
        self.calls.append("sections")
        return [{"gid": "s1", "name": "To do"}, {"gid": "s2", "name": "Done"}]

    async def tasks(self, section_gid: str) -> list[dict[str, Any]]:
        self.calls.append("tasks")
        if section_gid == "s1":
            return [
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
        return [
            {
                "gid": "t3",
                "name": "Legacy separator row",
                "resource_subtype": "section",  # skipped: not a real task
            }
        ]

    async def subtasks(self, task_gid: str) -> list[dict[str, Any]]:
        self.calls.append("subtasks")
        return [{"gid": "t1-sub1", "name": "Notify support", "resource_subtype": "default_task"}]

    async def tags(self, workspace_gid: str) -> list[dict[str, Any]]:
        self.calls.append("tags")
        return [{"gid": "tag1", "name": "Urgent", "color": "red"}]


async def test_import_creates_expected_counts(
    as_user: Clients, uow: UnitOfWork, settings: Settings
) -> None:
    await as_user("ravi")  # provisions the seeded user this test's fixture email matches
    ctx = await ctx_for(uow, settings, "ravi")
    client = FakeAsanaClient()
    async with uow.transaction() as s:
        job = await run_import(
            s,
            ctx,
            client,
            workspace_gid="ws1",
            team_gid="team1",
            team_name="Imported Team",
            project_gids=None,
        )
        assert job.status == "done"
        assert job.stats == {
            "teams": 1,
            "projects": 1,
            "sections": 2,
            "tasks": 2,  # t1, t2 (t3 skipped as a legacy "section" row)
            "subtasks": 1,
            "tags": 1,
            "users_matched": 1,
            "users_unmatched": 1,
            "skipped": ["task t3: unsupported resource_subtype"],
        }

    async with uow.transaction() as s:
        team = (await s.execute(select(Team).where(Team.name == "Imported Team"))).scalar_one()
        project = (
            await s.execute(select(Project).where(Project.name == "Imported Project"))
        ).scalar_one()
        assert project.privacy == "team"
        task = (await s.execute(select(Task).where(Task.title == "Ship the release"))).scalar_one()
        assert task.assignee_id is not None
        assert "prod" in (task.description_text or "")
        placement = (
            await s.execute(select(TaskProject).where(TaskProject.task_id == task.id))
        ).scalar_one()
        assert placement.project_id == project.id
        subtask = (await s.execute(select(Task).where(Task.title == "Notify support"))).scalar_one()
        assert subtask.parent_id == task.id
        # a subtask has no placement of its own
        sub_placement = (
            await s.execute(select(TaskProject).where(TaskProject.task_id == subtask.id))
        ).scalar_one_or_none()
        assert sub_placement is None
        links = (
            await s.execute(select(ExternalLink).where(ExternalLink.provider == "asana"))
        ).scalars()
        assert {link.external_id for link in links} >= {"team1", "p1", "s1", "s2", "t1", "t2"}
        _ = team


async def test_rerunning_the_import_does_not_duplicate(
    as_user: Clients, uow: UnitOfWork, settings: Settings
) -> None:
    await as_user("ravi")
    ctx = await ctx_for(uow, settings, "ravi")
    client = FakeAsanaClient()
    async with uow.transaction() as s:
        await run_import(
            s, ctx, client, workspace_gid="ws1", team_gid="team1", team_name="Imported Team"
        )
    async with uow.transaction() as s:
        job2 = await run_import(
            s, ctx, client, workspace_gid="ws1", team_gid="team1", team_name="Imported Team"
        )
        # nothing new was created on the second pass
        assert job2.stats == {
            "teams": 0,
            "projects": 0,
            "sections": 0,
            "tasks": 0,
            "subtasks": 0,
            "tags": 0,
            "users_matched": 1,
            "users_unmatched": 1,
            "skipped": ["task t3: unsupported resource_subtype"],
        }
    async with uow.transaction() as s:
        teams = (await s.execute(select(Team).where(Team.name == "Imported Team"))).scalars().all()
        assert len(teams) == 1
        jobs = (await s.execute(select(ImportJob))).scalars().all()
        assert len(jobs) == 2  # one row per run, even though the second run created nothing new


def test_map_privacy() -> None:
    assert map_privacy("public_to_workspace") == "team"
    assert map_privacy("private_to_team") == "team"
    assert map_privacy("private") == "private"
    assert map_privacy(None) == "private"


def test_map_task_type() -> None:
    assert map_task_type("default_task") == "task"
    assert map_task_type("milestone") == "milestone"
    assert map_task_type("approval") == "approval"
    assert map_task_type("section") is None
    assert map_task_type(None) == "task"


def test_map_approval_state() -> None:
    assert map_approval_state("approved") == "approved"
    assert map_approval_state("weird_value") is None
    assert map_approval_state(None) is None


def test_html_to_plain_strips_tags_and_keeps_text() -> None:
    assert html_to_plain("<body><p>Hello <strong>world</strong>.</p></body>") == "Hello world."
    assert html_to_plain(None) == ""
