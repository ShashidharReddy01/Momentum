"""S7.4.2 full Asana import (built on S2.7.1): the synthetic workspace in
``integrations/asana_import/fixture.py`` drives the engine. A full import creates exactly what the
fixture says it must (with authors, dates, rich text, fields, followers, likes, dependencies,
comments, files and status updates kept); a dry run writes nothing and reports the same counts
plus what can't be mapped; a re-run duplicates nothing; and an import cut into one-item steps ends
up identical to one run in a single go."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import func, select

from momentum.core.db import UnitOfWork
from momentum.core.settings import Settings
from momentum.core.storage import LocalStorageBackend
from momentum.domain.attachments.models import Attachment
from momentum.domain.comments.models import Comment, Reaction
from momentum.domain.fields.models import FieldDef, FieldValue, ProjectField
from momentum.domain.integrations.models import ExternalLink, ImportJob
from momentum.domain.projects.models import Project
from momentum.domain.status_updates.models import StatusUpdate
from momentum.domain.tasks.models import Follower, Task, TaskDependency, TaskProject
from momentum.domain.teams.models import Team
from momentum.domain.users.models import User
from momentum.integrations.asana_import.engine import new_job, run_step
from momentum.integrations.asana_import.fixture import FILE_BYTES, FakeAsana
from momentum.integrations.asana_import.mapping import (
    map_approval_state,
    map_privacy,
    map_task_type,
)
from momentum.integrations.asana_import.service import run_import
from tests.helpers import Clients, ctx_for

EXPECTED = {
    "teams": 1,
    "users_matched": 1,
    "users_invited": 1,
    "users_unmatched": 1,
    "tags": 1,
    "projects": 3,
    "custom_fields": 8,
    "sections": 4,
    "tasks": 5,  # t1, t2, t5, t4, t6 (t1 again in p2 is a second placement; t3 is skipped)
    "subtasks": 2,
    "milestones": 1,
    "approvals": 1,
    "placements": 1,
    "comments": 2,
    "attachments": 1,
    "attachment_links": 1,
    "status_updates": 2,
    "dependencies": 2,  # t1 → t2, sub1 → t1 (t4 → t-elsewhere is outside the import)
    "field_values": 9,
}


async def _run(uow: UnitOfWork, settings: Settings, tmp_path: Any, **kw: Any) -> ImportJob:
    ctx = await ctx_for(uow, settings, "ravi")
    async with uow.transaction() as s:
        return await run_import(
            s,
            ctx,
            FakeAsana(),
            workspace_gid="ws1",
            team_gid="team1",
            team_name="Imported Team",
            storage=LocalStorageBackend(str(tmp_path)),
            **kw,
        )


def _counts(stats: dict[str, Any]) -> dict[str, Any]:
    return {k: stats.get(k, 0) for k in EXPECTED}


async def test_a_full_import_keeps_everything(
    as_user: Clients, uow: UnitOfWork, settings: Settings, tmp_path: Any
) -> None:
    await as_user("ravi")
    job = await _run(uow, settings, tmp_path)
    assert job.status == "done" and job.stats is not None
    assert _counts(job.stats) == EXPECTED
    assert job.stats["skipped_items"] == [
        "person Ex Colleague: no email visible to the token",
        "task t3: a legacy section row, not a task",
        "dependency t4 → t-elsewhere: the other task isn't imported",
    ]
    assert job.stats["unmapped"] == {"formula fields imported as a text snapshot": 1}

    async with uow.transaction() as s:
        one = lambda q: s.execute(q)  # noqa: E731
        project = (
            await one(select(Project).where(Project.name == "Imported Project"))
        ).scalar_one()
        assert (project.privacy, project.color, project.default_view, project.status) == (
            "team",
            "proj-4",
            "board",
            "at_risk",  # the newer of its two status updates
        )
        assert "launch" in (project.brief_text or "")
        old = (await one(select(Project).where(Project.name == "Old Project"))).scalar_one()
        assert old.archived_at is not None

        release = (await one(select(Task).where(Task.title == "Ship the release"))).scalar_one()
        assert release.created_at.isoformat().startswith("2025-11-02")
        assert release.created_via == "import"
        doc = release.description or {}
        assert [n["type"] for n in doc["content"]] == ["paragraph", "bulletList"]
        assert doc["content"][0]["content"][1]["marks"] == [{"type": "bold"}]
        placed = (
            await one(select(TaskProject.project_id).where(TaskProject.task_id == release.id))
        ).scalars()
        assert len(set(placed)) == 2  # in both projects, once
        followers = (
            await one(
                select(func.count()).select_from(Follower).where(Follower.task_id == release.id)
            )
        ).scalar_one()
        assert followers == 2
        likes = (
            await one(
                select(func.count()).select_from(Reaction).where(Reaction.entity_id == release.id)
            )
        ).scalar_one()
        assert likes == 1

        values = {
            fd.name: fv.value
            for fv, fd in (
                await one(
                    select(FieldValue, FieldDef)
                    .join(FieldDef, FieldDef.id == FieldValue.field_id)
                    .where(FieldValue.task_id == release.id)
                )
            ).all()
        }
        ravi = (await one(select(User).where(User.email == "ravi@acme-demo.test"))).scalar_one()
        assert values == {
            "Stage": "aopt-ship",
            "Areas": ["aopt-ui", "aopt-api"],
            "Points": 5,
            "Budget": 1200.5,
            "Launch": "2026-03-01",
            "Owners": [str(ravi.id)],
            "Notes": "Go/no-go on Monday",
            "Progress": "42%",
        }
        stage = (await one(select(FieldDef).where(FieldDef.name == "Stage"))).scalar_one()
        assert [o["label"] for o in stage.options] == ["Plan", "Ship", "Retired"]
        assert stage.options[2]["archived"] is True
        budget = (await one(select(FieldDef).where(FieldDef.name == "Budget"))).scalar_one()
        assert (budget.type, budget.options) == ("currency", {"precision": 2, "unit": "EUR"})
        shared = (
            await one(
                select(func.count())
                .select_from(ProjectField)
                .where(ProjectField.field_id == stage.id)
            )
        ).scalar_one()
        assert shared == 2  # one field, attached to both projects that use it

        sub = (await one(select(Task).where(Task.title == "Notify support"))).scalar_one()
        subsub = (await one(select(Task).where(Task.title == "Draft the note"))).scalar_one()
        assert (sub.parent_id, subsub.parent_id) == (release.id, sub.id)
        deps = {(d.task_id, d.depends_on_id) for d in (await one(select(TaskDependency))).scalars()}
        milestone = (await one(select(Task).where(Task.title == "Kickoff milestone"))).scalar_one()
        assert {(release.id, milestone.id), (sub.id, release.id)} <= deps
        approval = (await one(select(Task).where(Task.title == "Approve the budget"))).scalar_one()
        assert (approval.type, approval.approval_state) == ("approval", "approved")

        newcomer = (
            await one(select(User).where(User.email == "nia.newcomer@example.com"))
        ).scalar_one()
        assert newcomer.status == "invited" and approval.assignee_id == newcomer.id

        comments = (
            (
                await one(
                    select(Comment)
                    .where(Comment.task_id == release.id)
                    .order_by(Comment.created_at)
                )
            )
            .scalars()
            .all()
        )
        assert [c.author_id for c in comments[:2]] == [ravi.id, None]
        assert comments[0].created_at.isoformat().startswith("2025-11-03")
        assert "From Asana, by Ex Colleague" in comments[1].body_text
        assert any("Design doc" in c.body_text for c in comments)  # the Drive link
        files = (
            (await one(select(Attachment).where(Attachment.task_id == release.id))).scalars().all()
        )
        assert [(a.filename, a.size_bytes) for a in files] == [("spec.txt", len(FILE_BYTES))]
        assert (tmp_path / files[0].storage_key).read_bytes() == FILE_BYTES
        updates = (
            await one(
                select(func.count())
                .select_from(StatusUpdate)
                .where(StatusUpdate.entity_id == project.id)
            )
        ).scalar_one()
        assert updates == 2


async def test_a_dry_run_reports_and_writes_nothing(
    as_user: Clients, uow: UnitOfWork, settings: Settings, tmp_path: Any
) -> None:
    await as_user("ravi")
    async with uow.transaction() as s:
        before = (await s.execute(select(func.count()).select_from(Task))).scalar_one()
        links = (await s.execute(select(func.count()).select_from(ExternalLink))).scalar_one()
    job = await _run(uow, settings, tmp_path, dry_run=True)
    assert job.status == "done" and job.stats is not None
    report = job.stats
    # the structure, tasks and values counted; comments, files and status need the real run
    for key in (
        "teams",
        "projects",
        "sections",
        "tasks",
        "subtasks",
        "custom_fields",
        "field_values",
    ):
        assert report[key] == EXPECTED[key], key
    assert report["users_invited"] == 1 and report["dependencies"] == EXPECTED["dependencies"]
    assert "dependency t4 → t-elsewhere: the other task isn't imported" in report["skipped_items"]
    assert "comments" not in report and "attachments" not in report
    async with uow.transaction() as s:
        assert (await s.execute(select(func.count()).select_from(Task))).scalar_one() == before
        assert (
            await s.execute(select(func.count()).select_from(ExternalLink))
        ).scalar_one() == links
        assert (await s.execute(select(Team).where(Team.name == "Imported Team"))).first() is None


async def test_a_rerun_duplicates_nothing(
    as_user: Clients, uow: UnitOfWork, settings: Settings, tmp_path: Any
) -> None:
    await as_user("ravi")
    await _run(uow, settings, tmp_path)
    again = await _run(uow, settings, tmp_path)
    assert again.stats is not None
    created = {k: v for k, v in _counts(again.stats).items() if not k.startswith("users_")}
    assert set(created.values()) == {0}, created
    assert again.stats["users_matched"] == 2  # the newcomer is now an invited member
    async with uow.transaction() as s:
        assert (
            len((await s.execute(select(Team).where(Team.name == "Imported Team"))).scalars().all())
            == 1
        )
        assert (
            await s.execute(
                select(func.count()).select_from(Comment).where(Comment.created_via == "import")
            )
        ).scalar_one() == 3


async def test_one_item_at_a_time_ends_up_the_same(
    as_user: Clients, uow: UnitOfWork, settings: Settings, tmp_path: Any
) -> None:
    """Every step saves the queue in the job: the browser (or the CLI) calls again with the token
    until it's done, and the result is the same as one long run."""
    await as_user("ravi")
    ctx = await ctx_for(uow, settings, "ravi")
    async with uow.transaction() as s:
        job = new_job(
            ctx,
            workspace_gid="ws1",
            team_gid="team1",
            team_name="Imported Team",
            project_gids=None,
            dry_run=False,
        )
        s.add(job)
    steps = 0
    while job.status != "done":
        async with uow.transaction() as s:
            job = (await s.execute(select(ImportJob).where(ImportJob.id == job.id))).scalar_one()
            await run_step(
                s,
                ctx,
                FakeAsana(),
                job,
                storage=LocalStorageBackend(str(tmp_path)),
                max_upload_bytes=1024,
                seconds=0,
            )
        steps += 1
        assert steps < 200
    assert job.stats is not None and _counts(job.stats) == EXPECTED
    assert steps > 10  # it really was cut into small steps


