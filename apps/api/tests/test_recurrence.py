"""S4.4.2 Recurring tasks: the pure next-occurrence date math, recurrence validation, spawning
the next instance on completion (`mode: on_complete`) and on schedule (`mode: on_schedule`, the
`scan_scheduled_recurrences` job), and idempotency (a task never spawns two children)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from momentum.core.db import UnitOfWork
from momentum.core.errors import ValidationFailed
from momentum.core.settings import Settings
from momentum.domain.tasks import service as tasks
from momentum.domain.tasks.models import Task
from momentum.domain.tasks.recurrence import next_occurrence
from momentum.domain.tasks.recurrence_scan import scan_scheduled_recurrences
from tests.ai_fixtures import World, world
from tests.helpers import Clients

_ = world

# ---------------- pure date math ----------------


def test_daily() -> None:
    assert next_occurrence(date(2026, 9, 28), {"freq": "daily", "interval": 1}) == date(2026, 9, 29)
    assert next_occurrence(date(2026, 9, 28), {"freq": "daily", "interval": 3}) == date(2026, 10, 1)


def test_daily_workdays_only_skips_the_weekend() -> None:
    # 2026-09-25 is a Friday
    assert next_occurrence(
        date(2026, 9, 25), {"freq": "daily", "interval": 1, "workdays_only": True}
    ) == date(2026, 9, 28)  # Monday


def test_weekly_multiple_weekdays() -> None:
    # Monday 2026-09-28; "every Mon & Thu" -> next is Thursday the same week
    rule = {"freq": "weekly", "interval": 1, "by_weekday": [0, 3]}
    assert next_occurrence(date(2026, 9, 28), rule) == date(2026, 10, 1)
    assert next_occurrence(date(2026, 10, 1), rule) == date(2026, 10, 5)  # next Monday


def test_weekly_interval_skips_weeks() -> None:
    # every 2 weeks on Monday
    rule = {"freq": "weekly", "interval": 2, "by_weekday": [0]}
    assert next_occurrence(date(2026, 9, 28), rule) == date(2026, 10, 12)


def test_monthly_day_of_month() -> None:
    rule = {"freq": "monthly", "interval": 1, "day_of_month": 31}
    # Jan 31 -> Feb has no 31st, clamp to the 28th (2026 isn't a leap year)
    assert next_occurrence(date(2026, 1, 31), rule) == date(2026, 2, 28)


def test_monthly_day_of_month_last_day() -> None:
    rule = {"freq": "monthly", "interval": 1, "day_of_month": -1}
    assert next_occurrence(date(2026, 2, 15), rule) == date(2026, 3, 31)


def test_monthly_nth_weekday() -> None:
    # "the 2nd Monday of the month", starting from September's
    rule = {"freq": "monthly", "interval": 1, "by_weekday": [0], "week_of_month": 2}
    assert next_occurrence(date(2026, 9, 14), rule) == date(2026, 10, 12)


def test_monthly_last_weekday() -> None:
    # `after` is a chain's own due date, assumed already on-pattern (the last Friday of its
    # month), so the next occurrence is always a full month ahead — the last Friday of October,
    # not a later Friday still inside September.
    rule = {"freq": "monthly", "interval": 1, "by_weekday": [4], "week_of_month": -1}
    assert next_occurrence(date(2026, 9, 1), rule) == date(2026, 10, 30)


def test_yearly() -> None:
    assert next_occurrence(date(2026, 9, 28), {"freq": "yearly", "interval": 1}) == date(
        2027, 9, 28
    )


def test_yearly_leap_day_falls_back() -> None:
    assert next_occurrence(date(2028, 2, 29), {"freq": "yearly", "interval": 1}) == date(
        2029, 2, 28
    )


# ---------------- validation ----------------


async def test_recurrence_validation(uow: UnitOfWork, world: World) -> None:
    ravi = world.ravi
    tid = world.copy.id
    ok_cases = [
        {"freq": "daily", "workdays_only": True},
        {"freq": "weekly", "by_weekday": [0, 3]},
        {"freq": "monthly", "day_of_month": 15},
        {"freq": "monthly", "day_of_month": -1},
        {"freq": "monthly", "by_weekday": [4], "week_of_month": -1},
        {"freq": "yearly", "mode": "on_schedule"},
    ]
    for rule in ok_cases:
        async with uow.transaction() as s:
            m = await tasks.update_task(s, ravi, tid, {"recurrence": rule})
            assert m.entity.recurrence is not None, rule

    bad_cases = [
        {"recurrence": {"freq": "monthly", "day_of_month": 32}},
        {"recurrence": {"freq": "monthly", "day_of_month": 15, "week_of_month": 2}},  # exclusive
        {"recurrence": {"freq": "weekly", "day_of_month": 15}},  # only on monthly
        {"recurrence": {"freq": "monthly", "by_weekday": [0, 1], "week_of_month": 2}},  # needs 1
        {"recurrence": {"freq": "monthly", "week_of_month": 5}},  # out of range
        {"recurrence": {"freq": "daily", "mode": "whenever"}},
    ]
    for bad in bad_cases:
        with pytest.raises(ValidationFailed):
            async with uow.transaction() as s:
                await tasks.update_task(s, ravi, tid, bad)


# ---------------- spawning on completion ----------------


async def test_completing_spawns_the_next_instance_with_the_same_fields_and_subtasks(
    uow: UnitOfWork, world: World
) -> None:
    async with uow.transaction() as s:
        m = await tasks.create_task(
            s,
            world.ravi,
            world.project.id,
            "Weekly status update",
            priority="high",
            due_on=date(2026, 9, 28),  # a Monday
            recurrence={"freq": "weekly", "interval": 1, "by_weekday": [0]},
        )
        task, _placement = m.entity
        task_id, original_recurrence = task.id, dict(task.recurrence or {})
        await tasks.update_task(
            s, world.ravi, task.id, {"description": {"type": "doc", "content": []}}
        )
        await tasks.create_subtask(s, world.ravi, task.id, "Collect updates")
        await tasks.create_subtask(s, world.ravi, task.id, "Post in #general")

    async with uow.transaction() as s:
        await tasks.set_completed(s, world.ravi, task_id, True)

    async with uow.transaction() as s:
        rows = (
            (await s.execute(select(Task).where(Task.recurrence_parent_id == task_id)))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        child = rows[0]
        assert child.title == "Weekly status update"
        assert child.priority == "high"
        assert child.due_on == date(2026, 10, 5)
        assert child.recurrence == original_recurrence
        assert child.completed_at is None
        child_id = child.id

    async with uow.transaction() as s:
        kids = (
            (
                await s.execute(
                    select(Task).where(Task.parent_id == child_id).order_by(Task.parent_position)
                )
            )
            .scalars()
            .all()
        )
        assert [k.title for k in kids] == ["Collect updates", "Post in #general"]


async def test_completing_twice_does_not_double_spawn(uow: UnitOfWork, world: World) -> None:
    async with uow.transaction() as s:
        m = await tasks.create_task(
            s,
            world.ravi,
            world.project.id,
            "Daily standup notes",
            due_on=date(2026, 9, 28),
            recurrence={"freq": "daily", "interval": 1},
        )
        task = m.entity[0]

    async with uow.transaction() as s:
        await tasks.set_completed(s, world.ravi, task.id, True)
    async with uow.transaction() as s:
        await tasks.set_completed(s, world.ravi, task.id, False)
    async with uow.transaction() as s:
        await tasks.set_completed(s, world.ravi, task.id, True)

    async with uow.transaction() as s:
        rows = (
            (await s.execute(select(Task).where(Task.recurrence_parent_id == task.id)))
            .scalars()
            .all()
        )
    assert len(rows) == 1


async def test_undoing_the_completion_leaves_the_spawned_instance_in_place(
    uow: UnitOfWork, world: World
) -> None:
    from momentum.core.undo import undo

    async with uow.transaction() as s:
        m = await tasks.create_task(
            s,
            world.ravi,
            world.project.id,
            "Weekly review",
            due_on=date(2026, 9, 28),
            recurrence={"freq": "weekly", "interval": 1, "by_weekday": [0]},
        )
        task = m.entity[0]

    async with uow.transaction() as s:
        comp = await tasks.set_completed(s, world.ravi, task.id, True)
    async with uow.transaction() as s:
        await undo(s, world.ravi, activity_id=comp.activity_id)

    async with uow.transaction() as s:
        reopened = (await s.execute(select(Task).where(Task.id == task.id))).scalar_one()
        rows = (
            (await s.execute(select(Task).where(Task.recurrence_parent_id == task.id)))
            .scalars()
            .all()
        )
        assert reopened.completed_at is None
        assert len(rows) == 1  # the child from the (now-undone) completion is still there


async def test_a_recurring_task_with_no_due_date_never_spawns(
    uow: UnitOfWork, world: World
) -> None:
    async with uow.transaction() as s:
        m = await tasks.create_task(
            s,
            world.ravi,
            world.project.id,
            "Undated repeat",
            recurrence={"freq": "daily", "interval": 1},
        )
        task = m.entity[0]
    async with uow.transaction() as s:
        await tasks.set_completed(s, world.ravi, task.id, True)
    async with uow.transaction() as s:
        rows = (
            (await s.execute(select(Task).where(Task.recurrence_parent_id == task.id)))
            .scalars()
            .all()
        )
    assert rows == []


# ---------------- schedule-based spawning ----------------


async def test_on_schedule_mode_spawns_from_the_job_not_from_completion(
    uow: UnitOfWork, world: World, settings: Settings
) -> None:
    async with uow.transaction() as s:
        m = await tasks.create_task(
            s,
            world.ravi,
            world.project.id,
            "Standing meeting",
            due_on=date.today() - timedelta(days=1),
            recurrence={"freq": "weekly", "interval": 1, "by_weekday": [0], "mode": "on_schedule"},
        )
        task = m.entity[0]

    # completing it does NOT spawn (on_schedule ignores completion)
    async with uow.transaction() as s:
        await tasks.set_completed(s, world.ravi, task.id, True)
    async with uow.transaction() as s:
        rows = (
            (await s.execute(select(Task).where(Task.recurrence_parent_id == task.id)))
            .scalars()
            .all()
        )
    assert rows == []

    async with uow.transaction() as s:
        spawned = await scan_scheduled_recurrences(s, settings)
    assert spawned == 1

    # a second scan may keep the chain moving (the freshly spawned child can itself already be
    # due), but it must never give the *original* task a second child — that's the idempotency
    # guarantee `recurrence_parent_id` exists for.
    async with uow.transaction() as s:
        await scan_scheduled_recurrences(s, settings)

    async with uow.transaction() as s:
        rows = (
            (await s.execute(select(Task).where(Task.recurrence_parent_id == task.id)))
            .scalars()
            .all()
        )
    assert len(rows) == 1


async def test_scan_ignores_tasks_not_yet_due(
    uow: UnitOfWork, world: World, settings: Settings
) -> None:
    async with uow.transaction() as s:
        await tasks.create_task(
            s,
            world.ravi,
            world.project.id,
            "Future standing meeting",
            due_on=date.today() + timedelta(days=30),
            recurrence={"freq": "weekly", "interval": 1, "mode": "on_schedule"},
        )
    async with uow.transaction() as s:
        spawned = await scan_scheduled_recurrences(s, settings)
    assert spawned == 0


# ---------------- endpoint round trip ----------------


async def test_completing_a_recurring_task_through_the_api_spawns_the_next_one(
    as_user: Clients,
) -> None:
    ravi = await as_user("ravi")
    pid = next(
        p["id"]
        for p in (await ravi.get("/api/v1/projects")).json()["data"]
        if p["name"] == "Website Revamp"
    )
    created = await ravi.post(
        f"/api/v1/projects/{pid}/tasks",
        json={
            "title": "Refill the snack bar",
            "due_on": "2026-09-28",
            "recurrence": {"freq": "weekly", "by_weekday": [0]},
        },
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["data"]["id"]

    detail = (await ravi.get(f"/api/v1/tasks/{task_id}")).json()
    assert detail["recurrence"]["mode"] == "on_complete"
    assert detail["recurrence_parent_id"] is None

    done = await ravi.post(f"/api/v1/tasks/{task_id}/complete")
    assert done.status_code == 200, done.text

    listing = (await ravi.get(f"/api/v1/projects/{pid}/tasks")).json()["data"]
    child = next(t for t in listing if t["title"] == "Refill the snack bar" and t["id"] != task_id)
    child_detail = (await ravi.get(f"/api/v1/tasks/{child['id']}")).json()
    assert child_detail["recurrence_parent_id"] == task_id
    assert child_detail["due_on"] == "2026-10-05"


async def test_patching_a_task_can_set_and_clear_its_recurrence(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = next(
        p["id"]
        for p in (await ravi.get("/api/v1/projects")).json()["data"]
        if p["name"] == "Website Revamp"
    )
    created = await ravi.post(f"/api/v1/projects/{pid}/tasks", json={"title": "Take out recycling"})
    task_id = created.json()["data"]["id"]

    patched = await ravi.patch(
        f"/api/v1/tasks/{task_id}",
        json={"recurrence": {"freq": "monthly", "day_of_month": 1, "mode": "on_schedule"}},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["recurrence"] == {
        "freq": "monthly",
        "interval": 1,
        "day_of_month": 1,
        "mode": "on_schedule",
    }

    cleared = await ravi.patch(f"/api/v1/tasks/{task_id}", json={"recurrence": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["data"]["recurrence"] is None
