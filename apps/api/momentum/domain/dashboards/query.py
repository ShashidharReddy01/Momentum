"""S6.5.1: the safe query builder behind every dashboard widget.

``run()`` turns a validated ``QuerySpec`` into SQLAlchemy expressions and runs them **as the
viewer**: the first condition on every query is the same project-visibility clause as the other
bulk reads (``visible_projects_clause``, template projects excluded), so a shared dashboard never
counts a task its viewer couldn't open through a project. Tasks visible to someone only
personally (assignee or follower without project access) are left out, the gap every bulk read
discloses (see ``domain/search/service.py``). No raw SQL: the spec only chooses among the
expressions written here.

One definition per group: ``_Run.key_clause(key)`` is what "this task is in that group" means, and
the grouped counts, the folded **Other** group and the drill-down all use it, so clicking a bar
lists exactly the tasks it counted.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import (
    ColumnElement,
    DateTime,
    Select,
    String,
    and_,
    case,
    cast,
    distinct,
    false,
    func,
    literal,
    not_,
    or_,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from momentum.core.context import Ctx
from momentum.core.errors import ValidationFailed
from momentum.core.ids import task_key
from momentum.domain.access import get_visible_project, visible_projects_clause
from momentum.domain.dashboards.schemas import (
    NONE_KEY,
    OTHER_KEY,
    STATUS_KEYS,
    DrillIn,
    DrillOut,
    FilterNameOut,
    GroupOut,
    PointOut,
    QueryResultOut,
    QuerySpec,
    TaskRowOut,
    WidgetKind,
)
from momentum.domain.fields.models import FieldDef, FieldValue
from momentum.domain.projects.models import Project
from momentum.domain.sections.models import Section
from momentum.domain.tags.models import Tag, TaskTag
from momentum.domain.tasks.models import Task, TaskDependency, TaskProject
from momentum.domain.tasks.service import today_for
from momentum.domain.users.models import User

PRIORITY_ORDER = ("urgent", "high", "medium", "low", NONE_KEY)
PRIORITY_LABELS = {
    "urgent": "Urgent",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    NONE_KEY: "No priority",
}
STATUS_LABELS = {
    "overdue": "Overdue",
    "due_soon": "Due in 7 days",
    "later": "Due later",
    "no_date": "No due date",
    "completed": "Completed",
}
DUE_SOON_DAYS = 7
DASH = "\u2013"  # an en dash in date ranges
GROUP_WORDS = {
    "assignee": "assignee",
    "section": "section",
    "project": "project",
    "status": "due date",
    "priority": "priority",
    "tag": "tag",
}
NONE_LABELS = {
    "assignee": "Unassigned",
    "tag": "No tag",
    "field": "No value",
    "priority": PRIORITY_LABELS[NONE_KEY],
}


def _uuid(key: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(key)
    except ValueError:
        return None


def _floor(d: date, bucket: str) -> date:
    if bucket == "week":
        return d - timedelta(days=d.weekday())
    if bucket == "month":
        return d.replace(day=1)
    return d


def _next(d: date, bucket: str) -> date:
    if bucket == "week":
        return d + timedelta(days=7)
    if bucket == "month":
        return (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return d + timedelta(days=1)


@dataclass
class _Group:
    key: str
    value: float
    tasks: int


class _Run:
    def __init__(
        self, session: AsyncSession, ctx: Ctx, spec: QuerySpec, project_id: uuid.UUID | None
    ) -> None:
        self.session = session
        self.ctx = ctx
        self.spec = spec
        self.project_id = project_id
        self.today = today_for(ctx)
        try:
            ZoneInfo(ctx.actor.timezone)
            self.tz = ctx.actor.timezone
        except (KeyError, ValueError):
            self.tz = "UTC"
        f = spec.filters
        allowed: list[ColumnElement[bool]] = [
            visible_projects_clause(ctx),  # always first: the viewer's own visibility
            Project.is_template.is_(False),
        ]
        if project_id is not None:
            allowed.append(Project.id == project_id)
        if f.project_ids:
            allowed.append(Project.id.in_(f.project_ids))
        if f.section_ids:
            allowed.append(TaskProject.section_id.in_(f.section_ids))
        # (task, project, section) placements the viewer may count
        self.pl = (
            select(TaskProject.task_id, TaskProject.project_id, TaskProject.section_id)
            .join(Project, Project.id == TaskProject.project_id)
            .where(*allowed)
            .subquery("pl")
        )
        self.live_tags = (
            select(TaskTag.task_id, TaskTag.tag_id)
            .join(Tag, Tag.id == TaskTag.tag_id)
            .where(Tag.deleted_at.is_(None))
            .subquery("live_tags")
        )
        self.where = self._conditions()

    # ---------- which tasks ----------

    def _conditions(self) -> list[ColumnElement[bool]]:
        f = self.spec.filters
        today = self.today
        out: list[ColumnElement[bool]] = [
            Task.workspace_id == self.ctx.workspace_id,
            Task.deleted_at.is_(None),
            Task.parent_id.is_(None),
            Task.id.in_(select(self.pl.c.task_id)),
        ]
        if f.status == "open":
            out.append(Task.completed_at.is_(None))
        elif f.status == "completed":
            out.append(Task.completed_at.is_not(None))
        if f.overdue:
            out += [Task.completed_at.is_(None), Task.due_on < today]
        if f.blocked:
            blocker = aliased(Task)
            waiting = (
                select(TaskDependency.task_id)
                .join(blocker, blocker.id == TaskDependency.depends_on_id)
                .where(blocker.deleted_at.is_(None), blocker.completed_at.is_(None))
            )
            out += [Task.completed_at.is_(None), Task.id.in_(waiting)]
        if f.due_within_days is not None:
            out.append(Task.due_on.between(today, today + timedelta(days=f.due_within_days)))
        if f.due_from is not None:
            out.append(Task.due_on >= f.due_from)
        if f.due_to is not None:
            out.append(Task.due_on <= f.due_to)
        if f.completed_within_days is not None:
            first = today - timedelta(days=f.completed_within_days - 1)
            out.append(cast(func.timezone(self.tz, Task.completed_at), DateTime) >= first)
        if f.assignees:
            who: list[ColumnElement[bool]] = []
            for a in f.assignees:
                if a == NONE_KEY:
                    who.append(Task.assignee_id.is_(None))
                elif a == "me":
                    who.append(Task.assignee_id == self.ctx.actor.id)
                else:
                    who.append(Task.assignee_id == uuid.UUID(a))
            out.append(or_(*who))
        if f.priorities:
            named = [p for p in f.priorities if p != NONE_KEY]
            pri = [Task.priority.in_(named)] if named else []
            if NONE_KEY in f.priorities:
                pri.append(Task.priority.is_(None))
            out.append(or_(*pri))
        if f.tag_ids:
            out.append(
                Task.id.in_(
                    select(self.live_tags.c.task_id).where(self.live_tags.c.tag_id.in_(f.tag_ids))
                )
            )
        return out

    def _measure_of(self, est: Any, ident: Any) -> Any:
        if self.spec.measure == "sum_estimate":
            return func.coalesce(func.sum(est), 0)
        return func.count(distinct(ident))

    async def totals(self) -> tuple[float, int, int]:
        """(measure over everything matched, tasks matched, of which unestimated)."""
        measure = (
            func.coalesce(func.sum(Task.estimate_minutes), 0)
            if self.spec.measure == "sum_estimate"
            else func.count()
        )
        value, n, unestimated = (
            await self.session.execute(
                select(
                    measure, func.count(), func.count().filter(Task.estimate_minutes.is_(None))
                ).where(*self.where)
            )
        ).one()
        return float(value), int(n), int(unestimated)

    # ---------- groups ----------

    def _status_expr(self) -> ColumnElement[str]:
        return case(
            (Task.completed_at.is_not(None), literal("completed")),
            (Task.due_on.is_(None), literal("no_date")),
            (Task.due_on < self.today, literal("overdue")),
            (
                Task.due_on <= self.today + timedelta(days=DUE_SOON_DAYS),
                literal("due_soon"),
            ),
            else_=literal("later"),
        )

    def _option_expr(self) -> ColumnElement[str]:
        # a single-select value is a JSON string (the option id); ->>0 of a one-element array
        # reads it as text, and a JSON null reads as SQL null
        return func.jsonb_build_array(FieldValue.value).op("->>")(0)

    def _grouped_stmt(self) -> Select[Any]:
        """Each matched task (once per group it's in) keyed in a subquery, grouped outside it:
        grouping by the key's *column* keeps its bind parameters out of GROUP BY."""
        g = self.spec.group_by
        key: ColumnElement[Any]
        base = select(Task.id.label("id"), Task.estimate_minutes.label("est")).select_from(Task)
        if g == "assignee":
            key = func.coalesce(cast(Task.assignee_id, String), NONE_KEY)
        elif g == "priority":
            key = func.coalesce(Task.priority, NONE_KEY)
        elif g == "status":
            key = self._status_expr()
        elif g in ("project", "section"):
            col = self.pl.c.project_id if g == "project" else self.pl.c.section_id
            key = cast(col, String)
            base = base.join(self.pl, self.pl.c.task_id == Task.id)
        elif g == "tag":
            key = func.coalesce(cast(self.live_tags.c.tag_id, String), NONE_KEY)
            base = base.outerjoin(self.live_tags, self.live_tags.c.task_id == Task.id)
        else:  # field
            key = func.coalesce(self._option_expr(), NONE_KEY)
            base = base.outerjoin(
                FieldValue,
                and_(FieldValue.task_id == Task.id, FieldValue.field_id == self.spec.field_id),
            )
        keyed = base.add_columns(key.label("k")).where(*self.where).subquery("keyed")
        return select(
            keyed.c.k, self._measure_of(keyed.c.est, keyed.c.id), func.count(distinct(keyed.c.id))
        ).group_by(keyed.c.k)

    def key_clause(self, key: str) -> ColumnElement[bool]:
        """SQL for "this task is in group ``key``" (the definition every count and drill uses)."""
        g = self.spec.group_by
        uid = _uuid(key)
        if g == "assignee":
            if key == NONE_KEY:
                return Task.assignee_id.is_(None)
            return Task.assignee_id == uid if uid else false()
        if g == "priority":
            if key == NONE_KEY:
                return Task.priority.is_(None)
            return Task.priority == key if key in PRIORITY_ORDER else false()
        if g == "status":
            return self._status_expr() == key if key in STATUS_KEYS else false()
        if g in ("project", "section"):
            if uid is None:
                return false()
            col = self.pl.c.project_id if g == "project" else self.pl.c.section_id
            return Task.id.in_(select(self.pl.c.task_id).where(col == uid))
        if g == "tag":
            tagged = select(self.live_tags.c.task_id)
            if key == NONE_KEY:
                return not_(Task.id.in_(tagged))
            return Task.id.in_(tagged.where(self.live_tags.c.tag_id == uid)) if uid else false()
        # field
        valued = select(FieldValue.task_id).where(FieldValue.field_id == self.spec.field_id)
        if key == NONE_KEY:
            return not_(Task.id.in_(valued.where(self._option_expr().is_not(None))))
        return Task.id.in_(valued.where(self._option_expr() == key))

    async def groups(self) -> list[_Group]:
        """Groups in display order, the ones past ``limit`` folded into Other (counted once)."""
        rows = [
            _Group(str(k), float(v), int(n))
            for k, v, n in (await self.session.execute(self._grouped_stmt())).all()
            if n
        ]
        g = self.spec.group_by
        if g == "status":
            rows.sort(key=lambda r: STATUS_KEYS.index(r.key))
        elif g == "priority":
            rows.sort(key=lambda r: PRIORITY_ORDER.index(r.key))
        else:
            rows.sort(key=lambda r: (-r.value, -r.tasks, r.key))
        if len(rows) <= self.spec.limit:
            return rows
        top = rows[: self.spec.limit]
        value, n = await self._other(self.top_keys_of(top))
        return [*top, _Group(OTHER_KEY, value, n)] if n else top

    @staticmethod
    def top_keys_of(groups: list[_Group]) -> list[str]:
        return [x.key for x in groups if x.key != OTHER_KEY]

    def other_clause(self, top: list[str]) -> ColumnElement[bool]:
        # coalesce: ``assignee_id = X`` is NULL (not false) for an unassigned task, and NOT NULL
        # would drop it from Other
        return not_(func.coalesce(or_(*[self.key_clause(k) for k in top]), false()))

    async def _other(self, top: list[str]) -> tuple[float, int]:
        measure = (
            func.coalesce(func.sum(Task.estimate_minutes), 0)
            if self.spec.measure == "sum_estimate"
            else func.count()
        )
        value, n = (
            await self.session.execute(
                select(measure, func.count()).where(*self.where, self.other_clause(top))
            )
        ).one()
        return float(value), int(n)

    async def labels(self, keys: list[str]) -> dict[str, tuple[str, str | None]]:
        """Readable label and colour token per key (only for keys the viewer's own results
        produced, so nothing hidden is ever named)."""
        g = self.spec.group_by
        out: dict[str, tuple[str, str | None]] = {}
        ids = [u for u in (_uuid(k) for k in keys) if u is not None]
        if g in NONE_LABELS:
            out[NONE_KEY] = (NONE_LABELS[g], None)
        if g == "status":
            out.update({k: (STATUS_LABELS[k], None) for k in STATUS_KEYS})
        elif g == "priority":
            out.update({k: (PRIORITY_LABELS[k], None) for k in PRIORITY_ORDER})
        elif g == "assignee" and ids:
            for uid, name in (
                await self.session.execute(select(User.id, User.name).where(User.id.in_(ids)))
            ).all():
                out[str(uid)] = (name, None)
        elif g == "project" and ids:
            for pid, name, color in (
                await self.session.execute(
                    select(Project.id, Project.name, Project.color).where(Project.id.in_(ids))
                )
            ).all():
                out[str(pid)] = (name, color)
        elif g == "section" and ids:
            rows = (
                await self.session.execute(
                    select(Section.id, Section.name, Project.name)
                    .join(Project, Project.id == Section.project_id)
                    .where(Section.id.in_(ids))
                )
            ).all()
            several = len({p for _, _, p in rows}) > 1
            for sid, name, project in rows:
                out[str(sid)] = (f"{project} · {name}" if several else name, None)
        elif g == "tag" and ids:
            for tid, name, color in (
                await self.session.execute(
                    select(Tag.id, Tag.name, Tag.color).where(Tag.id.in_(ids))
                )
            ).all():
                out[str(tid)] = (name, color)
        elif g == "field":
            field = await self.session.get(FieldDef, self.spec.field_id)
            for o in (field.options if field else None) or []:
                out[str(o["id"])] = (str(o.get("label") or "Option"), o.get("color"))
        out[OTHER_KEY] = ("Other", None)
        return out

    # ---------- time series ----------

    def _time(self) -> tuple[ColumnElement[Any], list[ColumnElement[bool]], date, date]:
        """(bucket expression, extra conditions, first bucket, last bucket)."""
        spec = self.spec
        bucket = spec.time_bucket or "week"
        span = timedelta(days=spec.window_days - 1)
        if spec.time_field == "due":
            first, last = _floor(self.today, bucket), _floor(self.today + span, bucket)
            expr = func.date_trunc(bucket, cast(Task.due_on, DateTime))
            return expr, [Task.due_on.is_not(None)], first, last
        col = Task.completed_at if spec.time_field == "completed" else Task.created_at
        first, last = _floor(self.today - span, bucket), _floor(self.today, bucket)
        expr = func.date_trunc(bucket, func.timezone(self.tz, col))
        return expr, [col.is_not(None)], first, last

    def bucket_clause(self, start: date) -> ColumnElement[bool]:
        expr, extra, _, _ = self._time()
        return and_(*extra, cast(expr, DateTime) == datetime.combine(start, datetime.min.time()))

    async def series(self) -> list[PointOut]:
        expr, extra, first, last = self._time()
        bucket = self.spec.time_bucket or "week"
        lo = datetime.combine(first, datetime.min.time())
        hi = datetime.combine(last, datetime.min.time())
        keyed = (
            select(Task.id.label("id"), Task.estimate_minutes.label("est"), expr.label("b"))
            .where(*self.where, *extra, expr >= lo, expr <= hi)
            .subquery("bucketed")
        )
        rows = (
            await self.session.execute(
                select(
                    keyed.c.b,
                    self._measure_of(keyed.c.est, keyed.c.id),
                    func.count(distinct(keyed.c.id)),
                ).group_by(keyed.c.b)
            )
        ).all()
        found = {
            (b.date() if isinstance(b, datetime) else b): (float(v), int(n)) for b, v, n in rows
        }
        out = []
        d = first
        while d <= last:
            v, n = found.get(d, (0.0, 0))
            out.append(
                PointOut(start=d, end=_next(d, bucket) - timedelta(days=1), value=v, tasks=n)
            )
            d = _next(d, bucket)
        return out

    # ---------- task rows ----------

    def _order(self) -> list[Any]:
        spec = self.spec
        if spec.filters.status == "completed" or (
            spec.time_bucket is not None and spec.time_field == "completed"
        ):
            return [Task.completed_at.desc(), Task.number.desc()]
        return [Task.due_on.asc().nulls_last(), Task.number]

    async def task_rows(
        self, extra: list[ColumnElement[bool]], limit: int
    ) -> tuple[list[TaskRowOut], int]:
        where = [*self.where, *extra]
        total = int((await self.session.execute(select(func.count()).where(*where))).scalar_one())
        tasks = list(
            (
                await self.session.execute(
                    select(Task).where(*where).order_by(*self._order()).limit(limit)
                )
            ).scalars()
        )
        if not tasks:
            return [], total
        ids = [t.id for t in tasks]
        names: dict[uuid.UUID, str] = {
            uid: name
            for uid, name in (
                await self.session.execute(
                    select(User.id, User.name).where(
                        User.id.in_({t.assignee_id for t in tasks if t.assignee_id})
                    )
                )
            ).all()
        }
        where_placed: dict[uuid.UUID, tuple[uuid.UUID, str, str | None]] = {}
        for tid, pid, pname, color in (
            await self.session.execute(
                select(self.pl.c.task_id, Project.id, Project.name, Project.color)
                .join(Project, Project.id == self.pl.c.project_id)
                .where(self.pl.c.task_id.in_(ids))
                .order_by(Project.name)
            )
        ).all():
            where_placed.setdefault(tid, (pid, pname, color))
        rows = []
        for t in tasks:
            pid, pname, color = where_placed.get(t.id, (None, None, None))
            rows.append(
                TaskRowOut(
                    id=t.id,
                    key=task_key(t.number),
                    title=t.title,
                    assignee_id=t.assignee_id,
                    assignee_name=names.get(t.assignee_id) if t.assignee_id else None,
                    due_on=t.due_on,
                    completed_at=t.completed_at,
                    estimate_minutes=t.estimate_minutes,
                    project_id=pid,
                    project_name=pname,
                    project_color=color,
                )
            )
        return rows, total


# ---------- description ----------


def describe(spec: QuerySpec, field_name: str | None = None) -> str:
    """One plain line saying what a widget counts ("Open tasks due in the next 14 days · by
    assignee"), built from the spec, so every chart says what it shows."""
    f = spec.filters
    states = [w for w, on in (("overdue", f.overdue), ("blocked", f.blocked)) if on]
    if states:
        what = f"{' and '.join(states).capitalize()} tasks"
    else:
        what = {"open": "Open tasks", "completed": "Completed tasks", "all": "All tasks"}[f.status]
    if spec.measure == "sum_estimate":
        what = f"Estimated hours of {what[0].lower()}{what[1:]}"
    parts = [what]
    if f.due_within_days is not None:
        parts.append(
            "due today" if f.due_within_days == 0 else f"due in the next {f.due_within_days} days"
        )
    if f.completed_within_days is not None:
        parts.append(
            "completed today"
            if f.completed_within_days == 1
            else f"completed in the last {f.completed_within_days} days"
        )
    if f.due_from and f.due_to:
        parts.append(f"due {f.due_from:%b} {f.due_from.day} {DASH} {f.due_to:%b} {f.due_to.day}")
    elif f.due_from:
        parts.append(f"due from {f.due_from:%b} {f.due_from.day}")
    elif f.due_to:
        parts.append(f"due by {f.due_to:%b} {f.due_to.day}")
    if f.assignees == ["me"]:
        parts.append("assigned to you")
    elif f.assignees == [NONE_KEY]:
        parts.append("unassigned")
    elif f.assignees:
        parts.append(f"for {len(f.assignees)} people")
    if f.priorities:
        parts.append("priority " + "/".join(PRIORITY_LABELS[p].lower() for p in f.priorities))
    if f.tag_ids:
        parts.append("with a chosen tag" if len(f.tag_ids) == 1 else "with chosen tags")
    if f.project_ids:
        n = len(f.project_ids)
        parts.append("in 1 project" if n == 1 else f"in {n} projects")
    line = " ".join(parts)
    if spec.group_by == "field":
        line += f" · by {field_name or 'custom field'}"
    elif spec.group_by:
        line += f" · by {GROUP_WORDS[spec.group_by]}"
    elif spec.time_bucket:
        verb = {"completed": "completed", "created": "created", "due": "due"}[spec.time_field]
        when = "next" if spec.time_field == "due" else "last"
        line += f" · {verb} per {spec.time_bucket}, {when} {spec.window_days} days"
    return line


async def filter_names(session: AsyncSession, ctx: Ctx, spec: QuerySpec) -> list[FilterNameOut]:
    """Names for the spec's list filters, as this viewer may see them: a project or section
    outside their visibility is named generically, never by its real name."""
    f = spec.filters
    out: list[FilterNameOut] = []
    if f.project_ids:
        seen: dict[uuid.UUID, str] = {
            i: n
            for i, n in await session.execute(
                select(Project.id, Project.name).where(
                    Project.id.in_(f.project_ids), visible_projects_clause(ctx)
                )
            )
        }
        out += [
            FilterNameOut(
                filter="project_ids", key=str(i), label=seen.get(i, "A project you can't see")
            )
            for i in f.project_ids
        ]
    if f.section_ids:
        seen = {
            i: n
            for i, n in await session.execute(
                select(Section.id, Section.name)
                .join(Project, Project.id == Section.project_id)
                .where(Section.id.in_(f.section_ids), visible_projects_clause(ctx))
            )
        }
        out += [
            FilterNameOut(
                filter="section_ids", key=str(i), label=seen.get(i, "A section you can't see")
            )
            for i in f.section_ids
        ]
    if f.assignees:
        ids = [u for u in (_uuid(a) for a in f.assignees) if u is not None]
        names: dict[uuid.UUID, str] = (
            {
                i: n
                for i, n in await session.execute(
                    select(User.id, User.name).where(
                        User.id.in_(ids), User.workspace_id == ctx.workspace_id
                    )
                )
            }
            if ids
            else {}
        )
        for a in f.assignees:
            label = (
                "Me"
                if a == "me"
                else "Unassigned"
                if a == NONE_KEY
                else names.get(uuid.UUID(a), "Someone not in this workspace")
            )
            out.append(FilterNameOut(filter="assignees", key=a, label=label))
    if f.tag_ids:
        seen = {
            i: n
            for i, n in await session.execute(
                select(Tag.id, Tag.name).where(
                    Tag.id.in_(f.tag_ids), Tag.workspace_id == ctx.workspace_id
                )
            )
        }
        out += [
            FilterNameOut(filter="tag_ids", key=str(i), label=seen.get(i, "A deleted tag"))
            for i in f.tag_ids
        ]
    out += [
        FilterNameOut(filter="priorities", key=p, label=PRIORITY_LABELS[p]) for p in f.priorities
    ]
    return out


# ---------- entry points ----------


async def check_spec(session: AsyncSession, ctx: Ctx, spec: QuerySpec) -> str | None:
    """What the model can't check alone: a grouped-by custom field exists here and is a
    single-select. Returns the field's name (for the description)."""
    if spec.field_id is None:
        return None
    field = await session.get(FieldDef, spec.field_id)
    if field is None or field.workspace_id != ctx.workspace_id or field.deleted_at is not None:
        raise ValidationFailed("That custom field doesn't exist")
    if field.type != "single_select":
        raise ValidationFailed("Charts can group by single-select fields only")
    return field.name


async def _prepare(
    session: AsyncSession, ctx: Ctx, spec: QuerySpec, project_id: uuid.UUID | None
) -> tuple[_Run, str | None]:
    if project_id is not None:
        await get_visible_project(session, ctx, project_id)  # NotFound when not visible
    field_name = await check_spec(session, ctx, spec)
    return _Run(session, ctx, spec, project_id), field_name


async def run(
    session: AsyncSession,
    ctx: Ctx,
    kind: WidgetKind,
    spec: QuerySpec,
    *,
    project_id: uuid.UUID | None = None,
) -> QueryResultOut:
    """One widget's numbers for this viewer."""
    r, field_name = await _prepare(session, ctx, spec, project_id)
    total, n, unestimated = await r.totals()
    out = QueryResultOut(
        kind=kind,
        measure=spec.measure,
        description=describe(spec, field_name),
        total=total,
        tasks_total=n,
        unestimated=unestimated if spec.measure == "sum_estimate" else 0,
        filter_names=await filter_names(session, ctx, spec),
        field_name=field_name,
        computed_at=datetime.now(UTC),
    )
    if kind == "count":
        out.value = total
    elif kind in ("bar", "donut"):
        groups = await r.groups()
        labels = await r.labels([x.key for x in groups])
        out.groups = [
            GroupOut(
                key=x.key,
                label=labels.get(x.key, ("Unknown", None))[0],
                value=x.value,
                tasks=x.tasks,
                color=labels.get(x.key, ("", None))[1],
            )
            for x in groups
        ]
    elif kind == "line":
        out.series = await r.series()
    else:
        out.tasks, matched = await r.task_rows([], spec.limit)
        out.more = max(0, matched - len(out.tasks))
    return out


async def drill(session: AsyncSession, ctx: Ctx, body: DrillIn) -> DrillOut:
    """The tasks behind one mark: the same spec, narrowed with the same clause that counted
    them. ``key='other'`` recomputes the shown groups and takes everything outside them."""
    r, _ = await _prepare(session, ctx, body.query_spec, body.project_id)
    extra: list[ColumnElement[bool]] = []
    label = "Tasks"
    if body.key is not None:
        if body.key == OTHER_KEY:
            shown = r.top_keys_of(await r.groups())
            extra.append(r.other_clause(shown) if shown else false())
            label = "Other"
        else:
            extra.append(r.key_clause(body.key))
            label = (await r.labels([body.key])).get(body.key, ("Tasks", None))[0]
    if body.bucket_start is not None:
        bucket = body.query_spec.time_bucket or "week"
        start = _floor(body.bucket_start, bucket)
        extra.append(r.bucket_clause(start))
        end = _next(start, bucket) - timedelta(days=1)
        label = (
            f"{start:%b} {start.day}"
            if start == end
            else f"{start:%b} {start.day} {DASH} {end:%b} {end.day}"
        )
    tasks, total = await r.task_rows(extra, body.limit)
    return DrillOut(label=label, tasks=tasks, total=total)
