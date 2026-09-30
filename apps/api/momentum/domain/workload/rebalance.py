"""S6.4.2: suggest a rebalance. A greedy heuristic over the workload model (no solver) that
proposes the fewest, least disruptive moves bringing people back under capacity. It writes
nothing: the AI layer turns the moves into one proposed action (preview → apply → one undo).

**What it may touch.** Only open, top-level, estimated tasks the asker can see *and edit*. Work in
projects the asker can't see is never named or moved; it only counts against a person's room
when they'd receive work (``hidden``), so nobody gets work piled onto a week that's already full
elsewhere.

**Who may receive work.** Active people (not agents) who can edit the task's project. If a
person lists ``skills`` in their prefs and the task has tags, at least one must match. Among
those, people who already work in that project or on the same tags come first, then the one
with the most room.

**Moves, least disruptive first**, tried for the most overloaded person-week:

1. ``reassign``: give the task to someone with room in every week it touches, dates unchanged.
2. ``start_later``: start it the following Monday, due date unchanged (a task spanning weeks).
3. ``push``: move the whole task one or two weeks later, dependents following through the
   same dependency cascade as the timeline (``tasks.plan_reschedule``). This moves a due date,
   so it's only tried when nothing above helps that week, and the move says so. A push whose
   cascade would reach a task the asker can't edit, or push anyone else over, is not offered.

Within a tier, a move that clears the overload with the least effort moved wins; otherwise the
one that relieves the most. Nobody is pushed over capacity by a move, no task is touched twice,
and it stops when nobody is over, nothing helps, or ``MAX_MOVES`` is reached. Weeks it couldn't
fix are reported with the reason.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Actor, Ctx
from momentum.core.errors import Forbidden, NotFound, ValidationFailed
from momentum.core.ids import task_key
from momentum.domain.access import (
    ROLE_RANK,
    get_visible_project,
    project_role,
    visible_projects_clause,
)
from momentum.domain.projects.models import Project
from momentum.domain.tags.models import Tag, TaskTag
from momentum.domain.tasks import service as tasks
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.users.models import User
from momentum.domain.workload.service import (
    MAX_WEEKS,
    _open_top_level,
    monday,
    spread,
    workload,
)

MAX_MOVES = 12  # each move is one operation in the proposed action (limit 20)
PUSH_WEEKS = (1, 2)
LOOKAHEAD_WEEKS = 2  # loads are known this far past the window, so a push can be checked
MAX_PLANS = 40  # cascade previews computed for push candidates

Kind = Literal["reassign", "start_later", "push"]
Status = Literal["balanced", "partial", "nothing_to_do", "no_estimates"]
Week = date
Load = dict[uuid.UUID, dict[Week, float]]


@dataclass
class Item:
    """One open task as the heuristic sees it."""

    id: uuid.UUID
    number: int
    title: str
    project_id: uuid.UUID
    project_name: str
    project_due: date | None
    assignee_id: uuid.UUID | None
    start_on: date | None
    due_on: date
    minutes: int
    movable: bool  # the asker can edit it and it carries an estimate
    overdue: bool
    tags: frozenset[str] = frozenset()
    receivers: tuple[uuid.UUID, ...] = ()  # who could take it (edit access, skills)

    @property
    def key(self) -> str:
        return task_key(self.number)


@dataclass
class Person:
    id: uuid.UUID
    name: str
    email: str
    capacity: dict[Week, int]
    projects: frozenset[uuid.UUID] = frozenset()  # where they already have open work
    tags: frozenset[str] = frozenset()  # tags on their open work


@dataclass(frozen=True)
class Shift:
    """A dependent that follows a pushed task (the cascade)."""

    id: uuid.UUID
    number: int
    title: str
    assignee_id: uuid.UUID | None
    minutes: int
    from_start: date | None
    from_due: date | None
    to_start: date | None
    to_due: date | None

    @property
    def key(self) -> str:
        return task_key(self.number)

    @property
    def days(self) -> int:
        a, b = self.from_due or self.from_start, self.to_due or self.to_start
        return (b - a).days if a and b else 0


# a push's cascade: None when it can't be done (it reaches a task the asker can't edit)
PushPlan = tuple[Shift, ...] | None
PlanFn = Callable[[Item, date | None, date], Awaitable[PushPlan]]


@dataclass
class Move:
    kind: Kind
    item: Item
    person: uuid.UUID  # whose week it relieves (the assignee)
    week: Week  # the week it was chosen for
    relief: int  # overload minutes it removes
    to_person: uuid.UUID | None = None
    new_start: date | None = None
    new_due: date | None = None
    weeks_later: int = 0
    shifted: tuple[Shift, ...] = ()
    past_project_due: bool = False

    @property
    def due_moved(self) -> bool:
        return self.kind == "push"


@dataclass
class Unresolved:
    person: uuid.UUID
    week: Week
    over: int
    reason: Literal["nothing_movable", "no_room"]


@dataclass
class Rebalance:
    status: Status
    weeks: list[Week]
    people: dict[uuid.UUID, Person]
    before: Load
    after: Load
    moves: list[Move]
    unresolved: list[Unresolved]
    limited: bool = False  # stopped at MAX_MOVES with people still over


# ---------------- the pure heuristic ----------------


def _weeks_of(
    start: date | None, due: date, minutes: int, today: date, window: set[Week]
) -> dict[Week, float]:
    out: dict[Week, float] = defaultdict(float)
    for d, m in spread(start, due, minutes, today).items():
        w = monday(d)
        if w in window:
            out[w] += m
    return dict(out)


@dataclass
class _State:
    people: dict[uuid.UUID, Person]
    window: list[Week]
    load: Load  # visible, per person and week
    hidden: Load  # work the asker can't see
    today: date
    touched: set[uuid.UUID] = field(default_factory=set)

    def cap(self, pid: uuid.UUID, w: Week) -> int:
        return self.people[pid].capacity.get(w, 0)

    def over(self, pid: uuid.UUID, w: Week) -> float:
        return max(0.0, self.load[pid].get(w, 0.0) - self.cap(pid, w))

    def fits(self, pid: uuid.UUID, add: dict[Week, float], *, with_hidden: bool) -> bool:
        """Adding ``add`` keeps the person at or under capacity in every week it touches (and
        within the known horizon)."""
        for w, m in add.items():
            if m <= 0:
                continue
            if w not in self.people[pid].capacity:
                return False  # beyond what we know
            extra = self.hidden[pid].get(w, 0.0) if with_hidden else 0.0
            if self.load[pid].get(w, 0.0) + extra + m > self.cap(pid, w) + 0.5:
                return False
        return True

    def relief(self, pid: uuid.UUID, remove: dict[Week, float], add: dict[Week, float]) -> float:
        """How much the person's total overload drops."""
        before = after = 0.0
        for w in set(remove) | set(add):
            cur = self.load[pid].get(w, 0.0)
            new = cur - remove.get(w, 0.0) + add.get(w, 0.0)
            before += max(0.0, cur - self.cap(pid, w))
            after += max(0.0, new - self.cap(pid, w))
        return before - after

    def apply(self, pid: uuid.UUID, remove: dict[Week, float], add: dict[Week, float]) -> None:
        for w, m in remove.items():
            self.load[pid][w] = self.load[pid].get(w, 0.0) - m
        for w, m in add.items():
            self.load[pid][w] = self.load[pid].get(w, 0.0) + m


