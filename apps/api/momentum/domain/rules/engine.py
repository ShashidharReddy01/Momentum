"""S4.1.1: the rules executor. An outbox consumer (its own ``consumer_offsets`` row, ``rules``):
for each task event it finds the enabled rules whose trigger and conditions match, and runs their
actions through the ordinary services as the rule's author with ``via="rule"``.

**Loop protection** (the reason this module is careful):
- Every event carries a ``depth`` (``Ctx.rule_depth``, stamped by ``core.events.emit``): 0 for a
  person's change, and events caused by a rule's actions carry the triggering event's depth + 1.
  A rule that would fire on an event of depth ``MAX_DEPTH`` or more doesn't; it records a
  ``skipped`` run and logs it, so a chain A → B → C → A stops after three hops.
- At most ``MAX_ACTIONS_PER_MINUTE`` rule actions per project per minute.
- ``(rule_id, outbox_event_id)`` is unique: a rule never fires twice on one event.

One action is different: ``ai_step`` (S4.1.5) is **queued**, not run — it writes a
``rule_ai_steps`` row and ``momentum/ai/rule_steps.py`` performs it on the ``ai`` queue a moment
later, because a model call must not be made inside the run's transaction. The run counts it as
an action it queued; the step keeps its own status.

A run is all or nothing: its actions share a savepoint, so a failing action leaves no partial
change behind (the ``failed`` run keeps the error), and a queued AI step goes with it. The whole
batch shares one transaction with the cursor, so a crash replays events without repeating any
effect.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import Activity
from momentum.core.context import Actor, Ctx
from momentum.core.errors import Forbidden
from momentum.core.events import ConsumerOffset, OutboxEvent, emit
from momentum.core.settings import Settings
from momentum.core.telemetry import get_logger
from momentum.domain.comments.service import create_comment
from momentum.domain.fields.models import FieldValue
from momentum.domain.fields.service import set_task_field_value
from momentum.domain.notifications.service import notify
from momentum.domain.rules.models import Rule, RuleAiStep, RuleRun
from momentum.domain.sections.models import Section
from momentum.domain.tags.models import TaskTag
from momentum.domain.tags.service import add_task_tag
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.tasks.service import (
    add_task_to_project,
    create_subtask,
    move_tasks,
    remove_task_from_project,
    set_completed,
    today_for,
    update_task,
)
from momentum.domain.users.models import User

log = get_logger("rules")

CONSUMER = "rules"
MAX_DEPTH = 3
MAX_ACTIONS_PER_MINUTE = 50

# trigger type -> the outbox event types it can fire on
TRIGGER_EVENTS: dict[str, tuple[str, ...]] = {
    "task.added": ("task.created", "task.added_to_project"),
    "task.moved": ("task.moved",),
    "task.field_changed": ("task.updated", "task.field_updated"),
    "task.completed": ("task.completed",),
    "task.assigned": ("task.assigned",),
    "task.due_approaching": ("task.due_approaching",),
    "form.submitted": ("form.submitted",),
    "approval.decided": ("approval.decided",),
}
WATCHED = {e for events in TRIGGER_EVENTS.values() for e in events}


@dataclass
class RulesRun:
    events: int = 0
    success: int = 0
    skipped: int = 0
    failed: int = 0


# ---------------- actions ----------------

ActionFn = Callable[[AsyncSession, Ctx, uuid.UUID, dict[str, Any], uuid.UUID], Awaitable[None]]


def _text_doc(text: str) -> dict[str, Any]:
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": line}]}
            for line in lines
            if line
        ],
    }


async def _assign(
    session: AsyncSession, ctx: Ctx, task_id: uuid.UUID, spec: dict[str, Any], batch: uuid.UUID
) -> None:
    await update_task(session, ctx, task_id, {"assignee_id": spec.get("user_id")}, batch_id=batch)


async def _add_comment(
    session: AsyncSession, ctx: Ctx, task_id: uuid.UUID, spec: dict[str, Any], batch: uuid.UUID
) -> None:
    await create_comment(session, ctx, task_id, _text_doc(str(spec["text"])))


async def _move_section(
    session: AsyncSession, ctx: Ctx, task_id: uuid.UUID, spec: dict[str, Any], batch: uuid.UUID
) -> None:
    await move_tasks(
        session, ctx, [task_id], section_id=uuid.UUID(str(spec["section_id"])), batch_id=batch
    )


async def _mark_complete(
    session: AsyncSession, ctx: Ctx, task_id: uuid.UUID, spec: dict[str, Any], batch: uuid.UUID
) -> None:
    await set_completed(session, ctx, task_id, True, batch_id=batch)


async def _set_field(
    session: AsyncSession, ctx: Ctx, task_id: uuid.UUID, spec: dict[str, Any], batch: uuid.UUID
) -> None:
    field_id = str(spec["field_id"])
    if field_id == "priority":
        await update_task(session, ctx, task_id, {"priority": spec.get("value")}, batch_id=batch)
    else:
        await set_task_field_value(session, ctx, task_id, uuid.UUID(field_id), spec.get("value"))


async def _add_to_project(
    session: AsyncSession, ctx: Ctx, task_id: uuid.UUID, spec: dict[str, Any], batch: uuid.UUID
) -> None:
    section_id = spec.get("section_id")
    await add_task_to_project(
        session,
        ctx,
        task_id,
        uuid.UUID(str(spec["project_id"])),
        section_id=uuid.UUID(str(section_id)) if section_id else None,
    )


async def _remove_from_project(
    session: AsyncSession, ctx: Ctx, task_id: uuid.UUID, spec: dict[str, Any], batch: uuid.UUID
) -> None:
    await remove_task_from_project(session, ctx, task_id, uuid.UUID(str(spec["project_id"])))


async def _add_tag(
    session: AsyncSession, ctx: Ctx, task_id: uuid.UUID, spec: dict[str, Any], batch: uuid.UUID
) -> None:
    await add_task_tag(session, ctx, task_id, uuid.UUID(str(spec["tag_id"])), None)


async def _create_subtasks(
    session: AsyncSession, ctx: Ctx, task_id: uuid.UUID, spec: dict[str, Any], batch: uuid.UUID
) -> None:
    for title in spec["titles"]:
        await create_subtask(session, ctx, task_id, str(title), batch_id=batch)


async def _set_due_relative(
    session: AsyncSession, ctx: Ctx, task_id: uuid.UUID, spec: dict[str, Any], batch: uuid.UUID
) -> None:
    due = today_for(ctx) + timedelta(days=int(spec["days"]))
    await update_task(session, ctx, task_id, {"due_on": due.isoformat()}, batch_id=batch)


async def _notify_user(
    session: AsyncSession, ctx: Ctx, task_id: uuid.UUID, spec: dict[str, Any], batch: uuid.UUID
) -> None:
    user_id = spec.get("user_id")
    await notify(
        session,
        ctx,
        user_id=uuid.UUID(str(user_id)) if user_id else None,
        kind="rule",
        entity_type="task",
        entity_id=task_id,
        title=str(spec["text"])[:300],
    )


async def _queue_ai_step(
    session: AsyncSession,
    ctx: Ctx,
    rule: Rule,
    run_id: uuid.UUID,
    project_id: uuid.UUID | None,
    task_id: uuid.UUID,
    spec: dict[str, Any],
    batch: uuid.UUID,
) -> None:
    """S4.1.5: hand the step to the ``ai`` queue instead of calling a model here.

    A gateway call takes seconds, and this runs inside the run's savepoint — the executor must
    not hold a write transaction open across it. The row is written inside that savepoint, so a
    run that fails later queues nothing; ``momentum/ai/rule_steps.py`` picks it up within a
    minute and does the AI write as the rule's author, marked as AI.
    """
    field_id = spec.get("field_id")
    session.add(
        RuleAiStep(
            workspace_id=rule.workspace_id,
            rule_id=rule.id,
            rule_run_id=run_id,
            project_id=project_id,
            task_id=task_id,
            kind=str(spec["kind"]),
            field_id=str(field_id) if field_id else None,
            status="queued",
            depth=ctx.rule_depth,
            activity_batch_id=batch,
        )
    )
    await session.flush()


ACTIONS: dict[str, ActionFn] = {
    "assign": _assign,
    "add_comment": _add_comment,
    "move_section": _move_section,
    "mark_complete": _mark_complete,
    "set_field": _set_field,
    "add_to_project": _add_to_project,
    "remove_from_project": _remove_from_project,
    "add_tag": _add_tag,
    "create_subtasks": _create_subtasks,
    "set_due_relative": _set_due_relative,
    "notify_user": _notify_user,
}


# ---------------- matching ----------------


async def _field_value(session: AsyncSession, task: Task, field: str) -> Any:
    if field == "priority":
        return task.priority
    if field == "assignee":
        return str(task.assignee_id) if task.assignee_id else None
    if field in ("due_on", "start_on"):
        day = getattr(task, field)
        return day.isoformat() if day else None
    if field == "tag":
        rows = await session.execute(select(TaskTag.tag_id).where(TaskTag.task_id == task.id))
        return sorted(str(t) for (t,) in rows)
    row = await session.get(FieldValue, (task.id, uuid.UUID(field)))
    return row.value if row else None


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def compare(op: str, actual: Any, expected: Any) -> bool:
    if op == "empty":
        return _is_empty(actual)
    if op == "not_empty":
        return not _is_empty(actual)
    if isinstance(actual, list):  # tags and multi-value fields: "has"
        if op == "eq":
            return expected in actual
        if op == "neq":
            return expected not in actual
        if op == "in":
            return any(e in actual for e in expected)
        return False
    if op == "eq":
        return bool(actual == expected)
    if op == "neq":
        return bool(actual != expected)
    if op == "in":
        return actual in expected
    numbers = all(
        isinstance(v, int | float) and not isinstance(v, bool) for v in (actual, expected)
    )
    strings = isinstance(actual, str) and isinstance(expected, str)  # ISO dates order as text
    if op in ("gt", "lt") and (numbers or strings):
        return bool(actual > expected if op == "gt" else actual < expected)
    return False


async def _conditions_pass(session: AsyncSession, rule: Rule, task: Task) -> bool:
    for c in rule.conditions:
        actual = await _field_value(session, task, c["field"])
        if not compare(c["op"], actual, c.get("value")):
            return False
    return True


async def _trigger_matches(session: AsyncSession, trig: dict[str, Any], ev: OutboxEvent) -> bool:
    kind = trig["type"]
    if ev.type not in TRIGGER_EVENTS.get(kind, ()):
        return False
    data: dict[str, Any] = ev.payload.get("data") or {}
    if kind == "task.added":
        return bool(data.get("project_id"))  # a subtask's creation names a parent, not a project
    if kind == "task.moved":
        act = await session.get(Activity, ev.activity_id) if ev.activity_id else None
        if act is None or "section_id" not in act.diff:  # a reorder inside a section isn't a move
            return False
        return trig.get("to_section") in (None, data.get("section_id"))
    if kind == "task.field_changed":
        field = trig["field"]
        if ev.type == "task.updated":
            pair = (data.get("changes") or {}).get(field)
            if pair is None:
                return False
            new = pair[1]
        else:
            if data.get("field_id") != field:
                return False
            row = await session.get(FieldValue, (ev.entity_id, uuid.UUID(field)))
            new = row.value if row else None
        return "to" not in trig or bool(new == trig["to"])
    if kind == "task.assigned":
        assignee = data.get("assignee_id")
        return bool(assignee is not None and trig.get("user_id") in (None, assignee))
    if kind == "form.submitted":
        form_id = trig.get("form_id")
        return form_id is None or form_id == data.get("form_id")
    if kind == "approval.decided":
        decision = trig.get("decision")
        return decision is None or decision == data.get("state")
    return kind in ("task.completed", "task.due_approaching")


async def _event_projects(session: AsyncSession, ev: OutboxEvent) -> set[uuid.UUID]:
    """The projects an event happened in (a task can live in several)."""
    data: dict[str, Any] = ev.payload.get("data") or {}
    if data.get("project_id"):
        return {uuid.UUID(str(data["project_id"]))}
    if data.get("section_id"):
        section = await session.get(Section, uuid.UUID(str(data["section_id"])))
        return {section.project_id} if section else set()
    rows = await session.execute(
        select(TaskProject.project_id).where(TaskProject.task_id == ev.entity_id)
    )
    return {p for (p,) in rows}


# ---------------- running ----------------


async def _actions_used_last_minute(session: AsyncSession, project_id: uuid.UUID | None) -> int:
    since = datetime.now(UTC) - timedelta(minutes=1)
    stmt = select(func.coalesce(func.sum(RuleRun.actions_run), 0)).where(
        RuleRun.finished_at >= since,
        RuleRun.project_id == project_id if project_id else RuleRun.project_id.is_(None),
    )
    return int((await session.execute(stmt)).scalar_one())


def _rule_ctx(
    user: User | None, rule: Rule, ev: OutboxEvent, settings: Settings, depth: int
) -> Ctx:
    actor = (
        Actor(
            id=user.id,
            workspace_id=user.workspace_id,
            role=user.role,
            is_agent=user.is_agent,
            email=user.email,
            name=user.name,
            timezone=user.timezone,
        )
        if user is not None
        else Actor(id=rule.created_by, workspace_id=rule.workspace_id)
    )
    return Ctx(
        actor=actor,
        settings=settings,
        via="rule",
        request_id=f"rule:{rule.id}:{ev.id}",
        rule_depth=depth + 1,
    )


async def _fire(
    session: AsyncSession,
    settings: Settings,
    rule: Rule,
    ev: OutboxEvent,
    project_id: uuid.UUID | None,
    stats: RulesRun,
) -> None:
    """Record one run of ``rule`` for ``ev``: skipped (depth, rate) or executed."""
    depth = int((ev.payload or {}).get("depth", 0))
    started = datetime.now(UTC)
    user = await session.get(User, rule.created_by)
    ctx = _rule_ctx(user, rule, ev, settings, depth)
    status, error, ran = "success", None, 0
    batch_id = uuid.uuid4()
    # The row is inserted before the actions run so a queued AI step (S4.1.5) can point at it;
    # its outcome is filled in at the end. Core insert/update rather than the ORM: the actions
    # run in a savepoint whose rollback would expire an ORM instance, and an expired instance
    # can't be assigned to from async code without a reload.
    run_id = uuid.uuid4()
    await session.execute(
        insert(RuleRun).values(
            id=run_id,
            workspace_id=rule.workspace_id,
            rule_id=rule.id,
            project_id=project_id,
            outbox_event_id=ev.id,
            status="failed",
            depth=depth,
            actions_run=0,
            started_at=started,
        )
    )
    if depth >= MAX_DEPTH:
        status, error = (
            "skipped",
            f"Stopped: this change is {depth} rule steps deep (max {MAX_DEPTH})",
        )
        log.warning(
            "rule_skipped", reason="max_depth", rule_id=str(rule.id), event_id=ev.id, depth=depth
        )
    elif (
        await _actions_used_last_minute(session, project_id) + len(rule.actions)
        > MAX_ACTIONS_PER_MINUTE
    ):
        status, error = (
            "skipped",
            f"Stopped: more than {MAX_ACTIONS_PER_MINUTE} rule actions a minute",
        )
        log.warning("rule_skipped", reason="rate_limit", rule_id=str(rule.id), event_id=ev.id)
    else:
        try:
            if user is None or user.status != "active":
                raise Forbidden("The person who created this rule is no longer active")
            async with session.begin_nested():
                for spec in rule.actions:
                    if spec["type"] == "ai_step":
                        await _queue_ai_step(
                            session, ctx, rule, run_id, project_id, ev.entity_id, spec, batch_id
                        )
                    else:
                        await ACTIONS[spec["type"]](session, ctx, ev.entity_id, spec, batch_id)
                    ran += 1
        except Exception as e:  # a rule must never take the executor down; the run keeps the error
            status, error, ran = "failed", (str(e) or type(e).__name__)[:500], 0
            log.warning("rule_failed", rule_id=str(rule.id), event_id=ev.id, error=error)
    await session.execute(
        update(RuleRun)
        .where(RuleRun.id == run_id)
        .values(
            status=status,
            error=error,
            actions_run=ran,
            finished_at=datetime.now(UTC),
            activity_batch_id=batch_id if ran else None,
        )
    )
    await session.flush()
    await emit(
        session,
        ctx,
        type="rule.ran",
        entity_type="rule",
        entity_id=rule.id,
        data={"rule_id": str(rule.id), "status": status, "task_id": str(ev.entity_id)},
        channels=[f"project:{project_id}"] if project_id else [f"workspace:{rule.workspace_id}"],
    )
    setattr(stats, status, getattr(stats, status) + 1)


async def _handle(
    session: AsyncSession,
    settings: Settings,
    rules: list[Rule],
    ev: OutboxEvent,
    stats: RulesRun,
) -> None:
    if ev.type not in WATCHED or ev.entity_type != "task":
        return
    candidates = [
        r for r in rules if r.workspace_id == ev.workspace_id and r.created_at <= ev.created_at
    ]
    if not candidates:
        return
    task = await session.get(Task, ev.entity_id)
    if task is None or task.deleted_at is not None:
        return
    projects = await _event_projects(session, ev)
    for rule in candidates:
        if rule.project_id is not None and rule.project_id not in projects:
            continue
        try:
            if not await _trigger_matches(session, rule.trigger, ev):
                continue
            if not await _conditions_pass(session, rule, task):
                continue
        except (KeyError, ValueError, TypeError) as e:  # stored JSON that no longer fits the schema
            log.warning("rule_invalid", rule_id=str(rule.id), error=str(e))
            continue
        seen = await session.execute(
            select(RuleRun.id).where(RuleRun.rule_id == rule.id, RuleRun.outbox_event_id == ev.id)
        )
        if seen.first() is not None:  # this rule already handled this event
            continue
        project_id = rule.project_id or (min(projects) if projects else None)
        await _fire(session, settings, rule, ev, project_id, stats)


@dataclass
class ActionResult:
    type: str
    ok: bool
    error: str | None


@dataclass
class TestRunResult:
    conditions_passed: bool
    actions: list[ActionResult]


async def test_run(
    session: AsyncSession, settings: Settings, rule: Rule, task: Task
) -> TestRunResult:
    """Preview ``rule`` against ``task`` for the builder's "test run": conditions are checked,
    then (if they pass) each action runs as the rule's author inside its own savepoint that's
    always rolled back, so nothing is persisted and a later action still gets tried even if an
    earlier one would fail. Not a real run: no ``RuleRun`` row, no ``rule.ran`` event."""
    conditions_passed = await _conditions_pass(session, rule, task)
    results: list[ActionResult] = []
    if conditions_passed:
        user = await session.get(User, rule.created_by)
        actor = (
            Actor(
                id=user.id,
                workspace_id=user.workspace_id,
                role=user.role,
                is_agent=user.is_agent,
                email=user.email,
                name=user.name,
                timezone=user.timezone,
            )
            if user is not None
            else Actor(id=rule.created_by, workspace_id=rule.workspace_id)
        )
        ctx = Ctx(
            actor=actor,
            settings=settings,
            via="rule",
            request_id=f"rule-test:{rule.id}",
            rule_depth=MAX_DEPTH,  # rolled back regardless; belt and suspenders against chaining
        )
        task_id = task.id
        for spec in rule.actions:
            if spec["type"] == "ai_step":
                # An AI step is queued, not run, so there is nothing to preview: saying it would
                # run is honest (the real run queues it) and no model call is made or charged.
                results.append(ActionResult(f"ai_step: {spec.get('kind')}", True, None))
                continue
            savepoint = await session.begin_nested()
            try:
                await ACTIONS[spec["type"]](session, ctx, task_id, spec, uuid.uuid4())
                results.append(ActionResult(spec["type"], True, None))
            except Exception as e:  # a preview must never raise; the row records the error
                error = (str(e) or type(e).__name__)[:500]
                results.append(ActionResult(spec["type"], False, error))
            finally:
                await savepoint.rollback()
    return TestRunResult(conditions_passed, results)


async def _cursor(session: AsyncSession) -> ConsumerOffset:
    row = (
        await session.execute(
            select(ConsumerOffset).where(ConsumerOffset.consumer == CONSUMER).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        row = ConsumerOffset(consumer=CONSUMER, last_event_id=0)
        session.add(row)
        await session.flush()
    return row


async def run_rules(
    session: AsyncSession, settings: Settings, *, batch: int = 200, max_batches: int = 50
) -> RulesRun:
    """Process outbox events after the cursor. The caller commits. Events that rules cause land
    after the cursor and are picked up by the next batch of the same run (bounded by
    ``max_batches``; loop protection stops chains long before that)."""
    stats = RulesRun()
    cursor = await _cursor(session)
    if not settings.rules_enabled:  # a kill switch drops what happened meanwhile, never replays it
        newest = (await session.execute(select(func.max(OutboxEvent.id)))).scalar_one()
        cursor.last_event_id = max(cursor.last_event_id, newest or 0)
        return stats
    for _ in range(max_batches):
        events = list(
            (
                await session.execute(
                    select(OutboxEvent)
                    .where(OutboxEvent.id > cursor.last_event_id)
                    .order_by(OutboxEvent.id)
                    .limit(batch)
                )
            ).scalars()
        )
        if not events:
            break
        rules = list(
            (
                await session.execute(
                    select(Rule).where(Rule.enabled.is_(True), Rule.deleted_at.is_(None))
                )
            ).scalars()
        )
        for ev in events:
            if rules:
                await _handle(session, settings, rules, ev, stats)
            cursor.last_event_id = ev.id
            stats.events += 1
    await session.flush()
    return stats
