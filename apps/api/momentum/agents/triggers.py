"""S5.1.2: what makes an agent run (agents.md §2). Every trigger ends in ``enqueue_run`` with a
dedupe key, so the same trigger delivered twice queues one run.

- **schedule**: ``evaluate_schedules`` runs every minute (Procrastinate periodic) and checks each
  enabled agent's crons in the workspace's timezone, a fixed IANA zone, or — for ``timezone:
  user`` — each person's own timezone (one run per person, acting on their behalf). Key:
  ``schedule:<trigger#>:<user|->:<minute UTC>``. A minute the worker missed is not replayed.
- **event / assigned / mentioned**: ``consume_events`` is an outbox consumer (its own
  ``consumer_offsets`` row, ``agents``), like the rules executor. Keys: ``event:<outbox id>``,
  ``assigned:<task>:<outbox id>``, ``mentioned:<comment>``.
- **manual**: ``request_run`` (``POST /agents/{id}/run``), always a new run.

Only events from after an agent was last switched on (``enabled_at``) count, so enabling an
agent never replays history. Loop protection: events caused by an agent never trigger an agent
(a person applying an agent's proposal is a person). Event and schedule triggers only fire
inside the agent's scope and access; assigned/mentioned/manual always queue (a person asked),
and the runtime explains a missing access on the run instead of dropping it silently.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from croniter import croniter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Actor, Ctx
from momentum.core.errors import Forbidden, NotFound, ValidationFailed
from momentum.core.events import ConsumerOffset, OutboxEvent
from momentum.core.settings import Settings
from momentum.domain.access import get_visible_project, get_visible_task, task_ancestors
from momentum.domain.agents.models import Agent
from momentum.domain.agents.runs import enqueue_run
from momentum.domain.projects.models import Project
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.users.models import User
from momentum.domain.workspace.models import Workspace
from momentum.domain.workspace.service import workspace_timezone

CONSUMER = "agents"
EXTERNAL_VIAS = ("form", "integration")


@dataclass
class TriggerStats:
    events: int = 0
    queued: int = 0


def agent_ctx(agent: Agent, user: User, settings: Settings) -> Ctx:
    """The agent acting as itself: its own account, ``via="agent"``."""
    return Ctx(
        actor=Actor(
            id=user.id,
            workspace_id=user.workspace_id,
            role=user.role,
            is_agent=True,
            email=user.email,
            name=agent.name,
            timezone=user.timezone,
        ),
        settings=settings,
        via="agent",
    )


def on_behalf_ctx(person: User, settings: Settings) -> Ctx:
    """A per-user agent acting for ``person``: their access, ``via="agent"``."""
    return Ctx(
        actor=Actor(
            id=person.id,
            workspace_id=person.workspace_id,
            role=person.role,
            email=person.email,
            name=person.name,
            timezone=person.timezone,
        ),
        settings=settings,
        via="agent",
    )


async def task_project_ids(session: AsyncSession, task: Task) -> list[uuid.UUID]:
    """The projects a task lives in (a subtask lives where its top-level task does)."""
    chain = await task_ancestors(session, task)
    top = chain[-1] if chain else task
    rows = await session.execute(
        select(TaskProject.project_id).where(TaskProject.task_id == top.id)
    )
    return list(rows.scalars())


async def in_scope(
    session: AsyncSession, agent: Agent, ctx: Ctx, project_ids: list[uuid.UUID]
) -> bool:
    """Whether the agent may act on something in these projects: it must have access (explicit
    membership, kickoff Q1) and the project must be inside its ``scope``, which only narrows."""
    scope = agent.scope or {}
    wanted = scope.get("projects", "member_of")
    teams = scope.get("teams")
    for pid in project_ids:
        if isinstance(wanted, list) and str(pid) not in {str(p) for p in wanted}:
            continue
        try:
            project, _role = await get_visible_project(session, ctx, pid)
        except NotFound:
            continue
        if teams and str(project.team_id) not in {str(t) for t in teams}:
            continue
        return True
    return False


async def _enabled_agents(session: AsyncSession) -> list[tuple[Agent, User]]:
    rows = await session.execute(
        select(Agent, User).join(User, User.id == Agent.user_id).where(Agent.enabled.is_(True))
    )
    return [(a, u) for a, u in rows.tuples()]


# ---------------- schedules ----------------


def personal_cron(cron: str, person: User | None, at: str | None) -> str:
    """S5.3.1: a per-person schedule's cron with the person's own time of day (their
    notification ``digest_time``, "HH:MM") in place of its minute and hour, when they set one.
    Days and months stay the definition's (Pulse: weekdays)."""
    if person is None or at != "digest_time":
        return cron
    value = ((person.prefs or {}).get("notifications") or {}).get("digest_time")
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        return cron
    hour, minute = value.split(":")
    if not (hour.isdigit() and minute.isdigit() and int(hour) < 24 and int(minute) < 60):
        return cron
    return " ".join([str(int(minute)), str(int(hour)), *cron.split()[2:]])