async def test_only_some_projects(
    as_user: Clients, uow: UnitOfWork, settings: Settings, tmp_path: Any
) -> None:
    await as_user("ravi")
    job = await _run(uow, settings, tmp_path, project_gids=["p2", "nope"])
    assert job.stats is not None
    assert (job.stats["projects"], job.stats["tasks"]) == (1, 2)
    assert "project nope: not in this team (or archived)" in job.stats["skipped_items"]


async def test_the_step_api_needs_its_own_job(as_user: Clients) -> None:
    ravi, tom = await as_user("ravi"), await as_user("tom")
    body = {"workspace_gid": "ws1", "team_gid": "team1", "team_name": "T", "dry_run": True}
    r = await ravi.post("/api/v1/integrations/asana/imports", json=body)
    assert r.status_code == 201, r.text
    job = r.json()
    assert (job["status"], job["dry_run"], job["remaining"]) == ("pending", True, 1)
    assert "log" not in job and "pat" not in str(job)
    assert (await tom.get(f"/api/v1/integrations/asana/imports/{job['id']}")).status_code in (
        403,
        404,
    )
    mine = (await ravi.get("/api/v1/integrations/asana/imports")).json()["data"]
    assert job["id"] in {j["id"] for j in mine}
    bad = await ravi.post(
        f"/api/v1/integrations/asana/imports/{job['id']}/step", json={"pat": "has space"}
    )
    assert bad.status_code == 422


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