def _span(item: Item, today: date, window: set[Week]) -> dict[Week, float]:
    return _weeks_of(item.start_on, item.due_on, item.minutes, today, window)


def _rank_receivers(state: _State, item: Item) -> list[uuid.UUID]:
    """Familiar people first (already in the project, then same tags), then most room."""

    def room(pid: uuid.UUID) -> float:
        span = _span(item, state.today, set(state.people[pid].capacity))
        return min(
            (
                state.cap(pid, w) - state.load[pid].get(w, 0.0) - state.hidden[pid].get(w, 0.0)
                for w in span
            ),
            default=0.0,
        )

    def order(pid: uuid.UUID) -> tuple[int, int, float, str]:
        p = state.people[pid]
        return (
            0 if item.project_id in p.projects else 1,
            0 if item.tags & p.tags else 1,
            -room(pid),
            p.name,
        )

    return sorted((r for r in item.receivers if r in state.people), key=order)


def _pick(options: list[tuple[float, int, Move]], over: float) -> Move | None:
    """Clears the overload with the least effort moved, else relieves the most."""
    if not options:
        return None
    clearing = [o for o in options if o[0] >= over - 0.5]
    if clearing:
        return min(clearing, key=lambda o: (o[1], o[2].item.number))[2]
    return max(options, key=lambda o: (o[0], -o[2].item.number))[2]


