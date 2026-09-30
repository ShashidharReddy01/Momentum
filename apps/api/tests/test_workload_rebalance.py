"""S6.4.2 rebalance heuristic on crafted overloads (pure: no database). Reassign before moving
dates, never onto someone without access or room, a due date moves only when nothing else helps,
and it stops when everyone fits or nothing helps."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from momentum.domain.workload.rebalance import (
    Item,
    Person,
    PlanFn,
    PushPlan,
    Rebalance,
    Shift,
    plan_moves,
)

TODAY = date(2030, 1, 1)  # a Tuesday
W1, W2, W3, W4, W5 = (date(2030, 1, 7) + timedelta(weeks=i) for i in range(5))
WINDOW = [W1, W2, W3]
HORIZON = [W1, W2, W3, W4, W5]
H = 60  # minutes in an hour
PROJECT = uuid.uuid4()


def person(name: str, hours: int = 30, **weeks: int) -> Person:
    cap = {w: hours * H for w in HORIZON}
    for k, v in weeks.items():  # e.g. w2=0 for a week away
        cap[HORIZON[int(k[1:]) - 1]] = v * H
    return Person(id=uuid.uuid4(), name=name, email=f"{name.lower()}@x.test", capacity=cap)


_n = iter(range(1, 1000))


def task(
    who: Person,
    hours: float,
    due: date,
    start: date | None = None,
    *,
    receivers: tuple[Person, ...] = (),
    movable: bool = True,
    title: str = "",
) -> Item:
    n = next(_n)
    return Item(
        id=uuid.uuid4(),
        number=n,
        title=title or f"Task {n}",
        project_id=PROJECT,
        project_name="Website Revamp",
        project_due=None,
        assignee_id=who.id,
        start_on=start,
        due_on=due,
        minutes=int(hours * H),
        movable=movable,
        overdue=False,
        receivers=tuple(r.id for r in receivers),
    )


async def no_cascade(item: Item, start: date | None, due: date) -> PushPlan:
    return ()


async def run(
    people: list[Person],
    items: list[Item],
    *,
    hidden: dict[uuid.UUID, dict[date, float]] | None = None,
    push: PlanFn = no_cascade,
) -> Rebalance:
    return await plan_moves(
        people={p.id: p for p in people},
        items=items,
        window=WINDOW,
        horizon=HORIZON,
        hidden=hidden or {},
        today=TODAY,
        push_plan=push,
    )


FRI1 = W1 + timedelta(days=4)  # the Friday of week 1


async def test_nothing_to_do_when_everyone_fits() -> None:
    ana, ravi = person("Ana"), person("Ravi")
    r = await run([ana, ravi], [task(ana, 20, FRI1, W1, receivers=(ravi,))])
    assert (r.status, r.moves, r.unresolved) == ("nothing_to_do", [], [])


async def test_reassigns_the_smallest_task_that_clears_the_week() -> None:
    ana, ravi = person("Ana"), person("Ravi")
    big = task(ana, 20, FRI1, W1, receivers=(ravi,))
    fits = task(ana, 12, FRI1, W1, receivers=(ravi,))
    small = task(ana, 8, FRI1, W1, receivers=(ravi,))  # 40h against 30h: 10h over
    r = await run([ana, ravi], [big, fits, small])
    assert r.status == "balanced"
    [mv] = r.moves
    assert (mv.kind, mv.item.id, mv.to_person) == ("reassign", fits.id, ravi.id)
    assert r.after[ana.id][W1] == 28 * H and r.after[ravi.id][W1] == 12 * H
    assert r.before[ana.id][W1] == 40 * H


async def test_never_assigns_to_someone_without_access_or_room() -> None:
    ana, ravi, mei = person("Ana"), person("Ravi"), person("Mei")
    busy = task(ravi, 25, FRI1, W1)  # Ravi has 5h left in week 1
    t = task(ana, 12, FRI1, W1, receivers=(ravi,))  # Mei has room but no edit access
    filler = task(ana, 25, FRI1, W1)
    r = await run([ana, ravi, mei], [busy, t, filler])
    assert all(m.to_person != mei.id for m in r.moves)
    assert all(m.kind != "reassign" for m in r.moves)


async def test_hidden_work_limits_who_can_take_more() -> None:
    ana, ravi, priya = person("Ana"), person("Ravi"), person("Priya")
    t = task(ana, 10, FRI1, W1, receivers=(ravi, priya))
    filler = task(ana, 25, FRI1, W1)
    # Ravi is nearly full on work the asker can't see: Priya gets it
    r = await run([ana, ravi, priya], [t, filler], hidden={ravi.id: {W1: 25 * H}})
    [mv] = r.moves
    assert mv.to_person == priya.id


async def test_prefers_someone_already_in_the_project() -> None:
    ana, ravi, priya = person("Ana"), person("Ravi"), person("Priya")
    t = task(ana, 10, FRI1, W1, receivers=(ravi, priya))
    filler = task(ana, 25, FRI1, W1)
    r = await run([ana, ravi, priya], [t, filler, task(priya, 2, W2 + timedelta(days=4), W2)])
    [mv] = r.moves
    assert mv.to_person == priya.id  # Ravi has more room, but Priya works there already


async def test_starts_later_before_moving_a_due_date() -> None:
    ana = person("Ana")
    # 20h over two weeks (10h each) plus 25h fixed in week 1: 5h over; week 2 has room
    spans = task(ana, 20, W2 + timedelta(days=4), W1)
    fixed = task(ana, 25, FRI1, W1, movable=False)
    r = await run([ana], [spans, fixed])
    [mv] = r.moves
    assert (mv.kind, mv.new_start, mv.due_moved) == ("start_later", W2, False)
    assert r.status == "balanced" and r.after[ana.id][W2] == 20 * H


async def test_moves_a_due_date_only_when_nothing_else_helps() -> None:
    ana = person("Ana")
    t = task(ana, 8, FRI1, FRI1)
    fixed = task(ana, 30, FRI1, W1, movable=False)
    r = await run([ana], [t, fixed])
    [mv] = r.moves
    assert (mv.kind, mv.weeks_later, mv.due_moved) == ("push", 1, True)
    assert mv.new_due == FRI1 + timedelta(weeks=1)
    assert r.status == "balanced"


async def test_a_push_that_reaches_uneditable_work_is_never_offered() -> None:
    ana = person("Ana")
    t = task(ana, 8, FRI1, FRI1)
    fixed = task(ana, 30, FRI1, W1, movable=False)

    async def blocked(item: Item, start: date | None, due: date) -> PushPlan:
        return None

    r = await run([ana], [t, fixed], push=blocked)
    assert r.moves == [] and r.status == "partial"
    [u] = r.unresolved
    assert (u.person, u.week, u.over, u.reason) == (ana.id, W1, 8 * H, "no_room")


async def test_a_push_never_overloads_whoever_the_dependents_belong_to() -> None:
    ana, mei = person("Ana"), person("Mei")
    t = task(ana, 8, FRI1, FRI1)
    fixed = task(ana, 30, FRI1, W1, movable=False)
    mei_full = task(mei, 28, W3 + timedelta(days=4), W3, movable=False)
    dep_id = uuid.uuid4()

    async def cascade(item: Item, start: date | None, due: date) -> PushPlan:
        # Mei's 6h dependent follows from week 2 into week 3, where she has 2h left
        return (
            Shift(
                dep_id,
                99,
                "Follow-up",
                mei.id,
                6 * H,
                W2 + timedelta(days=4),
                W2 + timedelta(days=4),
                W3 + timedelta(days=4),
                W3 + timedelta(days=4),
            ),
        )

    r = await run([ana, mei], [t, fixed, mei_full], push=cascade)
    assert r.moves == []
    assert r.unresolved[0].reason == "no_room"


async def test_nothing_movable_is_reported_and_it_stops() -> None:
    ana, ravi = person("Ana"), person("Ravi")
    r = await run([ana, ravi], [task(ana, 40, FRI1, W1, receivers=(ravi,), movable=False)])
    assert r.moves == [] and r.status == "partial"
    assert [(u.reason, u.over) for u in r.unresolved] == [("nothing_movable", 10 * H)]


async def test_several_moves_until_everyone_fits_and_each_task_moves_once() -> None:
    ana, priya, ravi = person("Ana"), person("Priya"), person("Ravi", hours=20)
    items = [task(ana, 10, FRI1, W1, receivers=(ravi, priya)) for _ in range(5)]  # 50h vs 30h
    items += [task(priya, 30, FRI1, W1, movable=False), task(priya, 6, FRI1, FRI1)]  # 6h over
    r = await run([ana, priya, ravi], items)
    assert r.status == "balanced"
    assert len({m.item.id for m in r.moves}) == len(r.moves)
    for pid in (ana.id, priya.id, ravi.id):
        for w in WINDOW:
            assert r.after[pid].get(w, 0) <= r.people[pid].capacity[w]


async def test_same_input_same_suggestion() -> None:
    ana, priya, ravi = person("Ana"), person("Priya"), person("Ravi")
    items = [task(ana, h, FRI1, W1, receivers=(ravi, priya)) for h in (6, 9, 12, 14)]
    a = await run([ana, priya, ravi], items)
    b = await run([ana, priya, ravi], items)
    assert [(m.kind, m.item.id, m.to_person) for m in a.moves] == [
        (m.kind, m.item.id, m.to_person) for m in b.moves
    ]