def _minute(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)


async def evaluate_schedules(
    session: AsyncSession, settings: Settings, now: datetime
) -> TriggerStats:
    """Queue the scheduled runs due in this minute (and the one before, in case the periodic job
    ran late; dedupe keeps that from doubling)."""
    stats = TriggerStats()
    if not settings.agents_enabled:
        return stats
    minutes = [_minute(now), _minute(now) - timedelta(minutes=1)]
    for agent, _account in await _enabled_agents(session):
        for index, trig in enumerate(agent.triggers or []):
            if trig.get("type") != "schedule":
                continue
            cron, tz = str(trig["cron"]), str(trig.get("timezone") or "workspace")
            if tz == "user":
                people = (
                    await session.execute(
                        select(User).where(
                            User.workspace_id == agent.workspace_id,
                            User.is_agent.is_(False),
                            User.status == "active",
                        )
                    )
                ).scalars()
                targets: list[tuple[User | None, str]] = [(p, p.timezone) for p in people]
            else:
                if tz == "workspace":
                    ws = await session.get(Workspace, agent.workspace_id)
                    tz = workspace_timezone(ws) if ws is not None else "UTC"
                targets = [(None, tz)]
            for person, zone in targets:
                own = personal_cron(cron, person, trig.get("at"))
                for minute in minutes:
                    if not croniter.match(own, minute.astimezone(ZoneInfo(zone))):
                        continue
                    trigger: dict[str, Any] = {
                        "type": "schedule",
                        "fire_time": minute.isoformat(),
                        "timezone": zone,
                    }
                    if person is not None:
                        trigger["for_user_id"] = str(person.id)
                        trigger["requested_by"] = str(person.id)
                    who = str(person.id) if person is not None else "-"
                    key = f"schedule:{index}:{who}:{minute.isoformat()}"
                    if await enqueue_run(session, agent, trigger, key) is not None:
                        stats.queued += 1
    return stats


# ---------------- outbox events ----------------


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


def _actor(ev: OutboxEvent) -> tuple[str | None, str | None]:
    actor = (ev.payload or {}).get("actor") or {}
    return actor.get("id"), actor.get("kind")


def _external(ev: OutboxEvent) -> bool:
    return ev.type == "form.submitted" or (ev.payload or {}).get("via") in EXTERNAL_VIAS


async def _event_projects(session: AsyncSession, ev: OutboxEvent) -> list[uuid.UUID]:
    data = (ev.payload or {}).get("data") or {}
    if data.get("project_id"):
        return [uuid.UUID(str(data["project_id"]))]
    task_id = data.get("task_id") or (ev.entity_id if ev.entity_type == "task" else None)
    if task_id is None:
        return []
    task = await session.get(Task, uuid.UUID(str(task_id)))
    return await task_project_ids(session, task) if task is not None else []


async def _recipient(
    session: AsyncSession, actor_id: str | None, actor_kind: str | None, projects: list[uuid.UUID]
) -> str | None:
    """Who an event-triggered agent's proposals go to: the person who caused the event, else the
    owner of the project it happened in."""
    if actor_id and actor_kind == "user":
        return actor_id
    for pid in projects:
        project = await session.get(Project, pid)
        if project is not None and project.owner_id is not None:
            return str(project.owner_id)
    return None


async def consume_events(
    session: AsyncSession, settings: Settings, *, batch: int = 200, max_batches: int = 20
) -> TriggerStats:
    """Queue agent runs for new outbox events. The caller commits."""
    stats = TriggerStats()
    cursor = await _cursor(session)
    if not settings.agents_enabled:  # a kill switch drops what happened meanwhile, never replays it
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
        agents = await _enabled_agents(session)
        for ev in events:
            cursor.last_event_id = ev.id
            stats.events += 1
            if agents:
                stats.queued += await _handle(session, settings, agents, ev)
    await session.flush()
    return stats