async def plan_moves(
    *,
    people: dict[uuid.UUID, Person],
    items: list[Item],
    window: list[Week],
    horizon: list[Week],
    hidden: Load,
    today: date,
    push_plan: PlanFn,
    max_moves: int = MAX_MOVES,
) -> Rebalance:
    """The heuristic itself: deterministic for the same inputs. ``window`` is what the asker is
    looking at (overload is fixed there); ``horizon`` extends it so a push can be checked."""
    known = set(horizon)
    load: Load = {pid: defaultdict(float) for pid in people}
    for it in items:
        if it.assignee_id in load:
            for w, m in _span(it, today, known).items():
                load[it.assignee_id][w] += m
    before = {pid: dict(v) for pid, v in load.items()}
    hidden_all: Load = {pid: defaultdict(float, hidden.get(pid, {})) for pid in people}
    state = _State(people, window, load, hidden_all, today)
    by_person: dict[uuid.UUID, list[Item]] = defaultdict(list)
    for it in items:
        if it.assignee_id is not None:
            by_person[it.assignee_id].append(it)

    def over_cells() -> list[tuple[uuid.UUID, Week, float]]:
        cells = [(pid, w, state.over(pid, w)) for pid in people for w in window]
        cells = [c for c in cells if c[2] > 0.5]
        return sorted(cells, key=lambda c: (-c[2], c[1], people[c[0]].name))

    if not over_cells():
        return Rebalance("nothing_to_do", window, people, before, before, [], [])

    moves: list[Move] = []
    stuck: dict[tuple[uuid.UUID, Week], Literal["nothing_movable", "no_room"]] = {}
    plans_left = MAX_PLANS
    while len(moves) < max_moves:
        chosen: Move | None = None
        for pid, w, over in over_cells():
            if (pid, w) in stuck:
                continue
            cands = [
                it
                for it in by_person[pid]
                if it.movable and it.id not in state.touched and w in _span(it, today, known)
            ]
            if not cands:
                stuck[(pid, w)] = "nothing_movable"
                continue
            # 1. reassign, same dates
            options: list[tuple[float, int, Move]] = []
            for it in cands:
                span = _span(it, today, known)
                for r in _rank_receivers(state, it):
                    if r == pid or not state.fits(r, span, with_hidden=True):
                        continue
                    gain = state.relief(pid, span, {})
                    if gain > 0.5:
                        options.append(
                            (
                                min(gain, over),
                                it.minutes,
                                Move("reassign", it, pid, w, round(gain), r),
                            )
                        )
                        break  # the best-ranked receiver with room
            chosen = _pick(options, over)
            # 2. start the following Monday, due date unchanged
            if chosen is None:
                for it in cands:
                    later = w + timedelta(days=7)
                    if it.overdue or it.due_on < later or it.start_on is None:
                        continue
                    old = _span(it, today, known)
                    new = _weeks_of(later, it.due_on, it.minutes, today, known)
                    delta = {k: v - old.get(k, 0.0) for k, v in new.items()}
                    if not state.fits(pid, delta, with_hidden=False):
                        continue
                    gain = state.relief(pid, old, new)
                    if gain > 0.5:
                        mv = Move("start_later", it, pid, w, round(gain), new_start=later)
                        options.append((min(gain, over), it.minutes, mv))
                chosen = _pick(options, over)
            # 3. push the whole task later (moves its due date)
            if chosen is None:
                for it in cands:
                    if it.overdue:
                        continue
                    old = _span(it, today, known)
                    for n in PUSH_WEEKS:
                        if plans_left <= 0:
                            break
                        new_start = it.start_on + timedelta(weeks=n) if it.start_on else None
                        new_due = it.due_on + timedelta(weeks=n)
                        new = _weeks_of(new_start, new_due, it.minutes, today, known)
                        if monday(new_due) not in known:
                            break  # past what we know about
                        delta = {k: v - old.get(k, 0.0) for k, v in new.items()}
                        if not state.fits(pid, delta, with_hidden=False):
                            continue
                        plans_left -= 1
                        cascade = await push_plan(it, new_start, new_due)
                        if cascade is None or any(s.id in state.touched for s in cascade):
                            break  # it reaches work the asker can't edit: never offered
                        if not _cascade_fits(state, cascade, pid, old, new):
                            continue
                        gain = state.relief(pid, old, new)
                        if gain > 0.5:
                            mv = Move(
                                "push",
                                it,
                                pid,
                                w,
                                round(gain),
                                new_start=new_start,
                                new_due=new_due,
                                weeks_later=n,
                                shifted=cascade,
                                past_project_due=bool(it.project_due and new_due > it.project_due),
                            )
                            options.append((min(gain, over), it.minutes, mv))
                            break  # the smallest push that helps
                chosen = _pick(options, over)
            if chosen is not None:
                break
            stuck[(pid, w)] = "no_room"
        if chosen is None:
            break
        _commit(state, chosen, known)
        moves.append(chosen)

    after = {pid: dict(v) for pid, v in state.load.items()}
    left = over_cells()
    unresolved = [
        Unresolved(pid, w, round(o), stuck.get((pid, w), "no_room")) for pid, w, o in left
    ]
    status: Status = "balanced" if not left else "partial"
    return Rebalance(
        status,
        window,
        people,
        before,
        after,
        moves,
        unresolved,
        limited=bool(left) and len(moves) >= max_moves,
    )


