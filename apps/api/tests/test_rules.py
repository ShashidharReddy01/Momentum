"""S4.1.1 Rules: the model and API (validation, permissions) and the executor: triggers,
conditions, actions, and above all loop protection (depth, rate, one run per event)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.core.activity import Activity
from momentum.core.events import ConsumerOffset, OutboxEvent
from momentum.core.settings import Settings
from momentum.domain.comments.models import Comment
from momentum.domain.rules.engine import (
    CONSUMER,
    MAX_ACTIONS_PER_MINUTE,
    MAX_DEPTH,
    RulesRun,
    compare,
    run_rules,
)
from momentum.domain.rules.models import Rule, RuleRun
from momentum.domain.tasks.models import Task
from momentum.domain.users.models import User
from tests.helpers import Clients

SessionFactory = async_sessionmaker[AsyncSession]


async def _project(c: httpx.AsyncClient, name: str = "Website Revamp") -> str:
    return next(
        p["id"] for p in (await c.get("/api/v1/projects")).json()["data"] if p["name"] == name
    )


async def _sections(c: httpx.AsyncClient, pid: str) -> dict[str, str]:
    rows = (await c.get(f"/api/v1/projects/{pid}/sections")).json()["data"]
    return {s["name"]: s["id"] for s in rows}


async def _task(c: httpx.AsyncClient, pid: str, section: str, title: str = "T", **body: Any) -> str:
    r = await c.post(
        f"/api/v1/projects/{pid}/tasks", json={"title": title, "section_id": section, **body}
    )
    assert r.status_code == 201, r.text
    return str(r.json()["data"]["id"])


async def _move(c: httpx.AsyncClient, task: str, section: str) -> None:
    r = await c.post(f"/api/v1/tasks/{task}/move", json={"section_id": section})
    assert r.status_code == 200, r.text


async def _rule(
    c: httpx.AsyncClient,
    project: str | None,
    trigger: dict[str, Any],
    actions: list[Any],
    **extra: Any,
) -> str:
    body = {"name": "R", "project_id": project, "trigger": trigger, "actions": actions, **extra}
    r = await c.post("/api/v1/rules", json=body)
    assert r.status_code == 201, r.text
    return str(r.json()["data"]["id"])


async def _user_id(c: httpx.AsyncClient, local: str) -> str:
    users = (await c.get("/api/v1/users")).json()["data"]
    return next(u["id"] for u in users if u["email"].startswith(f"{local}@"))


async def _run(sf: SessionFactory, settings: Settings) -> RulesRun:
    async with sf() as s, s.begin():
        return await run_rules(s, settings)


async def _query[T](sf: SessionFactory, fn: Callable[[AsyncSession], Awaitable[T]]) -> T:
    async with sf() as s:
        return await fn(s)


async def _runs(sf: SessionFactory, rule_id: str) -> list[RuleRun]:
    async def q(s: AsyncSession) -> list[RuleRun]:
        stmt = (
            select(RuleRun)
            .where(RuleRun.rule_id == uuid.UUID(rule_id))
            .order_by(RuleRun.started_at)
        )
        return list((await s.execute(stmt)).scalars())

    return await _query(sf, q)


async def _comments(sf: SessionFactory, task_id: str) -> list[Comment]:
    async def q(s: AsyncSession) -> list[Comment]:
        stmt = select(Comment).where(Comment.task_id == uuid.UUID(task_id))
        return list((await s.execute(stmt)).scalars())

    return await _query(sf, q)


async def _task_row(sf: SessionFactory, task_id: str) -> Task:
    async def q(s: AsyncSession) -> Task:
        return (await s.execute(select(Task).where(Task.id == uuid.UUID(task_id)))).scalar_one()

    return await _query(sf, q)


# ---------------- validation ----------------


async def test_rule_validation(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    sec = await _sections(ravi, pid)
    move = {"type": "task.moved", "to_section": sec["Review"]}
    ok = [{"type": "add_comment", "text": "hi"}]
    bad: list[dict[str, Any]] = [
        {"trigger": {"type": "task.exploded"}, "actions": ok},
        {"trigger": {"type": "form.submitted"}, "actions": ok},  # not available yet
        {"trigger": {"type": "task.completed", "to_section": sec["Review"]}, "actions": ok},
        {"trigger": {"type": "task.field_changed", "field": "title"}, "actions": ok},
        {"trigger": move, "actions": []},
        {"trigger": move, "actions": [{"type": "delete_everything"}]},
        {"trigger": move, "actions": [{"type": "add_comment"}]},
        {"trigger": move, "actions": [{"type": "assign"}]},  # user_id needed (null unassigns)
        {"trigger": move, "actions": ok, "conditions": [{"field": "priority", "op": "in"}]},
        {
            "trigger": move,
            "actions": ok,
            "conditions": [{"field": "priority", "op": "gt", "value": 1}],
        },
        {
            "trigger": move,
            "actions": ok,
            "conditions": [{"field": "tag", "op": "eq", "value": "x"}],
        },
        {"trigger": move, "actions": ok, "conditions": [{"field": "nope", "op": "eq", "value": 1}]},
    ]
    for body in bad:
        r = await ravi.post("/api/v1/rules", json={"name": "R", "project_id": pid, **body})
        assert r.status_code == 422, (body, r.text)
    # references must exist, and sections must belong to the rule's project
    other = await _sections(ravi, await _project(ravi, "Mobile App v2"))
    for trig, act in (
        ({"type": "task.moved", "to_section": other["To do"]}, ok),
        (move, [{"type": "move_section", "section_id": other["To do"]}]),
        (move, [{"type": "assign", "user_id": str(uuid.uuid4())}]),
        ({"type": "task.assigned", "user_id": str(uuid.uuid4())}, ok),
    ):
        r = await ravi.post(
            "/api/v1/rules", json={"name": "R", "project_id": pid, "trigger": trig, "actions": act}
        )
        assert r.status_code == 422, (trig, act, r.text)
    good = await ravi.post(
        "/api/v1/rules",
        json={
            "name": "Escalate",
            "project_id": pid,
            "trigger": move,
            "conditions": [{"field": "priority", "op": "in", "value": ["high", "urgent"]}],
            "actions": [{"type": "assign", "user_id": None}, *ok],
        },
    )
    assert good.status_code == 201, good.text
    assert good.json()["data"]["actions"][0] == {"type": "assign", "user_id": None}


async def test_patch_revalidates_and_versions(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    rid = await _rule(
        ravi, pid, {"type": "task.completed"}, [{"type": "add_comment", "text": "done"}]
    )
    r = await ravi.patch(f"/api/v1/rules/{rid}", json={"enabled": False, "name": "Off"})
    assert r.status_code == 200 and r.json()["data"]["enabled"] is False
    assert r.json()["data"]["version"] == 2
    stale = await ravi.patch(f"/api/v1/rules/{rid}", json={"name": "X", "expected_version": 1})
    assert stale.status_code == 409
    bad = await ravi.patch(f"/api/v1/rules/{rid}", json={"actions": [{"type": "nope"}]})
    assert bad.status_code == 422
    assert (await ravi.patch(f"/api/v1/rules/{rid}", json={"trigger": None})).status_code == 422
    assert (await ravi.delete(f"/api/v1/rules/{rid}")).status_code == 200
    assert (await ravi.get(f"/api/v1/rules/{rid}")).status_code == 404
    assert (await ravi.get(f"/api/v1/rules?project_id={pid}")).json()["data"] == []


# ---------------- permissions ----------------


async def test_managing_rules_needs_project_admin_and_workspace_rules_need_admin(
    as_user: Clients,
) -> None:
    ravi, mei, admin = await as_user("ravi"), await as_user("mei"), await as_user("admin")
    pid = await _project(ravi)
    trig, act = {"type": "task.completed"}, [{"type": "add_comment", "text": "done"}]
    body = {"name": "R", "project_id": pid, "trigger": trig, "actions": act}
    rid = await _rule(ravi, pid, trig, act)
    # mei is an editor via her team: she can look, not change
    assert (await mei.get(f"/api/v1/rules/{rid}")).status_code == 200
    assert (await mei.post("/api/v1/rules", json=body)).status_code == 403
    assert (await mei.patch(f"/api/v1/rules/{rid}", json={"enabled": False})).status_code == 403
    assert (await mei.delete(f"/api/v1/rules/{rid}")).status_code == 403
    # someone who can't see the project can't tell the rule exists
    ana = await as_user("ana")
    theirs = await _project(ana, "Q4 Launch Campaign")
    hidden = await _rule(ana, theirs, trig, act)
    assert (await ravi.get(f"/api/v1/rules/{hidden}")).status_code == 404
    assert (await ravi.get(f"/api/v1/rules?project_id={theirs}")).status_code == 404
    # workspace rules: workspace admins only
    assert (await ravi.post("/api/v1/rules", json={**body, "project_id": None})).status_code == 403
    assert (await ravi.get("/api/v1/rules")).status_code == 403
    ws = await admin.post("/api/v1/rules", json={**body, "project_id": None})
    assert ws.status_code == 201, ws.text
    assert len((await admin.get("/api/v1/rules")).json()["data"]) == 1


# ---------------- triggers, conditions, actions ----------------


async def test_moved_rule_with_condition_runs_actions_as_the_rule(
    as_user: Clients, session_factory: SessionFactory, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    pid, mei_id = await _project(ravi), await _user_id(ravi, "mei")
    sec = await _sections(ravi, pid)
    rid = await _rule(
        ravi,
        pid,
        {"type": "task.moved", "to_section": sec["Review"]},
        [
            {"type": "assign", "user_id": mei_id},
            {"type": "add_comment", "text": "Ready for review"},
        ],
        conditions=[{"field": "priority", "op": "eq", "value": "high"}],
    )
    hit = await _task(ravi, pid, sec["Backlog"], "hit", priority="high")
    miss = await _task(ravi, pid, sec["Backlog"], "miss", priority="low")
    await _move(ravi, hit, sec["Review"])
    await _move(ravi, miss, sec["Review"])
    await _move(ravi, hit, sec["Review"])  # a reorder inside the section isn't a move
    stats = await _run(session_factory, settings)
    assert (stats.success, stats.skipped, stats.failed) == (1, 0, 0)
    assert str((await _task_row(session_factory, hit)).assignee_id) == mei_id
    assert (await _task_row(session_factory, miss)).assignee_id is None
    (comment,) = await _comments(session_factory, hit)
    assert comment.created_via == "rule" and comment.is_ai is False
    assert await _comments(session_factory, miss) == []
    (run,) = await _runs(session_factory, rid)
    assert (run.status, run.depth, run.actions_run) == ("success", 0, 2)

    async def rule_activity(s: AsyncSession) -> list[Activity]:
        stmt = select(Activity).where(Activity.batch_id == run.activity_batch_id)
        return list((await s.execute(stmt)).scalars())

    acts = await _query(session_factory, rule_activity)
    assert acts and {a.actor_kind for a in acts} == {"rule"}
    runs = (await ravi.get(f"/api/v1/rules/{rid}/runs")).json()["data"]
    assert [r["status"] for r in runs] == ["success"]


async def test_other_triggers(
    as_user: Clients, session_factory: SessionFactory, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    pid, mei_id = await _project(ravi), await _user_id(ravi, "mei")
    sec = await _sections(ravi, pid)
    say = lambda t: [{"type": "add_comment", "text": t}]  # noqa: E731
    await _rule(ravi, pid, {"type": "task.added"}, say("added"))
    await _rule(ravi, pid, {"type": "task.completed"}, say("completed"))
    await _rule(ravi, pid, {"type": "task.assigned", "user_id": mei_id}, say("assigned"))
    await _rule(
        ravi,
        pid,
        {"type": "task.field_changed", "field": "priority", "to": "urgent"},
        say("urgent"),
    )
    task = await _task(ravi, pid, sec["Backlog"])
    await ravi.patch(f"/api/v1/tasks/{task}", json={"priority": "low"})
    await ravi.patch(f"/api/v1/tasks/{task}", json={"priority": "urgent"})
    await ravi.patch(f"/api/v1/tasks/{task}", json={"assignee_id": await _user_id(ravi, "tom")})
    await ravi.patch(f"/api/v1/tasks/{task}", json={"assignee_id": mei_id})
    await ravi.post(f"/api/v1/tasks/{task}/complete")
    await _run(session_factory, settings)
    texts = sorted(
        "".join(c.body_text for c in [c]) for c in await _comments(session_factory, task)
    )
    assert texts == ["added", "assigned", "completed", "urgent"]


async def test_custom_field_and_tag_conditions(
    as_user: Clients, session_factory: SessionFactory, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    sec = await _sections(ravi, pid)
    tag = (await ravi.post("/api/v1/tags", json={"name": "Urgent"})).json()["data"]["id"]
    await _rule(
        ravi,
        pid,
        {"type": "task.completed"},
        [{"type": "add_comment", "text": "tagged"}],
        conditions=[{"field": "tag", "op": "eq", "value": tag}],
    )
    tagged, plain = await _task(ravi, pid, sec["Backlog"]), await _task(ravi, pid, sec["Backlog"])
    await ravi.post(f"/api/v1/tasks/{tagged}/tags", json={"tag_id": tag})
    for t in (tagged, plain):
        await ravi.post(f"/api/v1/tasks/{t}/complete")
    await _run(session_factory, settings)
    assert len(await _comments(session_factory, tagged)) == 1
    assert await _comments(session_factory, plain) == []


@pytest.mark.parametrize(
    ("op", "actual", "expected", "want"),
    [
        ("eq", "high", "high", True),
        ("eq", None, "high", False),
        ("neq", None, "high", True),
        ("neq", "low", "high", True),
        ("in", "high", ["high", "urgent"], True),
        ("in", "low", ["high", "urgent"], False),
        ("empty", None, None, True),
        ("empty", [], None, True),
        ("empty", "x", None, False),
        ("not_empty", "x", None, True),
        ("gt", 5, 3, True),
        ("lt", 5, 3, False),
        ("gt", "2026-10-02", "2026-10-01", True),
        ("lt", "2026-09-30", "2026-10-01", True),
        ("gt", None, 3, False),
        ("gt", "a", 3, False),
        ("gt", True, 0, False),
        ("eq", ["a", "b"], "a", True),
        ("neq", ["a", "b"], "a", False),
        ("in", ["a", "b"], ["c", "b"], True),
        ("gt", ["a"], "a", False),
    ],
)
def test_compare(op: str, actual: Any, expected: Any, want: bool) -> None:
    assert compare(op, actual, expected) is want


async def test_failed_run_rolls_back_all_of_its_actions(
    as_user: Clients, session_factory: SessionFactory, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    sec = await _sections(ravi, pid)
    rid = await _rule(
        ravi,
        pid,
        {"type": "task.completed"},
        [
            {"type": "add_comment", "text": "first"},
            {"type": "move_section", "section_id": sec["Done"]},
        ],
    )
    assert (await ravi.delete(f"/api/v1/sections/{sec['Done']}")).status_code == 200
    task = await _task(ravi, pid, sec["Backlog"])
    await ravi.post(f"/api/v1/tasks/{task}/complete")
    stats = await _run(session_factory, settings)
    assert (stats.success, stats.failed) == (0, 1)
    (run,) = await _runs(session_factory, rid)
    assert run.status == "failed" and run.error and run.actions_run == 0
    assert await _comments(session_factory, task) == []  # the first action was undone with it


async def test_rule_of_a_disabled_author_fails_instead_of_acting(
    as_user: Clients, session_factory: SessionFactory, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    sec = await _sections(ravi, pid)
    rid = await _rule(ravi, pid, {"type": "task.completed"}, [{"type": "add_comment", "text": "x"}])
    task = await _task(ravi, pid, sec["Backlog"])
    await ravi.post(f"/api/v1/tasks/{task}/complete")

    async def disable(s: AsyncSession) -> None:
        noor = (
            await s.execute(select(User).where(User.email == "noor@acme-demo.test"))
        ).scalar_one()
        noor.status = "disabled"
        await s.execute(update(Rule).where(Rule.id == uuid.UUID(rid)).values(created_by=noor.id))
        await s.commit()

    await _query(session_factory, disable)
    stats = await _run(session_factory, settings)
    assert stats.failed == 1
    assert "no longer active" in (await _runs(session_factory, rid))[0].error  # type: ignore[operator]
    assert await _comments(session_factory, task) == []


# ---------------- loop protection ----------------


async def _chain(ravi: httpx.AsyncClient) -> tuple[str, dict[str, str], list[str]]:
    """Rules S1 → S2 → S3 → S1: entering a section pushes the task on to the next one."""
    pid = await _project(ravi)
    sec = await _sections(ravi, pid)
    names = ["Backlog", "In progress", "Review"]
    rules = []
    for here, nxt in zip(names, [*names[1:], names[0]], strict=True):
        rules.append(
            await _rule(
                ravi,
                pid,
                {"type": "task.moved", "to_section": sec[here]},
                [{"type": "move_section", "section_id": sec[nxt]}],
            )
        )
    return pid, sec, rules


async def test_rule_chain_stops_at_depth_three_with_a_logged_skip(
    as_user: Clients, session_factory: SessionFactory, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    pid, sec, rules = await _chain(ravi)
    task = await _task(ravi, pid, sec["Done"])
    await _move(ravi, task, sec["Backlog"])  # the person's move: depth 0
    stats = await _run(session_factory, settings)
    assert (stats.success, stats.skipped, stats.failed) == (MAX_DEPTH, 1, 0)
    # A → B → C → A: each rule ran once, and the fourth hop (rule 1 again) was refused
    by_rule = [await _runs(session_factory, r) for r in rules]
    assert [[(r.status, r.depth) for r in runs] for runs in by_rule] == [
        [("success", 0), ("skipped", 3)],
        [("success", 1)],
        [("success", 2)],
    ]
    skipped = by_rule[0][1]
    assert skipped.actions_run == 0 and "3 rule steps deep" in (skipped.error or "")
    # the task moved 3 times on its own and then stopped: it sits where the last hop put it
    assert (await _task_row(session_factory, task)).version >= 1

    async def depths(s: AsyncSession) -> list[int]:
        stmt = (
            select(OutboxEvent)
            .where(OutboxEvent.type == "task.moved", OutboxEvent.entity_id == uuid.UUID(task))
            .order_by(OutboxEvent.id)
        )
        return [e.payload["depth"] for e in (await s.execute(stmt)).scalars()][-4:]

    assert await _query(session_factory, depths) == [0, 1, 2, 3]
    # nothing is left to do: another pass is a no-op
    again = await _run(session_factory, settings)
    assert (again.success, again.skipped, again.failed) == (0, 0, 0)


async def test_rule_events_carry_the_depth_of_the_run_that_caused_them(
    as_user: Clients, session_factory: SessionFactory, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    sec = await _sections(ravi, pid)
    await _rule(ravi, pid, {"type": "task.completed"}, [{"type": "add_comment", "text": "x"}])
    task = await _task(ravi, pid, sec["Backlog"])
    await ravi.post(f"/api/v1/tasks/{task}/complete")
    await _run(session_factory, settings)

    async def events(s: AsyncSession) -> dict[str, list[tuple[int, str]]]:
        out: dict[str, list[tuple[int, str]]] = {}
        for e in (await s.execute(select(OutboxEvent).order_by(OutboxEvent.id))).scalars():
            out.setdefault(e.type, []).append((e.payload["depth"], e.payload["actor"]["kind"]))
        return out

    ev = await _query(session_factory, events)
    assert ev["task.completed"] == [(0, "user")]
    assert ev["comment.created"] == [(1, "rule")]
    assert ev["rule.ran"] == [(1, "rule")]


async def test_a_rule_never_fires_twice_on_one_event(
    as_user: Clients, session_factory: SessionFactory, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    sec = await _sections(ravi, pid)
    rid = await _rule(ravi, pid, {"type": "task.completed"}, [{"type": "add_comment", "text": "x"}])
    task = await _task(ravi, pid, sec["Backlog"])
    await ravi.post(f"/api/v1/tasks/{task}/complete")
    await _run(session_factory, settings)

    async def rewind(s: AsyncSession) -> None:
        await s.execute(
            update(ConsumerOffset)
            .where(ConsumerOffset.consumer == CONSUMER)
            .values(last_event_id=0)
        )
        await s.commit()

    await _query(session_factory, rewind)  # the same events are delivered again
    stats = await _run(session_factory, settings)
    assert stats.success == 0
    assert len(await _runs(session_factory, rid)) == 1
    assert len(await _comments(session_factory, task)) == 1


async def test_rate_limit_per_project_per_minute(
    as_user: Clients, session_factory: SessionFactory, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    sec = await _sections(ravi, pid)
    rid = await _rule(ravi, pid, {"type": "task.completed"}, [{"type": "add_comment", "text": "x"}])
    workspace_id = (
        await _task_row(session_factory, await _task(ravi, pid, sec["Backlog"]))
    ).workspace_id

    async def busy(s: AsyncSession, ago: timedelta) -> None:
        s.add(
            RuleRun(
                workspace_id=workspace_id,
                rule_id=uuid.UUID(rid),
                project_id=uuid.UUID(pid),
                outbox_event_id=-1 - int(ago.total_seconds()),
                status="success",
                actions_run=MAX_ACTIONS_PER_MINUTE,
                started_at=datetime.now(UTC) - ago,
                finished_at=datetime.now(UTC) - ago,
            )
        )
        await s.commit()

    # 50 actions a minute ago: this minute is full
    await _query(session_factory, lambda s: busy(s, timedelta(seconds=5)))
    t1 = await _task(ravi, pid, sec["Backlog"])
    await ravi.post(f"/api/v1/tasks/{t1}/complete")
    stats = await _run(session_factory, settings)
    assert (stats.success, stats.skipped) == (0, 1)
    assert await _comments(session_factory, t1) == []
    skipped = [r for r in await _runs(session_factory, rid) if r.status == "skipped"]
    assert len(skipped) == 1 and "a minute" in (skipped[0].error or "")

    # older than a minute no longer counts
    async def age(s: AsyncSession) -> None:
        stale = datetime.now(UTC) - timedelta(minutes=2)
        await s.execute(
            update(RuleRun).where(RuleRun.status == "success").values(finished_at=stale)
        )
        await s.commit()

    await _query(session_factory, age)
    t2 = await _task(ravi, pid, sec["Backlog"])
    await ravi.post(f"/api/v1/tasks/{t2}/complete")
    assert (await _run(session_factory, settings)).success == 1
    assert len(await _comments(session_factory, t2)) == 1


async def test_kill_switch_drops_events_instead_of_replaying_them(
    as_user: Clients, session_factory: SessionFactory, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    sec = await _sections(ravi, pid)
    rid = await _rule(ravi, pid, {"type": "task.completed"}, [{"type": "add_comment", "text": "x"}])
    task = await _task(ravi, pid, sec["Backlog"])
    await ravi.post(f"/api/v1/tasks/{task}/complete")
    off = settings.model_copy(update={"rules_enabled": False})
    assert (await _run(session_factory, off)).success == 0
    assert (await _run(session_factory, settings)).success == 0  # switched back on: no backlog
    assert await _runs(session_factory, rid) == []


async def test_a_rule_ignores_events_from_before_it_existed_and_while_disabled_or_deleted(
    as_user: Clients, session_factory: SessionFactory, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    sec = await _sections(ravi, pid)
    task = await _task(ravi, pid, sec["Backlog"])
    await ravi.post(f"/api/v1/tasks/{task}/complete")  # happens before any rule exists
    early = await _rule(
        ravi, pid, {"type": "task.completed"}, [{"type": "add_comment", "text": "a"}]
    )
    off = await _rule(
        ravi, pid, {"type": "task.completed"}, [{"type": "add_comment", "text": "b"}], enabled=False
    )
    gone = await _rule(
        ravi, pid, {"type": "task.completed"}, [{"type": "add_comment", "text": "c"}]
    )
    await ravi.delete(f"/api/v1/rules/{gone}")
    stats = await _run(session_factory, settings)
    assert stats.success == 0
    for rid in (early, off, gone):
        assert await _runs(session_factory, rid) == []


async def test_project_scope_and_multi_homed_tasks(
    as_user: Clients, session_factory: SessionFactory, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    ana = await as_user("ana")
    pid, other = await _project(ravi), await _project(ana, "Q4 Launch Campaign")
    sec = await _sections(ravi, pid)
    rid = await _rule(
        ana, other, {"type": "task.completed"}, [{"type": "add_comment", "text": "x"}]
    )
    task = await _task(ravi, pid, sec["Backlog"])
    await ravi.post(f"/api/v1/tasks/{task}/complete")
    await _run(session_factory, settings)
    assert await _runs(session_factory, rid) == []  # the task isn't in that rule's project