async def _handle(
    session: AsyncSession, settings: Settings, agents: list[tuple[Agent, User]], ev: OutboxEvent
) -> int:
    actor_id, actor_kind = _actor(ev)
    if actor_kind == "agent":
        return 0  # loop protection: agents don't trigger agents
    data = (ev.payload or {}).get("data") or {}
    # only what happened since each agent was switched on (no replay of history)
    agents = [
        (a, u) for a, u in agents if a.enabled_at is not None and ev.created_at >= a.enabled_at
    ]
    by_user = {str(u.id): (a, u) for a, u in agents}
    queued = 0

    # a task assigned to an agent
    if ev.type == "task.assigned" and str(data.get("assignee_id")) in by_user:
        agent, _user = by_user[str(data["assignee_id"])]
        if any(t.get("type") == "assigned" for t in agent.triggers or []):
            trigger = {
                "type": "assigned",
                "event_id": ev.id,
                "task_id": str(ev.entity_id),
                "requested_by": actor_id,
                "external": _external(ev),
            }
            key = f"assigned:{ev.entity_id}:{ev.id}"
            queued += int(await enqueue_run(session, agent, trigger, key) is not None)

    # an agent @mentioned in a comment, or newly mentioned in an edit of one (S5.2.2: an edit's
    # event lists only the people it added); an agent answers a given comment once
    if ev.type in ("comment.created", "comment.edited"):
        for uid in data.get("mentioned_user_ids") or []:
            if str(uid) not in by_user:
                continue
            agent, _user = by_user[str(uid)]
            if not any(t.get("type") == "mentioned" for t in agent.triggers or []):
                continue
            trigger = {
                "type": "mentioned",
                "event_id": ev.id,
                "task_id": str(data.get("task_id")),
                "comment_id": str(ev.entity_id),
                "requested_by": actor_id,
                "external": _external(ev),
            }
            key = f"mentioned:{ev.entity_id}"
            queued += int(await enqueue_run(session, agent, trigger, key) is not None)

    # event triggers
    projects: list[uuid.UUID] | None = None
    for agent, user in agents:
        matching = [
            t
            for t in agent.triggers or []
            if t.get("type") == "event" and t.get("event") == ev.type
        ]
        if not matching:
            continue
        if projects is None:
            projects = await _event_projects(session, ev)
        wanted = [
            t
            for t in matching
            if not (t.get("filter") or {}).get("project_ids")
            or {str(p) for p in projects} & {str(p) for p in t["filter"]["project_ids"]}
        ]
        if not wanted or not await in_scope(
            session, agent, agent_ctx(agent, user, settings), projects
        ):
            continue
        trigger = {
            "type": "event",
            "event_id": ev.id,
            "event_type": ev.type,
            "external": _external(ev),
            "requested_by": await _recipient(session, actor_id, actor_kind, projects),
        }
        if ev.entity_type == "task":
            trigger["task_id"] = str(ev.entity_id)
        elif data.get("task_id"):
            trigger["task_id"] = str(data["task_id"])
        if projects:
            trigger["project_id"] = str(projects[0])
        queued += int(await enqueue_run(session, agent, trigger, f"event:{ev.id}") is not None)
    return queued


# ---------------- manual ----------------


async def request_run(
    session: AsyncSession,
    ctx: Ctx,
    agent: Agent,
    *,
    task_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    text: str | None = None,
) -> uuid.UUID:
    """ "Run now" by a person: on a task or project they can see (or on nothing), optionally with
    text to work from (notes, a brief). The result and any proposals are for them."""
    if ctx.actor.id is None or ctx.actor.is_agent:
        raise Forbidden("Only people can run agents by hand")
    if ctx.actor.role == "guest":
        raise Forbidden("Guests can't run agents")
    if not agent.enabled:
        raise ValidationFailed(f"{agent.name} is turned off")
    if not any(t.get("type") == "manual" for t in agent.triggers or []):
        raise ValidationFailed(f"{agent.name} can't be run by hand")
    trigger: dict[str, Any] = {"type": "manual", "requested_by": str(ctx.actor.id)}
    if task_id is not None:
        await get_visible_task(session, ctx, task_id)
        trigger["task_id"] = str(task_id)
    if project_id is not None:
        await get_visible_project(session, ctx, project_id)
        trigger["project_id"] = str(project_id)
    if text:
        trigger["input"] = text
    run_id = await enqueue_run(session, agent, trigger, f"manual:{uuid.uuid4()}")
    assert run_id is not None  # a fresh key never conflicts
    return run_id