@pytest.mark.parametrize("state", ["pending", "approved", "changes_requested", "rejected"])
def test_map_approval_state(state: str) -> None:
    assert map_approval_state(state) == state
    assert map_approval_state("weird") is None


async def test_the_cli_runs_a_dry_run_then_the_import(
    as_user: Clients, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, settings: Settings
) -> None:
    """`momentum asana-import`: the token from ASANA_PAT (never printed), a dry run, then the
    import; every step is its own transaction, and the report lists what was skipped."""
    import asyncio

    from typer.testing import CliRunner

    from momentum.cli import cli
    from momentum.integrations.asana_import import client as client_module

    await as_user("admin")

    class Client(FakeAsana):
        def __init__(self, pat: str, **_: Any) -> None:
            super().__init__()
            assert pat == "1/secret-token"

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(client_module, "AsanaClient", Client)
    monkeypatch.setenv("ASANA_PAT", "1/secret-token")
    monkeypatch.setenv("MOMENTUM_DATABASE_URL", settings.database_url)
    monkeypatch.setenv("MOMENTUM_DB_SCHEMA", settings.db_schema)
    monkeypatch.setenv("MOMENTUM_STORAGE_LOCAL_DIR", str(tmp_path))
    args = [
        "asana-import",
        "--workspace",
        "ws1",
        "--team",
        "team1",
        "--team-name",
        "CLI Team",
        "--as",
        "admin@acme-demo.test",
    ]

    def run(*extra: str) -> Any:
        return CliRunner().invoke(cli, [*args, *extra])

    dry = await asyncio.to_thread(run, "--dry-run")
    assert dry.exit_code == 0, dry.output
    assert "dry run" in dry.output and "tasks: 5" in dry.output
    real = await asyncio.to_thread(run)
    assert real.exit_code == 0, real.output
    assert "comments: 2" in real.output and "skipped: task t3" in real.output
    assert "secret-token" not in dry.output + real.output
    nobody = await asyncio.to_thread(
        lambda: CliRunner().invoke(cli, [*args[:-1], "someone@example.com"])
    )
    assert nobody.exit_code != 0
