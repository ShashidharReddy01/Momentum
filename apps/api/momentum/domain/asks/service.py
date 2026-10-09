"""Phase 7.6 S76-03 (spec §5): asks, an agent's questions to people.

- **Create** only from a job (``momentum.sdk.Job.ask``, inside the job engine): the people who may
  answer are resolved from the route (``requester``, ``project_owner``, ``approver``,
  ``stewards``, ``admins``, ``person:<id>``, ``field:<name>``), never guests and only people who can
  see the task; a route that resolves to nobody falls back to the project owner, then the
  workspace admins, and the fallback is recorded. The ask is posted in the task's thread as the
  agent's comment carrying an ``askCard`` node, and each person gets an ``agent_ask``
  notification.
- **Answer** (card, thread, inbox, API): only the people it's for, validated per kind; the waiting
  job is queued. Undoable while the job hasn't consumed the answer.
- **Timers** (``ask_timers``, every 5 minutes): a reminder at ``remind_at`` (counted in working
  hours, Monday to Friday) and a second at half of the remaining time; at ``expires_at`` the ask's
  ``default_on_expiry`` applies (a value, escalate to the next route up, route_to_review, fail).
- **Cancel** when the job ends.

Each records activity and outbox (``ask.created``, ``ask.answered``, ``ask.expired``,
``ask.cancelled``, ``ask.escalated``).
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import Activity, record_activity
from momentum.core.context import Actor, Ctx
from momentum.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from momentum.core.events import emit
from momentum.core.settings import Settings
from momentum.core.undo import UndoConflict, undo_handler, undo_op
from momentum.domain.access import get_visible_task
from momentum.domain.agents.models import Agent, AgentRun, AgentRunStep
from momentum.domain.asks.models import Ask
from momentum.domain.asks.schemas import (
    AskAgentOut,
    AskOut,
    AskPersonOut,
    AskSpec,
    validate_answer,
)
from momentum.domain.comments.service import create_comment
from momentum.domain.fields.models import FieldDef, FieldValue
from momentum.domain.notifications.service import notify
from momentum.domain.projects.models import Project
from momentum.domain.tasks.models import TaskProject
from momentum.domain.users.models import User

ESCALATION = ("project_owner", "admins")
MAX_REMINDERS = 2
YES = {"yes", "y", "yep", "yes please", "ok", "okay", "confirm", "confirmed", "approve", "go ahead"}
NO = {"no", "n", "nope", "no thanks", "cancel", "don't", "do not", "stop"}


# ---------------------------------------------------------------- who an ask is for


def person_ctx(user: User, settings: Settings) -> Ctx:
    return Ctx(
        actor=Actor(
            id=user.id,
            workspace_id=user.workspace_id,
            role=user.role,
            email=user.email,
            name=user.name,
            timezone=user.timezone,
        ),
        settings=settings,
    )


async def _can_answer(session: AsyncSession, user: User, task_id: uuid.UUID, s: Settings) -> bool:
    if user.is_agent or user.status != "active" or user.role == "guest":
        return False
    try:
        await get_visible_task(session, person_ctx(user, s), task_id)
    except NotFound:
        return False
    return True


async def _route_users(
    session: AsyncSession,
    route: str,
    *,
    workspace_id: uuid.UUID,
    task_id: uuid.UUID,
    project_id: uuid.UUID | None,
    requested_by: uuid.UUID | None,
    pack_key: str | None = None,
) -> list[uuid.UUID]:
    if route in ("approver", "stewards") and pack_key:
        from momentum.domain.pack_settings.service import people

        return await people(
            session,
            workspace_id,
            pack_key,
            "approvers" if route == "approver" else "stewards",
            project_id,
        )
    if route == "requester":
        return [requested_by] if requested_by else []
    if route == "project_owner":
        project = await session.get(Project, project_id) if project_id else None
        return [project.owner_id] if project is not None and project.owner_id else []
    if route == "admins":
        rows = await session.execute(
            select(User.id)
            .where(User.workspace_id == workspace_id, User.role == "admin", User.status == "active")
            .order_by(User.name)
        )
        return list(rows.scalars())
    if route.startswith("person:"):
        return [uuid.UUID(route.split(":", 1)[1])]
    if route.startswith("field:") and project_id is not None:
        name = route.split(":", 1)[1].strip().casefold()
        value = (
            await session.execute(
                select(FieldValue.value)
                .join(FieldDef, FieldDef.id == FieldValue.field_id)
                .where(
                    FieldValue.task_id == task_id,
                    FieldDef.type == "people",
                    FieldDef.workspace_id == workspace_id,
                )
                .where(FieldDef.name.ilike(name))
            )
        ).scalar_one_or_none()
        raw = value if isinstance(value, list) else [value] if value else []
        out = []
        for x in raw:
            try:
                out.append(uuid.UUID(str(x)))
            except ValueError:
                continue
        return out
    return []  # a pack without approvers or stewards set: the route falls back


async def resolve_route(
    session: AsyncSession,
    settings: Settings,
    route: str,
    *,
    workspace_id: uuid.UUID,
    task_id: uuid.UUID,
    project_id: uuid.UUID | None,
    requested_by: uuid.UUID | None,
    pack_key: str | None = None,
) -> tuple[list[uuid.UUID], str | None]:
    """The people who may answer, and the fallback route used when ``route`` gave nobody."""
    if project_id is None:  # the task's home project
        project_id = await session.scalar(
            select(TaskProject.project_id).where(TaskProject.task_id == task_id).limit(1)
        )
    for candidate in (route, *[r for r in ESCALATION if r != route]):
        ids = await _route_users(
            session,
            candidate,
            workspace_id=workspace_id,
            task_id=task_id,
            project_id=project_id,
            requested_by=requested_by,
            pack_key=pack_key,
        )
        people = []
        for uid in dict.fromkeys(ids):
            user = await session.get(User, uid)
            if (
                user is not None
                and user.workspace_id == workspace_id
                and await _can_answer(session, user, task_id, settings)
            ):
                people.append(user.id)
        if people:
            return people, None if candidate == route else candidate
    raise Conflict("Nobody can answer this question", code="no_one_to_ask")


# ---------------------------------------------------------------- time


def add_working_hours(start: datetime, hours: float, tz: str = "UTC") -> datetime:
    """``start`` plus ``hours`` counted on working days only (Monday to Friday, in ``tz``)."""
    zone = ZoneInfo(tz)
    at = start.astimezone(zone)
    left = timedelta(hours=hours)
    while left > timedelta(0):
        if at.weekday() >= 5:  # jump to the next Monday 00:00
            at = (at + timedelta(days=7 - at.weekday())).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            continue
        midnight = (at + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        step = min(left, midnight - at)
        at += step
        left -= step
    return at.astimezone(UTC)


# ---------------------------------------------------------------- create


def _card_doc(ask: Ask) -> dict[str, Any]:
    content: list[dict[str, Any]] = [
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": ask.title, "marks": [{"type": "bold"}]}],
        }
    ]
    for para in [p for p in re.split(r"\n\s*\n", ask.body or "") if p.strip()][:20]:
        content.append({"type": "paragraph", "content": [{"type": "text", "text": para.strip()}]})
    content.append({"type": "askCard", "attrs": {"askId": str(ask.id)}})
    return {"type": "doc", "content": content}


async def _post(session: AsyncSession, ctx: Ctx, agent: Agent, ask: Ask) -> None:
    """Post the ask's card in the thread and tell the people it's for."""
    comment = await create_comment(session, ctx, ask.task_id, _card_doc(ask))
    ask.comment_id = comment.entity.id
    for uid in ask.to_user_ids:
        await notify(
            session,
            ctx,
            user_id=uid,
            kind="agent_ask",
            entity_type="task",
            entity_id=ask.task_id,
            title=f"{agent.name} asks: {ask.title}"[:300],
            snippet=(ask.body or "")[:500] or None,
        )


async def create_ask(
    session: AsyncSession,
    ctx: Ctx,
    *,
    agent: Agent,
    run: AgentRun,
    step_key: str,
    task_id: uuid.UUID,
    project_id: uuid.UUID | None,
    spec: AskSpec,
    tz: str = "UTC",
) -> Ask:
    """Make an ask from a job step (``ctx`` is the agent's, acting for the person who asked)."""
    if not ctx.actor.is_agent:
        raise Forbidden("Only agents ask questions")
    requested = (run.trigger or {}).get("requested_by")
    to, fallback = await resolve_route(
        session,
        ctx.settings,
        spec.route,
        workspace_id=ctx.workspace_id,
        task_id=task_id,
        project_id=project_id,
        requested_by=uuid.UUID(str(requested)) if requested else None,
        pack_key=agent.pack_key,
    )
    now = datetime.now(UTC)
    days = spec.expires_in_days or ctx.settings.ask_expire_days
    hours = spec.remind_in_hours or ctx.settings.ask_remind_hours
    ask = Ask(
        workspace_id=ctx.workspace_id,
        agent_id=agent.id,
        run_id=run.id,
        step_key=step_key,
        task_id=task_id,
        to_user_ids=to,
        route=spec.route,
        route_fallback=fallback,
        kind=spec.kind,
        title=spec.title,
        body=spec.body,
        evidence=[e.model_dump(mode="json", exclude_none=True) for e in spec.evidence],
        options=spec.options_dicts(),
        form=spec.form_dicts(),
        default_on_expiry=spec.default_on_expiry,
        status="open",
        expires_at=now + timedelta(days=days),
        remind_at=add_working_hours(now, hours, tz),
        reminders_sent=0,
    )
    if ask.remind_at is not None and ask.remind_at >= ask.expires_at:
        ask.remind_at = now + (ask.expires_at - now) / 2
    session.add(ask)
    await session.flush()
    await _post(session, ctx, agent, ask)
    act = await record_activity(
        session,
        ctx,
        entity_type="ask",
        entity_id=ask.id,
        verb="ask.created",
        changes={"title": (None, ask.title), "to": (None, [str(u) for u in to])},
    )
    await emit(
        session,
        ctx,
        type="ask.created",
        entity_type="ask",
        entity_id=ask.id,
        data={"task_id": str(task_id), "run_id": str(run.id), "kind": ask.kind},
        channels=[f"task:{task_id}", f"run:{run.id}", *(f"user:{u}" for u in to)],
        activity_id=act.id,
    )
    return ask


# ---------------------------------------------------------------- read


def _require_member(ctx: Ctx) -> None:
    if ctx.actor.role == "guest":
        raise Forbidden("Guests can't see agents' questions")


async def get_ask(session: AsyncSession, ctx: Ctx, ask_id: uuid.UUID, *, lock: bool = False) -> Ask:
    _require_member(ctx)
    ask = await session.get(Ask, ask_id, with_for_update=lock or None)
    if ask is None or ask.workspace_id != ctx.workspace_id:
        raise NotFound("Question not found")
    await get_visible_task(session, ctx, ask.task_id)  # NotFound when you can't see the task
    return ask


async def list_asks(
    session: AsyncSession, ctx: Ctx, *, mine: bool = True, status: str | None = "open"
) -> list[Ask]:
    """Asks for the viewer (``mine``), oldest first; or every ask the viewer can see."""
    _require_member(ctx)
    stmt = select(Ask).where(Ask.workspace_id == ctx.workspace_id, Ask.status != "superseded")
    if status is not None:
        stmt = stmt.where(Ask.status == status)
    if mine:
        if ctx.actor.id is None:
            return []
        stmt = stmt.where(Ask.to_user_ids.contains([ctx.actor.id]))
    rows = list((await session.execute(stmt.order_by(Ask.created_at).limit(200))).scalars())
    out = []
    for ask in rows:
        try:
            await get_visible_task(session, ctx, ask.task_id)
        except NotFound:
            continue
        out.append(ask)
    return out


async def ask_out(session: AsyncSession, ctx: Ctx, ask: Ask) -> AskOut:
    agent = await session.get(Agent, ask.agent_id)
    assert agent is not None
    people = {
        u.id: u
        for u in (
            await session.execute(
                select(User).where(
                    User.id.in_([*ask.to_user_ids, *([ask.answered_by] if ask.answered_by else [])])
                )
            )
        ).scalars()
    }
    answered = people.get(ask.answered_by) if ask.answered_by else None
    change = None
    if ask.status == "answered" and ask.answered_by == ctx.actor.id:
        used = await session.scalar(
            select(AgentRunStep.id).where(
                AgentRunStep.run_id == ask.run_id,
                AgentRunStep.key == ask.step_key,
                AgentRunStep.status == "done",
            )
        )
        if used is None:
            change = await session.scalar(
                select(Activity.id)
                .where(Activity.entity_id == ask.id, Activity.verb == "ask.answered")
                .order_by(Activity.id.desc())
                .limit(1)
            )
    return AskOut(
        id=ask.id,
        run_id=ask.run_id,
        task_id=ask.task_id,
        comment_id=ask.comment_id,
        agent=AskAgentOut(id=agent.id, name=agent.name, avatar=agent.avatar),
        kind=ask.kind,
        title=ask.title,
        body=ask.body,
        evidence=ask.evidence or [],
        options=ask.options,
        form=ask.form,
        route=ask.route,
        route_fallback=ask.route_fallback,
        status=ask.status,
        answer=ask.answer,
        answered_by=AskPersonOut(id=answered.id, name=answered.name) if answered else None,
        answered_via=ask.answered_via,
        to=[
            AskPersonOut(id=u.id, name=u.name) for uid in ask.to_user_ids if (u := people.get(uid))
        ],
        can_answer=ask.status == "open"
        and ctx.actor.role != "guest"
        and ctx.actor.id in ask.to_user_ids,
        default_on_expiry=ask.default_on_expiry,
        created_at=ask.created_at,
        answered_at=ask.answered_at,
        expires_at=ask.expires_at,
        change_activity_id=change,
    )


# ---------------------------------------------------------------- answer


async def _wake(session: AsyncSession, ask: Ask) -> AgentRun | None:
    """Queue the job waiting on this ask (``None`` when it isn't waiting on it)."""
    run = await session.get(AgentRun, ask.run_id, with_for_update=True)
    if run is None or run.status != "waiting":
        return None
    wait = run.waiting_on or {}
    if wait.get("type") != "ask" or str(ask.id) not in (wait.get("ids") or []):
        return None
    run.status, run.waiting_on, run.resume_at = "queued", None, None
    return run


def _run_channels(run: AgentRun) -> list[str]:
    t = run.trigger or {}
    return [f"run:{run.id}", *([f"task:{t['task_id']}"] if t.get("task_id") else [])]


async def answer_ask(
    session: AsyncSession, ctx: Ctx, ask_id: uuid.UUID, value: Any, *, via: str = "card"
) -> Ask:
    ask = await get_ask(session, ctx, ask_id, lock=True)
    if ask.status != "open":
        raise Conflict(
            "This question was already answered"
            if ask.status == "answered"
            else f"This question is {ask.status}",
            code="ask_closed",
        )
    if ctx.actor.role == "guest":
        raise Forbidden("Guests can't answer agents' questions")
    if ctx.actor.id not in ask.to_user_ids:
        raise Forbidden("This question is for someone else")
    clean = validate_answer(ask.kind, ask.options, ask.form, value)
    ask.status, ask.answer, ask.answered_via = "answered", clean, via
    ask.answered_by, ask.answered_at = ctx.actor.id, datetime.now(UTC)
    act = await record_activity(
        session,
        ctx,
        entity_type="ask",
        entity_id=ask.id,
        verb="ask.answered",
        changes={"answer": (None, clean)},
        undo=undo_op("asks.unanswer", ask_id=ask.id),
    )
    await emit(
        session,
        ctx,
        type="ask.answered",
        entity_type="ask",
        entity_id=ask.id,
        data={"task_id": str(ask.task_id), "run_id": str(ask.run_id), "via": via},
        channels=[f"task:{ask.task_id}", f"run:{ask.run_id}"],
        activity_id=act.id,
    )
    run = await _wake(session, ask)
    if run is not None:
        await emit(
            session,
            ctx,
            type="agent_run.resumed",
            entity_type="agent_run",
            entity_id=run.id,
            data={"agent_id": str(run.agent_id)},
            channels=_run_channels(run),
            activity_id=act.id,
        )
    await session.flush()
    return ask


@undo_handler("asks.unanswer")
async def _undo_answer(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    ask = await session.get(Ask, uuid.UUID(str(args["ask_id"])), with_for_update=True)
    if ask is None or ask.status != "answered":
        raise UndoConflict("This answer can't be taken back now")
    consumed = await session.scalar(
        select(AgentRunStep.id).where(
            AgentRunStep.run_id == ask.run_id,
            AgentRunStep.key == ask.step_key,
            AgentRunStep.status == "done",
        )
    )
    if consumed is not None:
        raise UndoConflict("The agent already used this answer; tell it in the thread instead")
    ask.status, ask.answer, ask.answered_by, ask.answered_via, ask.answered_at = (
        "open",
        None,
        None,
        None,
        None,
    )
    await emit(
        session,
        ctx,
        type="ask.reopened",
        entity_type="ask",
        entity_id=ask.id,
        data={"task_id": str(ask.task_id), "run_id": str(ask.run_id)},
        channels=[f"task:{ask.task_id}", f"run:{ask.run_id}"],
    )


def exact_answer(ask: Ask, text: str) -> tuple[bool, Any]:
    """A thread reply that maps to the answer with certainty (spec §5.3): an exact option label or
    value, yes/no for a confirm, a lone number for a one-number form, any text for a text ask.
    ``(False, None)`` means "ask the model and confirm with the person"."""
    t = " ".join(text.split())
    bare = t.strip(" .!?\"'").casefold()
    if ask.kind == "text":
        return (True, t) if t else (False, None)
    if ask.kind == "confirm":
        if bare in YES:
            return True, True
        if bare in NO:
            return True, False
        return False, None
    if ask.kind in ("choice", "pick_entity", "pick_record"):
        for o in ask.options or []:
            if bare in (str(o["label"]).strip().casefold(), str(o["value"]).casefold()):
                return True, o["value"]
        return False, None
    fields = ask.form or []
    numeric = [f for f in fields if f.get("required", True)]
    if len(numeric) == 1 and numeric[0]["type"] in ("number", "money") and len(fields) == 1:
        try:
            return True, validate_answer("form", None, fields, {numeric[0]["name"]: bare})
        except ValidationFailed:
            return False, None
    return False, None


# ---------------------------------------------------------------- cancel, remind, expire


async def cancel_for_run(session: AsyncSession, ctx: Ctx, run_id: uuid.UUID) -> int:
    """The job ended: its open asks are cancelled (their cards say so)."""
    rows = (
        await session.execute(
            select(Ask).where(Ask.run_id == run_id, Ask.status == "open").with_for_update()
        )
    ).scalars()
    n = 0
    for ask in rows:
        ask.status = "cancelled"
        act = await record_activity(
            session, ctx, entity_type="ask", entity_id=ask.id, verb="ask.cancelled"
        )
        await emit(
            session,
            ctx,
            type="ask.cancelled",
            entity_type="ask",
            entity_id=ask.id,
            data={"task_id": str(ask.task_id), "run_id": str(ask.run_id)},
            channels=[f"task:{ask.task_id}", f"run:{ask.run_id}"],
            activity_id=act.id,
        )
        n += 1
    return n


async def _agent_ctx(session: AsyncSession, ask: Ask, settings: Settings) -> tuple[Agent, Ctx]:
    agent = await session.get(Agent, ask.agent_id)
    account = await session.get(User, agent.user_id) if agent is not None else None
    assert agent is not None and account is not None
    return agent, Ctx(
        actor=Actor(
            id=account.id,
            workspace_id=account.workspace_id,
            role=account.role,
            is_agent=True,
            email=account.email,
            name=agent.name,
            timezone=account.timezone,
        ),
        settings=settings,
        via="agent",
    )


async def _expire(session: AsyncSession, settings: Settings, ask: Ask, now: datetime) -> None:
    agent, ctx = await _agent_ctx(session, ask, settings)
    default = ask.default_on_expiry or {"action": "fail"}
    if default.get("action") == "escalate":
        current = ask.route_fallback or ask.route
        up = ESCALATION[ESCALATION.index(current) + 1 :] if current in ESCALATION else ESCALATION
        run = await session.get(AgentRun, ask.run_id)
        assert run is not None
        for route in up:
            try:
                to, _fallback = await resolve_route(
                    session,
                    settings,
                    route,
                    workspace_id=ask.workspace_id,
                    task_id=ask.task_id,
                    project_id=uuid.UUID(str((run.trigger or {})["project_id"]))
                    if (run.trigger or {}).get("project_id")
                    else None,
                    requested_by=None,
                )
            except Conflict:
                continue
            if set(to) == set(ask.to_user_ids):
                continue
            new = Ask(
                workspace_id=ask.workspace_id,
                agent_id=ask.agent_id,
                run_id=ask.run_id,
                step_key=ask.step_key,
                task_id=ask.task_id,
                to_user_ids=to,
                route=route,
                route_fallback=None,
                kind=ask.kind,
                title=ask.title,
                body=ask.body,
                evidence=ask.evidence,
                options=ask.options,
                form=ask.form,
                default_on_expiry={"action": "escalate"}
                if route != ESCALATION[-1]
                else {"action": "fail"},
                status="open",
                expires_at=now + timedelta(days=settings.ask_expire_days),
                remind_at=now + timedelta(hours=settings.ask_remind_hours),
                reminders_sent=0,
            )
            ask.status = "superseded"
            await session.flush()  # free the one-live-ask-per-step slot first
            session.add(new)
            await session.flush()
            ask.superseded_by = new.id
            await _post(session, ctx, agent, new)
            act = await record_activity(
                session,
                ctx,
                entity_type="ask",
                entity_id=ask.id,
                verb="ask.escalated",
                changes={"route": (ask.route, route)},
            )
            await emit(
                session,
                ctx,
                type="ask.escalated",
                entity_type="ask",
                entity_id=ask.id,
                data={"task_id": str(ask.task_id), "run_id": str(ask.run_id), "to": str(new.id)},
                channels=[f"task:{ask.task_id}", f"run:{ask.run_id}"],
                activity_id=act.id,
            )
            # the waiting job now waits on the new ask
            if run.status == "waiting" and (run.waiting_on or {}).get("type") == "ask":
                run.waiting_on = {**(run.waiting_on or {}), "ids": [str(new.id)]}
            return
        default = {"action": "fail"}  # nobody further up: give up
    ask.status = "expired"
    ask.answered_via = "expiry"
    ask.answered_at = now
    if "value" in default:
        ask.answer = default["value"]
    act = await record_activity(
        session,
        ctx,
        entity_type="ask",
        entity_id=ask.id,
        verb="ask.expired",
        changes={"default": (None, default)},
    )
    await emit(
        session,
        ctx,
        type="ask.expired",
        entity_type="ask",
        entity_id=ask.id,
        data={"task_id": str(ask.task_id), "run_id": str(ask.run_id), "default": default},
        channels=[f"task:{ask.task_id}", f"run:{ask.run_id}"],
        activity_id=act.id,
    )
    ask.default_on_expiry = default
    run = await _wake(session, ask)
    if run is not None:
        await emit(
            session,
            ctx,
            type="agent_run.resumed",
            entity_type="agent_run",
            entity_id=run.id,
            data={"agent_id": str(run.agent_id)},
            channels=_run_channels(run),
            activity_id=act.id,
        )


async def ask_timers(
    session: AsyncSession, settings: Settings, now: datetime | None = None
) -> dict[str, int]:
    """Reminders and expiry for open asks. The caller commits."""
    now = now or datetime.now(UTC)
    stats = {"reminded": 0, "expired": 0}
    due = (
        await session.execute(
            select(Ask)
            .where(Ask.status == "open", Ask.expires_at <= now)
            .with_for_update(skip_locked=True)
        )
    ).scalars()
    for ask in list(due):
        await _expire(session, settings, ask, now)
        stats["expired"] += 1
    remind = (
        await session.execute(
            select(Ask)
            .where(
                Ask.status == "open",
                Ask.remind_at.is_not(None),
                Ask.remind_at <= now,
                Ask.reminders_sent < MAX_REMINDERS,
            )
            .with_for_update(skip_locked=True)
        )
    ).scalars()
    for ask in list(remind):
        agent, ctx = await _agent_ctx(session, ask, settings)
        for uid in ask.to_user_ids:
            await notify(
                session,
                ctx,
                user_id=uid,
                kind="agent_ask_reminder",
                entity_type="task",
                entity_id=ask.task_id,
                title=f"Reminder: {agent.name} is still waiting: {ask.title}"[:300],
            )
        ask.reminders_sent += 1
        ask.remind_at = (
            now + (ask.expires_at - now) / 2 if ask.reminders_sent < MAX_REMINDERS else None
        )
        stats["reminded"] += 1
    await session.flush()
    return stats