def _shift_weeks(s: Shift, today: date, known: set[Week]) -> tuple[dict[Week, float], ...]:
    def span(start: date | None, due: date | None) -> dict[Week, float]:
        if due is None:
            return {}
        return _weeks_of(start, due, s.minutes, today, known)

    return span(s.from_start, s.from_due), span(s.to_start, s.to_due)


def _cascade_fits(
    state: _State,
    cascade: tuple[Shift, ...],
    pid: uuid.UUID,
    old: dict[Week, float],
    new: dict[Week, float],
) -> bool:
    """Every dependent that follows stays within its assignee's room (the pushed task's own
    person included, counted together)."""
    delta: dict[uuid.UUID, dict[Week, float]] = defaultdict(lambda: defaultdict(float))
    for k, v in new.items():
        delta[pid][k] += v
    for k, v in old.items():
        delta[pid][k] -= v
    known = set(state.people[pid].capacity)
    for s in cascade:
        if s.assignee_id is None or s.assignee_id not in state.people:
            continue
        a, b = _shift_weeks(s, state.today, known)
        for k, v in b.items():
            delta[s.assignee_id][k] += v
        for k, v in a.items():
            delta[s.assignee_id][k] -= v
    for person, d in delta.items():
        if person == pid:
            if not state.fits(person, d, with_hidden=False):
                return False
        elif not state.fits(person, d, with_hidden=True):
            return False
    return True


def _commit(state: _State, mv: Move, known: set[Week]) -> None:
    it = mv.item
    old = _span(it, state.today, known)
    if mv.kind == "reassign":
        assert mv.to_person is not None
        state.apply(mv.person, old, {})
        state.apply(mv.to_person, {}, old)
    else:
        new = _weeks_of(mv.new_start, mv.new_due or it.due_on, it.minutes, state.today, known)
        state.apply(mv.person, old, new)
        for s in mv.shifted:
            if s.assignee_id in state.people:
                a, b = _shift_weeks(s, state.today, known)
                state.apply(s.assignee_id, a, b)
            state.touched.add(s.id)
    state.touched.add(it.id)


# ---------------- loading it from the workspace ----------------


def _person_ctx(ctx: Ctx, user: User) -> Ctx:
    return Ctx(
        actor=Actor(id=user.id, workspace_id=user.workspace_id, role=user.role),
        settings=ctx.settings,
    )


def _skills(user: User) -> frozenset[str]:
    raw = (user.prefs or {}).get("skills") or []
    return frozenset(str(s).strip().lower() for s in raw if str(s).strip())


