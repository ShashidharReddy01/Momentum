"""S6.4.1: workload. Who is carrying what, week by week, against the hours they have.

- **Effort** is ``tasks.estimate_minutes``, spread evenly over the working days (Mon-Fri) from a
  task's start to its due date (the due day alone when there is no start). Open work is future
  work: a task already underway only spreads over what's left of it, and an overdue task lands on
  today. Tasks with no due date aren't placed; they're counted per person as "no date".
- **Capacity** for a person and week is, first that applies: that week's override (``capacity``,
  e.g. time off), the person's own weekly hours (``users.prefs['weekly_hours']``), the workspace
  default (``workspaces.settings['workload']['default_hours']``, admins), then the
  ``MOMENTUM_WORKLOAD_DEFAULT_HOURS`` setting.
- **Visibility**: only open top-level tasks in projects the viewer can see are placed or named;
  the rest are counted per person (``hidden``), never named.

Changing capacity is the person themselves or a workspace admin, with activity and undo.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import Date, and_, case, cast, func, literal, not_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import record_activity
from momentum.core.context import Ctx
from momentum.core.errors import Forbidden, NotFound, ValidationFailed
from momentum.core.events import emit
from momentum.core.mutation import Mutation
from momentum.core.settings import Settings
from momentum.core.undo import undo_handler, undo_op
from momentum.domain.access import (
    get_visible_project,
    visible_people_clause,
    visible_projects_clause,
)
from momentum.domain.projects.models import Project
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.users.models import User
from momentum.domain.workload.models import Capacity
from momentum.domain.workspace.models import Workspace

MAX_HOURS = 80.0
MAX_WEEKS = 26


def monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _working_days(start: date, end: date) -> list[date]:
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    weekdays = [d for d in days if d.weekday() < 5]
    return weekdays or days  # a weekend-only task still counts


def spread(
    start_on: date | None, due_on: date, minutes: int | None, today: date
) -> dict[date, float]:
    """A task's effort per day (see the module doc). With no estimate, each day it touches gets
    0, so it still counts towards the task count of its weeks."""
    first = start_on if start_on is not None and start_on <= due_on else due_on
    if due_on < today:
        first = due_on = today  # overdue: it's on today's plate
    elif first < today:
        first = today  # underway: only what's left
    days = _working_days(first, due_on)
    each = (minutes or 0) / len(days)
    return {d: each for d in days}


def _weekdays_between(a: date, b: date) -> int:
    """Mon-Fri days from ``a`` to ``b`` inclusive (0 if ``b`` < ``a``), without a day loop."""
    if b < a:
        return 0
    days = (b - a).days + 1
    full, rest = divmod(days, 7)
    count = full * 5
    start = a.weekday()
    count += sum(1 for i in range(rest) if (start + i) % 7 < 5)
    return count


def spread_weeks(
    start_on: date | None, due_on: date, minutes: int | None, today: date
) -> dict[date, float]:
    """``spread`` summed per week (keyed by Monday), computed a week at a time: the same numbers,
    without building one entry per day (a long task covers 60-90 days)."""
    first = start_on if start_on is not None and start_on <= due_on else due_on
    if due_on < today:
        first = due_on = today
    elif first < today:
        first = today
    week = monday(first)
    if due_on < week + timedelta(days=7):  # within one week (every overdue task): all of it
        return {week: float(minutes or 0)}
    total = _weekdays_between(first, due_on)
    weekend_only = total == 0
    if weekend_only:
        total = (due_on - first).days + 1
    out: dict[date, float] = {}
    while week <= due_on:
        a, b = max(first, week), min(due_on, week + timedelta(days=6))
        n = (b - a).days + 1 if weekend_only else _weekdays_between(a, b)
        if n:
            out[week] = (minutes or 0) * n / total
        week += timedelta(days=7)
    return out


@dataclass
class WeekLoad:
    week_start: date
    capacity_minutes: int = 0
    override: bool = False
    planned_minutes: float = 0
    task_count: int = 0
    unestimated: int = 0


@dataclass
class PersonLoad:
    user: User | None  # None = the unassigned row
    weekly_minutes: int = 0
    hours_source: str = "setting"  # person | workspace | setting
    weeks: dict[date, WeekLoad] = field(default_factory=dict)
    no_date: int = 0
    hidden: int = 0


class PlacedFields(Protocol):
    """The task columns the grid and its task list read (a plain row: hydrating ~13k ORM objects
    per view was a third of the endpoint's time in the Phase 7 load test)."""

    @property
    def id(self) -> uuid.UUID: ...
    @property
    def number(self) -> int: ...
    @property
    def title(self) -> str: ...
    @property
    def assignee_id(self) -> uuid.UUID | None: ...
    @property
    def start_on(self) -> date | None: ...
    @property
    def due_on(self) -> date | None: ...
    @property
    def estimate_minutes(self) -> int | None: ...
    @property
    def version(self) -> int: ...


@dataclass
class PlacedTask:
    task: PlacedFields
    project_id: uuid.UUID
    project_name: str
    overdue: bool
    weeks: dict[date, float]


@dataclass
class Workload:
    start: date
    weeks: list[date]
    default_minutes: int
    default_source: str  # workspace | setting
    people: list[PersonLoad]
    unassigned: PersonLoad
    tasks: list[PlacedTask]  # the ones ``tasks_for`` asked for
    any_estimate: bool = False  # any placed task (listed or not) has an estimate


# ---------- capacity ----------


def _minutes(hours: float) -> int:
    return round(hours * 60)


def _check_hours(hours: float | None) -> None:
    if hours is not None and not 0 <= hours <= MAX_HOURS:
        raise ValidationFailed(
            f"Weekly hours must be between 0 and {MAX_HOURS:g}", code="invalid_hours"
        )


def workspace_default_hours(ws: Workspace | None) -> float | None:
    value = ((ws.settings or {}).get("workload") or {}).get("default_hours") if ws else None
    return float(value) if value is not None else None


def person_hours(user: User) -> float | None:
    value = (user.prefs or {}).get("weekly_hours")
    return float(value) if value is not None else None


async def default_minutes(
    session: AsyncSession, settings: Settings, workspace_id: uuid.UUID
) -> tuple[int, str]:
    hours = workspace_default_hours(await session.get(Workspace, workspace_id))
    if hours is not None:
        return _minutes(hours), "workspace"
    return _minutes(settings.workload_default_hours), "setting"


async def _overrides(
    session: AsyncSession, workspace_id: uuid.UUID, weeks: list[date]
) -> dict[tuple[uuid.UUID, date], int]:
    rows = await session.execute(
        select(Capacity).where(
            Capacity.workspace_id == workspace_id, Capacity.week_start.in_(weeks)
        )
    )
    return {(c.user_id, c.week_start): c.capacity_minutes for c in rows.scalars()}


async def _people(session: AsyncSession, ctx: Ctx) -> list[User]:
    return list(
        (
            await session.execute(
                select(User)
                .where(
                    User.workspace_id == ctx.workspace_id,
                    User.status == "active",
                    User.is_agent.is_(False),
                    visible_people_clause(ctx, User.id),
                )
                .order_by(User.name)
            )
        ).scalars()
    )


# ---------- the view ----------


# what the workload grid and its task list read from a task
PLACED_COLUMNS = (
    Task.id,
    Task.workspace_id,
    Task.number,
    Task.title,
    Task.assignee_id,
    Task.start_on,
    Task.due_on,
    Task.estimate_minutes,
    Task.version,
)


def _open_top_level(workspace_id: uuid.UUID) -> list[Any]:
    return [
        Task.workspace_id == workspace_id,
        Task.deleted_at.is_(None),
        Task.completed_at.is_(None),
        Task.parent_id.is_(None),
        Task.type != "milestone",
    ]


async def workload(
    session: AsyncSession,
    ctx: Ctx,
    start: date,
    weeks: int,
    project_id: uuid.UUID | None = None,
    today: date | None = None,
    tasks_for: str = "all",
    project_ids: list[uuid.UUID] | None = None,
) -> Workload:
    """``project_ids`` (Phase 7.5): only these projects (a portfolio's), still as the viewer."""
    if not 1 <= weeks <= MAX_WEEKS:
        raise ValidationFailed(f"Show between 1 and {MAX_WEEKS} weeks", code="invalid_range")
    if project_id is not None:
        await get_visible_project(session, ctx, project_id)
    today = today or datetime.now(UTC).date()
    first = monday(start)
    week_list = [first + timedelta(weeks=i) for i in range(weeks)]
    last = week_list[-1] + timedelta(days=6)
    dflt, dflt_source = await default_minutes(session, ctx.settings, ctx.workspace_id)
    overrides = await _overrides(session, ctx.workspace_id, week_list)

    def row(user: User | None) -> PersonLoad:
        own = person_hours(user) if user else None
        weekly = _minutes(own) if own is not None else (dflt if user else 0)
        p = PersonLoad(
            user,
            weekly_minutes=weekly,
            hours_source="person" if own is not None else dflt_source,
        )
        for w in week_list:
            o = overrides.get((user.id, w)) if user else None
            p.weeks[w] = WeekLoad(w, weekly if o is None else o, override=o is not None)
        return p

    people = {u.id: row(u) for u in await _people(session, ctx)}
    unassigned = row(None)

    # every open top-level task in a project you can see, due by the window's end: only the
    # columns the grid uses, filtered in SQL (Phase 7 load test: this loaded every open task
    # with its description and dropped most of them in Python)
    only = [Project.id == project_id] if project_id is not None else []
    if project_ids is not None:
        only.append(Project.id.in_(project_ids))
    scope = [*_open_top_level(ctx.workspace_id), visible_projects_clause(ctx), *only]
    # Where a task's effort lands (see ``spread_weeks``), in SQL: from its start (its due day when
    # it has no start, today when underway) to its due day (today when overdue).
    begins = case(
        (and_(Task.start_on.is_not(None), Task.start_on <= Task.due_on), Task.start_on),
        else_=Task.due_on,
    )
    on_plate = case((Task.due_on < today, literal(today)), else_=func.greatest(begins, today))
    ends = func.greatest(Task.due_on, today)
    week_of = func.date_trunc("week", on_plate)
    one_week = week_of == func.date_trunc("week", ends)
    visible_ids = (
        select(TaskProject.task_id)
        .join(Project, Project.id == TaskProject.project_id)
        .where(visible_projects_clause(ctx), *only)
    )
    dated = [*_open_top_level(ctx.workspace_id), Task.id.in_(visible_ids), Task.due_on <= last]

    def row_of(assignee_id: uuid.UUID | None) -> PersonLoad | None:
        return people.get(assignee_id) if assignee_id else unassigned  # None: inactive or agent

    # Phase 7 load test: most tasks (every overdue one) land in a single week, so the grid sums
    # those in SQL; only multi-week tasks are spread here, one row at a time.
    any_estimate = False
    single = await session.execute(
        select(
            Task.assignee_id,
            cast(week_of, Date),
            func.count(),
            func.coalesce(func.sum(Task.estimate_minutes), 0),
            func.count().filter(Task.estimate_minutes.is_(None)),
        )
        .where(*dated, one_week, on_plate >= first)
        .group_by(Task.assignee_id, week_of)
    )
    for uid, week, n, minutes, unestimated in single.all():
        person = row_of(uid)
        if person is None or week not in person.weeks:
            continue
        wl = person.weeks[week]
        wl.planned_minutes += float(minutes)
        wl.task_count += int(n)
        wl.unestimated += int(unestimated)
        any_estimate = any_estimate or int(unestimated) < int(n)

    def listed(assignee_id: uuid.UUID | None) -> bool:
        if tasks_for in ("all", "none"):
            return tasks_for == "all"
        if tasks_for == "unassigned":
            return assignee_id is None
        return str(assignee_id) == tasks_for.lower()

    # multi-week tasks (all of them: the grid needs them) and, for the task list, the one-week
    # tasks of the row(s) asked for
    wanted = [not_(one_week)]
    if tasks_for == "all":
        wanted = []
    elif tasks_for == "unassigned":
        wanted = [or_(not_(one_week), Task.assignee_id.is_(None))]
    elif tasks_for != "none":
        wanted = [or_(not_(one_week), Task.assignee_id == uuid.UUID(tasks_for))]
    q = (
        select(
            *PLACED_COLUMNS,
            one_week.label("one_week"),
            Project.id.label("project_id"),
            Project.name.label("project_name"),
        )
        .join(TaskProject, TaskProject.task_id == Task.id)
        .join(Project, Project.id == TaskProject.project_id)
        .where(*scope, Task.due_on <= last, *wanted)
        .order_by(Task.due_on, Task.number)
    )
    seen: set[uuid.UUID] = set()
    placed: list[PlacedTask] = []
    # open tasks with no due date: counted per person, not placed
    undated = await session.execute(
        select(Task.assignee_id, func.count())
        .where(*_open_top_level(ctx.workspace_id), Task.id.in_(visible_ids), Task.due_on.is_(None))
        .group_by(Task.assignee_id)
    )
    for uid, n in undated.all():
        person = row_of(uid)
        if person is not None:
            person.no_date = int(n)
    for task in (await session.execute(q)).all():
        if task.id in seen:  # multi-homed: once
            continue
        seen.add(task.id)
        person = row_of(task.assignee_id)
        if person is None:
            continue
        assert task.due_on is not None
        by_week = {
            w: m
            for w, m in spread_weeks(
                task.start_on, task.due_on, task.estimate_minutes, today
            ).items()
            if first <= w <= last
        }
        if not by_week:
            continue
        if not task.one_week:  # one-week tasks are already in the grid
            any_estimate = any_estimate or task.estimate_minutes is not None
            for w, m in by_week.items():
                wl = person.weeks[w]
                wl.planned_minutes += m
                wl.task_count += 1
                if task.estimate_minutes is None:
                    wl.unestimated += 1
        if listed(task.assignee_id):
            placed.append(
                PlacedTask(
                    task, task.project_id, task.project_name, task.due_on < today, dict(by_week)
                )
            )

    if project_id is None and project_ids is None:
        # open work in projects you can't see: counted per person, never named
        visible = select(TaskProject.task_id).join(Project, Project.id == TaskProject.project_id)
        visible = visible.where(visible_projects_clause(ctx))
        hidden = await session.execute(
            select(Task.assignee_id, func.count())
            .where(
                *_open_top_level(ctx.workspace_id),
                Task.assignee_id.is_not(None),
                Task.due_on <= last,
                Task.id.not_in(visible),
            )
            .group_by(Task.assignee_id)
        )
        for uid, n in hidden.all():
            if uid in people:
                people[uid].hidden = int(n)

    return Workload(
        start=first,
        weeks=week_list,
        default_minutes=dflt,
        default_source=dflt_source,
        people=list(people.values()),
        unassigned=unassigned,
        tasks=placed,
        any_estimate=any_estimate,
    )


async def load_between(
    session: AsyncSession,
    settings: Settings,
    workspace_id: uuid.UUID,
    user_ids: set[uuid.UUID],
    start: date,
    end: date,
) -> dict[uuid.UUID, tuple[int, int, int]]:
    """For Architect's capacity notes (it runs as the requester's agent, and names only the
    person): each person's (planned minutes, capacity minutes, open tasks due) between two dates,
    across all their work. Capacity is prorated by working days."""
    if not user_ids or end < start:
        return {}
    today = datetime.now(UTC).date()
    dflt, _ = await default_minutes(session, settings, workspace_id)
    days = _working_days(start, end)
    week_list = sorted({monday(d) for d in days})
    overrides = await _overrides(session, workspace_id, week_list)
    users = {
        u.id: u
        for u in (await session.execute(select(User).where(User.id.in_(user_ids)))).scalars()
    }
    out: dict[uuid.UUID, tuple[int, int, int]] = {}
    for uid, user in users.items():
        own = person_hours(user)
        weekly = _minutes(own) if own is not None else dflt
        capacity = sum(overrides.get((uid, monday(d)), weekly) / 5 for d in days)
        planned, count = 0.0, 0
        tasks = await session.execute(
            select(Task).where(
                *_open_top_level(workspace_id),
                Task.assignee_id == uid,
                Task.due_on.is_not(None),
                Task.due_on <= end,
            )
        )
        for task in tasks.scalars():
            assert task.due_on is not None
            if start <= task.due_on:
                count += 1
            planned += sum(
                m
                for d, m in spread(task.start_on, task.due_on, task.estimate_minutes, today).items()
                if start <= d <= end
            )
        out[uid] = (round(planned), round(capacity), count)
    return out


# ---------- writes ----------


def _require_self_or_admin(ctx: Ctx, user_id: uuid.UUID) -> None:
    if ctx.actor.is_agent:
        raise Forbidden("Agents can't change anyone's capacity")
    if not (ctx.actor.is_admin or ctx.actor.id == user_id):
        raise Forbidden("Only the person or a workspace admin can change their hours")


async def _user(session: AsyncSession, ctx: Ctx, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None or user.workspace_id != ctx.workspace_id or user.is_agent:
        raise NotFound("Person not found")
    return user


async def _changed(
    session: AsyncSession,
    ctx: Ctx,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    verb: str,
    changes: dict[str, Any],
    undo: dict[str, Any] | None,
    data: dict[str, Any],
) -> uuid.UUID:
    act = await record_activity(
        session,
        ctx,
        entity_type=entity_type,
        entity_id=entity_id,
        verb=verb,
        changes=changes,
        undo=undo,
    )
    await emit(
        session,
        ctx,
        type="workload.capacity_changed",
        entity_type=entity_type,
        entity_id=entity_id,
        data=data,
        channels=[f"workspace:{ctx.workspace_id}"],
        activity_id=act.id,
    )
    await session.flush()
    return act.id


async def set_weekly_hours(
    session: AsyncSession,
    ctx: Ctx,
    user_id: uuid.UUID,
    hours: float | None,
    *,
    record_undo: bool = True,
) -> Mutation[float | None]:
    """A person's standing weekly hours; None = the workspace default."""
    _require_self_or_admin(ctx, user_id)
    _check_hours(hours)
    user = await _user(session, ctx, user_id)
    before = person_hours(user)
    if before == hours:
        return Mutation(hours)
    # one key, atomically (concurrent saves of other prefs are kept)
    if hours is None:
        await session.execute(
            text(
                "UPDATE users SET prefs = coalesce(prefs, '{}'::jsonb) - 'weekly_hours' "
                "WHERE id = :uid"
            ),
            {"uid": user_id},
        )
    else:
        await session.execute(
            text(
                "UPDATE users SET prefs = coalesce(prefs, '{}'::jsonb) || "
                "jsonb_build_object('weekly_hours', cast(:h as float)) WHERE id = :uid"
            ),
            {"h": hours, "uid": user_id},
        )
    await session.refresh(user, ["prefs"])
    act = await _changed(
        session,
        ctx,
        entity_type="user",
        entity_id=user_id,
        verb="user.weekly_hours_changed",
        changes={"weekly_hours": (before, hours)},
        undo=undo_op("workload.set_hours", user_id=user_id, hours=before) if record_undo else None,
        data={"user_id": str(user_id)},
    )
    return Mutation(hours, act)


async def set_week(
    session: AsyncSession,
    ctx: Ctx,
    user_id: uuid.UUID,
    week_start: date,
    hours: float | None,
    *,
    record_undo: bool = True,
) -> Mutation[float | None]:
    """One week's capacity for a person (0 = away all week); None = back to their usual hours."""
    _require_self_or_admin(ctx, user_id)
    _check_hours(hours)
    if week_start.weekday() != 0:
        raise ValidationFailed("A week starts on a Monday", code="invalid_week")
    await _user(session, ctx, user_id)
    row = await session.get(Capacity, (user_id, week_start))
    before = row.capacity_minutes / 60 if row else None
    if before == hours:
        return Mutation(hours)
    if hours is None:
        assert row is not None
        await session.delete(row)
    elif row is None:
        session.add(
            Capacity(
                user_id=user_id,
                week_start=week_start,
                workspace_id=ctx.workspace_id,
                capacity_minutes=_minutes(hours),
            )
        )
    else:
        row.capacity_minutes = _minutes(hours)
    act = await _changed(
        session,
        ctx,
        entity_type="user",
        entity_id=user_id,
        verb="user.week_capacity_changed",
        changes={f"capacity {week_start.isoformat()}": (before, hours)},
        undo=undo_op(
            "workload.set_week", user_id=user_id, week_start=week_start.isoformat(), hours=before
        )
        if record_undo
        else None,
        data={"user_id": str(user_id), "week_start": week_start.isoformat()},
    )
    return Mutation(hours, act)


async def set_default_hours(
    session: AsyncSession, ctx: Ctx, hours: float | None, *, record_undo: bool = True
) -> Mutation[float | None]:
    """The workspace's default weekly hours (admins); None = the environment's setting."""
    if ctx.actor.is_agent or not ctx.actor.is_admin:
        raise Forbidden("Only a workspace admin can change the default hours")
    _check_hours(hours)
    ws = await session.get(Workspace, ctx.workspace_id)
    if ws is None:
        raise NotFound("Workspace not found")
    before = workspace_default_hours(ws)
    if before == hours:
        return Mutation(hours)
    workload_settings = dict((ws.settings or {}).get("workload") or {})
    if hours is None:
        workload_settings.pop("default_hours", None)
    else:
        workload_settings["default_hours"] = hours
    # JSONB is replaced wholesale so SQLAlchemy sees the change.
    ws.settings = {**(ws.settings or {}), "workload": workload_settings}
    act = await _changed(
        session,
        ctx,
        entity_type="workspace",
        entity_id=ws.id,
        verb="workspace.workload_hours_changed",
        changes={"default_hours": (before, hours)},
        undo=undo_op("workload.set_default_hours", hours=before) if record_undo else None,
        data={},
    )
    return Mutation(hours, act)


def _hours(args: dict[str, Any]) -> float | None:
    return None if args.get("hours") is None else float(args["hours"])


@undo_handler("workload.set_hours")
async def _undo_hours(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    await set_weekly_hours(
        session, ctx, uuid.UUID(str(args["user_id"])), _hours(args), record_undo=False
    )


@undo_handler("workload.set_week")
async def _undo_week(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    await set_week(
        session,
        ctx,
        uuid.UUID(str(args["user_id"])),
        date.fromisoformat(str(args["week_start"])),
        _hours(args),
        record_undo=False,
    )


@undo_handler("workload.set_default_hours")
async def _undo_default(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    await set_default_hours(session, ctx, _hours(args), record_undo=False)
