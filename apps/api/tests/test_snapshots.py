"""Phase 7.5 S75-05: project snapshots (spec §5.7). The nightly job's rows (counts, progress,
status, every project field, the forecast), same-day re-runs, retention, and the backfill that
reconstructs past days from task dates and project field history without overwriting."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from momentum.core.db import UnitOfWork
from momentum.domain.fields.models import ProjectFieldEvent
from momentum.domain.projects.models import Project, ProjectSnapshot
from momentum.domain.projects.snapshots import RETENTION_DAYS, backfill, snapshot_all
from momentum.domain.tasks.models import Task
from tests.helpers import Clients

B = "/api/v1"


async def _pid(c: object, name: str = "Website Revamp") -> str:
    projects = (await c.get(f"{B}/projects")).json()["data"]  # type: ignore[attr-defined]
    return str(next(p["id"] for p in projects if p["name"] == name))


async def _snap(uow: UnitOfWork, pid: str, day: object) -> ProjectSnapshot | None:
    async with uow.transaction() as s:  # populate_existing: the upsert bypassed the ORM
        return await s.get(ProjectSnapshot, (uuid.UUID(pid), day), populate_existing=True)


async def test_nightly_snapshot_rows_rerun_and_retention(as_user: Clients, uow: UnitOfWork) -> None:
    ravi = await as_user("ravi")
    pid = await _pid(ravi)
    stage = (
        await ravi.post(
            f"{B}/project-fields",
            json={"name": "Stage", "type": "single_select", "options": [{"label": "Discovery"}]},
        )
    ).json()["data"]
    option = stage["options"][0]["id"]
    await ravi.put(f"{B}/projects/{pid}/project-field-values/{stage['id']}", json={"value": option})
    today = datetime.now(UTC).date()
    await ravi.post(
        f"{B}/projects/{pid}/tasks",
        json={"title": "Late", "due_on": (today - timedelta(days=3)).isoformat()},
    )

    async with uow.transaction() as s:
        n = await snapshot_all(s, today)
        live = (
            await s.execute(
                select(Project.id).where(
                    Project.deleted_at.is_(None),
                    Project.archived_at.is_(None),
                    Project.is_template.is_(False),
                )
            )
        ).all()
    assert n == len(live)
    row = await _snap(uow, pid, today)
    assert row is not None
    assert row.data["fields"] == {stage["id"]: option}
    assert row.data["overdue"] >= 1 and row.data["open"] >= 1
    assert set(row.data) >= {"completed", "progress", "status", "forecast"}
    assert "reconstructed" not in row.data

    open_before = row.data["open"]
    # same day again: replaced, not duplicated
    await ravi.post(f"{B}/projects/{pid}/tasks", json={"title": "Another"})
    async with uow.transaction() as s:
        await snapshot_all(s, today)
    again = await _snap(uow, pid, today)
    assert again is not None and again.data["open"] == open_before + 1

    # retention: a row older than the window goes on the next run
    old_day = today - timedelta(days=RETENTION_DAYS + 1)
    async with uow.transaction() as s:
        s.add(
            ProjectSnapshot(
                project_id=uuid.UUID(pid), day=old_day, workspace_id=row.workspace_id, data={}
            )
        )
    async with uow.transaction() as s:
        await snapshot_all(s, today)
    assert await _snap(uow, pid, old_day) is None


async def test_backfill_reconstructs_from_history_and_never_overwrites(
    as_user: Clients, uow: UnitOfWork
) -> None:
    ravi = await as_user("ravi")
    pid = await _pid(ravi)
    today = datetime.now(UTC).date()
    stage = (
        await ravi.post(
            f"{B}/project-fields",
            json={
                "name": "Stage",
                "type": "single_select",
                "options": [{"label": "Discovery"}, {"label": "Implementation"}],
            },
        )
    ).json()["data"]
    disc, impl = (o["id"] for o in stage["options"])
    url = f"{B}/projects/{pid}/project-field-values/{stage['id']}"
    await ravi.put(url, json={"value": disc})
    await ravi.put(url, json={"value": impl})
    done = (await ravi.post(f"{B}/projects/{pid}/tasks", json={"title": "Done early"})).json()
    await ravi.post(f"{B}/tasks/{done['data']['id']}/complete")
    # move history into the past: Discovery 10 days ago, Implementation 4 days ago; the project,
    # its tasks and the completion 20 / 12 / 6 days ago
    async with uow.transaction() as s:
        events = list(
            (
                await s.execute(
                    select(ProjectFieldEvent)
                    .where(ProjectFieldEvent.project_id == uuid.UUID(pid))
                    .order_by(ProjectFieldEvent.at)
                )
            ).scalars()
        )
        now = datetime.now(UTC)
        events[0].at = now - timedelta(days=10)
        events[1].at = now - timedelta(days=4)
        await s.execute(
            update(Project)
            .where(Project.id == uuid.UUID(pid))
            .values(created_at=now - timedelta(days=20))
        )
        await s.execute(
            update(Task)
            .where(Task.id.in_(select(Task.id).where(Task.title != "Done early")))
            .values(created_at=now - timedelta(days=12), completed_at=None)
        )
        await s.execute(
            update(Task)
            .where(Task.id == uuid.UUID(done["data"]["id"]))
            .values(created_at=now - timedelta(days=12), completed_at=now - timedelta(days=6))
        )
        # a real snapshot five days ago must survive the backfill untouched
        ws = (await s.get(Project, uuid.UUID(pid))).workspace_id  # type: ignore[union-attr]
        s.add(
            ProjectSnapshot(
                project_id=uuid.UUID(pid),
                day=today - timedelta(days=5),
                workspace_id=ws,
                data={"real": True},
            )
        )

    async with uow.transaction() as s:
        written = await backfill(s, 14, today)
    assert written > 0
    day = lambda n: today - timedelta(days=n)  # noqa: E731
    ten = await _snap(uow, pid, day(10))
    seven = await _snap(uow, pid, day(7))
    three = await _snap(uow, pid, day(3))
    assert ten is not None and seven is not None and three is not None
    assert ten.data["reconstructed"] is True
    assert ten.data["fields"] == {stage["id"]: disc}
    assert three.data["fields"] == {stage["id"]: impl}
    assert seven.data["completed"] == 0 and three.data["completed"] == 1
    assert (await _snap(uow, pid, day(5))).data == {"real": True}  # type: ignore[union-attr]
    assert await _snap(uow, pid, day(13)) is not None  # tasks existed? the project did (20 d)
    # running it again writes nothing new
    async with uow.transaction() as s:
        assert await backfill(s, 14, today) == 0