async def suggest(
    session: AsyncSession,
    ctx: Ctx,
    start: date,
    weeks: int,
    project_id: uuid.UUID | None = None,
    today: date | None = None,
) -> Rebalance:
    """Suggest moves for the asker (``ctx``) over ``weeks`` from ``start``'s week. With
    ``project_id`` only that project's tasks move, but everyone's load counts all the work the
    asker can see (otherwise someone busy on another project would look free)."""
    if ctx.actor.is_agent:
        raise Forbidden("Rebalancing is suggested to a person")
    if not 1 <= weeks <= MAX_WEEKS:
        raise ValidationFailed(f"Show between 1 and {MAX_WEEKS} weeks", code="invalid_range")
    if project_id is not None:
        await get_visible_project(session, ctx, project_id)
    today = today or datetime.now(UTC).date()
    wl = await workload(
        session, ctx, start, min(weeks + LOOKAHEAD_WEEKS, MAX_WEEKS), project_id=None, today=today
    )
    window, horizon = wl.weeks[:weeks], wl.weeks
    users = {p.user.id: p.user for p in wl.people if p.user is not None}
    people = {
        u.id: Person(
            id=u.id,
            name=u.name,
            email=u.email,
            capacity={w: pl.capacity_minutes for w, pl in p.weeks.items()},
        )
        for p in wl.people
        if (u := p.user) is not None
    }

    ids = [t.task.id for t in wl.tasks]
    tags: dict[uuid.UUID, set[str]] = defaultdict(set)
    if ids:
        for tid, name in (
            await session.execute(
                select(TaskTag.task_id, Tag.name)
                .join(Tag, Tag.id == TaskTag.tag_id)
                .where(TaskTag.task_id.in_(ids), Tag.deleted_at.is_(None))
            )
        ).all():
            tags[tid].add(name.strip().lower())
    project_ids = {t.project_id for t in wl.tasks}
    projects = {
        p.id: p
        for p in (
            await session.execute(select(Project).where(Project.id.in_(project_ids)))
        ).scalars()
    }

    editor: dict[tuple[uuid.UUID, uuid.UUID | None], bool] = {}

    async def can_edit(pid: uuid.UUID, user: User | None = None) -> bool:
        """The asker (no ``user``) or ``user`` can edit tasks in the project."""
        k = (pid, user.id if user else None)
        if k not in editor:
            role = await project_role(
                session, _person_ctx(ctx, user) if user else ctx, projects[pid]
            )
            editor[k] = role is not None and ROLE_RANK[role] >= ROLE_RANK["editor"]
        return editor[k]

    items: list[Item] = []
    for t in wl.tasks:
        task = t.task
        assert task.due_on is not None
        movable = (
            (project_id is None or t.project_id == project_id)
            and bool(task.estimate_minutes)
            and task.assignee_id in people
            and await can_edit(t.project_id)
        )
        task_tags = frozenset(tags.get(task.id, set()))
        receivers: list[uuid.UUID] = []
        if movable:
            for uid, user in users.items():
                if uid == task.assignee_id or not await can_edit(t.project_id, user):
                    continue
                skills = _skills(user)
                if skills and task_tags and not (skills & task_tags):
                    continue
                receivers.append(uid)
        items.append(
            Item(
                id=task.id,
                number=task.number,
                title=task.title,
                project_id=t.project_id,
                project_name=t.project_name,
                project_due=projects[t.project_id].due_on,
                assignee_id=task.assignee_id,
                start_on=task.start_on,
                due_on=task.due_on,
                minutes=task.estimate_minutes or 0,
                movable=movable,
                overdue=t.overdue,
                tags=task_tags,
                receivers=tuple(receivers),
            )
        )
    for pid, person in people.items():
        mine = [it for it in items if it.assignee_id == pid]
        person.projects = frozenset(it.project_id for it in mine)
        person.tags = frozenset(tg for it in mine for tg in it.tags)

    if not any(it.minutes for it in items):
        return Rebalance("no_estimates", window, people, {}, {}, [], [])

    hidden = await _hidden_load(session, ctx, set(people), horizon, today)

    async def push_plan(item: Item, new_start: date | None, new_due: date) -> PushPlan:
        patch: dict[str, date] = {"due_on": new_due}
        if new_start is not None:
            patch["start_on"] = new_start
        try:
            plan = await tasks.plan_reschedule(session, ctx, item.id, patch)
        except (ValidationFailed, Forbidden, NotFound):
            return None
        if plan.skipped:
            return None
        return tuple(
            Shift(
                id=c.task.id,
                number=c.task.number,
                title=c.task.title,
                assignee_id=c.task.assignee_id,
                minutes=c.task.estimate_minutes or 0,
                from_start=c.from_start,
                from_due=c.from_due,
                to_start=c.to_start,
                to_due=c.to_due,
            )
            for c in plan.shifted
        )

    return await plan_moves(
        people=people,
        items=items,
        window=window,
        horizon=horizon,
        hidden=hidden,
        today=today,
        push_plan=push_plan,
    )


async def _hidden_load(
    session: AsyncSession,
    ctx: Ctx,
    people: set[uuid.UUID],
    horizon: list[Week],
    today: date,
) -> Load:
    """Each person's effort per week on open work the asker can't see: only ever a limit on how
    much more they can take, never shown or moved."""
    if not people or not horizon:
        return {}
    last = horizon[-1] + timedelta(days=6)
    visible = (
        select(TaskProject.task_id)
        .join(Project, Project.id == TaskProject.project_id)
        .where(visible_projects_clause(ctx))
    )
    rows = await session.execute(
        select(Task.start_on, Task.due_on, Task.estimate_minutes, Task.assignee_id).where(
            *_open_top_level(ctx.workspace_id),
            Task.assignee_id.in_(people),
            Task.due_on.is_not(None),
            Task.due_on <= last,
            Task.estimate_minutes > 0,
            Task.id.not_in(visible),
        )
    )
    known = set(horizon)
    out: dict[uuid.UUID, dict[Week, float]] = defaultdict(lambda: defaultdict(float))
    for start_on, due_on, minutes, uid in rows.all():
        for w, m in _weeks_of(start_on, due_on, minutes, today, known).items():
            out[uid][w] += m
    return {k: dict(v) for k, v in out.items()}


# ---------------- in words (the preview, the facts, Mo's tool) ----------------


Clean = Callable[[str], str]


def _same(s: str) -> str:
    return s


def hours(minutes: float) -> str:
    """As the grid shows them: whole hours, else one decimal."""
    h = round(minutes) / 60
    return f"{h:g}h" if h.is_integer() else f"{h:.1f}h"


def day(d: date) -> str:
    return f"{d:%b} {d.day}"


def week(w: date) -> str:
    return f"the week of {day(w)}"


def _name(r: Rebalance, pid: uuid.UUID | None, clean: Clean = _same) -> str:
    return clean(r.people[pid].name) if pid in r.people else "someone"


def describe(r: Rebalance, mv: Move, clean: Clean = _same) -> str:
    """One move in words ("T-12 Brief the vendor (8h): Ana → Ravi"), as the preview shows it."""
    it = mv.item
    head = f"{it.key} {clean(it.title)} ({hours(it.minutes)})"
    if mv.kind == "reassign":
        return f"{head}: {_name(r, mv.person, clean)} → {_name(r, mv.to_person, clean)}"
    if mv.kind == "start_later":
        assert mv.new_start is not None
        return f"{head}: starts {day(mv.new_start)}, due date unchanged ({day(it.due_on)})"
    assert mv.new_due is not None
    later = f"{mv.weeks_later} week{'s' if mv.weeks_later > 1 else ''} later"
    text = f"{head}: moved {later}, due {day(it.due_on)} → {day(mv.new_due)}"
    if mv.shifted:
        text += f"; {len(mv.shifted)} dependent task{'s' if len(mv.shifted) > 1 else ''} follow"
    return text


def why(r: Rebalance, mv: Move, clean: Clean = _same) -> str:
    """The reason for one move, from the heuristic's own numbers."""
    over = f"{_name(r, mv.person, clean)} was over in {week(mv.week)}"
    if mv.kind == "reassign":
        assert mv.to_person is not None
        who = r.people[mv.to_person]
        familiar = (
            " and already works in this project" if mv.item.project_id in who.projects else ""
        )
        return f"{over}; {clean(who.name)} has room{familiar}."
    if mv.kind == "start_later":
        return f"{over}; nobody who can take it had room, and it can start later and still finish."
    text = f"{over}; nobody had room and it couldn't start later. This moves its due date."
    if mv.past_project_due:
        text += " It also lands after the project's due date."
    return text
