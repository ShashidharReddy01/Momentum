"""S5.1.2: the agent runtime (agents.md §2).

``execute_run`` takes one claimed run and:

1. checks the kill switches (``MOMENTUM_AGENTS_ENABLED``, the agent's ``enabled``; the global and
   workspace AI switches are checked by the gateway on every call);
2. builds the context it acts in: the agent's own account (``via="agent"``), or — for a per-user
   run (``for_user_id``) — the person it works for, so it sees only what they see. When a person
   asked (assigned, mentioned, run now), the agent acts *for* them (``ctx.acting_for``): it sees
   only what both can see, with the lower role of the two;
3. checks access and scope for what the run is about (a task or project);
4. runs the shared tool loop (``ai/loop.py``) with only the agent's own tools, its step limit and
   a wall-clock timeout; every model call carries ``agent_run_id``, so the gateway checks the
   agent's own budget first and the call is billed to the run;
5. applies the autonomy x risk policy (``policy.py``) to the writes it previewed: applied as the
   agent, proposed to the person the run is for (``ai_actions`` + an ``agent_proposal``
   notification), or turned into a suggestion comment;
6. answers in the task's thread when a person asked (assigned, mentioned, run by hand on a task);
7. records the trace (short step summaries, never prompts or tool arguments), tokens and cost,
   and emits ``agent_run.finished``.

Failures post nothing to people. A budget stop, or three failures in a row, alert the workspace
admins (``agent_alert``, at most once a day per agent).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.agents import policy
from momentum.agents.extensions import Handler, HandlerRun, attach_file
from momentum.agents.triggers import agent_ctx, in_scope, on_behalf_ctx, task_project_ids
from momentum.ai.actions import ProposedCall, apply_as_agent, propose
from momentum.ai.context.builders import project_ctx, task_ctx
from momentum.ai.context.tokens import safe
from momentum.ai.errors import AIDisabled, AIUnavailable, BudgetExceeded
from momentum.ai.llm import LLM
from momentum.ai.loop import OUT_OF_STEPS, run_tool_loop
from momentum.ai.memory import memory_for
from momentum.ai.models import LlmCall
from momentum.ai.prompts import load
from momentum.ai.tools.registry import ToolRegistry
from momentum.ai.tools.write_tools import text_doc
from momentum.core.context import Actor, Ctx
from momentum.core.errors import DomainError, NotFound
from momentum.core.events import emit
from momentum.core.ids import task_key
from momentum.core.richtext import plain_text
from momentum.core.settings import Settings
from momentum.core.telemetry import get_logger
from momentum.domain.access import get_visible_project, get_visible_task
from momentum.domain.agents.models import Agent, AgentRun
from momentum.domain.agents.runs import recent_statuses
from momentum.domain.comments.models import Comment
from momentum.domain.comments.service import create_comment
from momentum.domain.notifications.models import Notification
from momentum.domain.notifications.service import notify
from momentum.domain.sections.models import Section
from momentum.domain.tasks import service as tasks
from momentum.domain.tasks.models import Task
from momentum.domain.users.models import User
from momentum.domain.workspace.models import Workspace
from momentum.domain.workspace.service import get_ai_config

log = get_logger("agents.runtime")
TRACE_TEXT = 300  # characters kept per trace summary
FAILURES_BEFORE_ALERT = 3
ALERT_EVERY = timedelta(hours=24)
ANSWERING = ("assigned", "mentioned", "manual")  # a person asked: answer in the thread
LONG_ANSWER = 4000  # characters; a longer answer goes in an attached file (S5.2.1)
LONG_ANSWER_OPENING = 1200  # how much of it the comment keeps
REVIEW_SECTIONS = ("review", "in review")  # where an assigned task goes back for review
AUTONOMY_NOTE = {
    "suggest": "You can only suggest: your changes are shown to people as suggestions, and your"
    " comments are posted as your suggestions.",
    "confirm": "Your changes are proposed to a person, who applies or rejects them.",
    "auto": "Low-risk changes you make are applied; bigger ones are proposed to a person first.",
}


class _Trace:
    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []

    def add(self, kind: str, summary: str, **extra: Any) -> None:
        self.steps.append(
            {
                "at": datetime.now(UTC).isoformat(),
                "kind": kind,
                "summary": summary[:TRACE_TEXT],
                **extra,
            }
        )

    async def on_loop_event(self, type_: str, data: dict[str, Any]) -> None:
        if type_ == "tool_result":
            self.add(
                "tool",
                str(data.get("summary") or ""),
                name=data.get("name"),
                ok=bool(data.get("ok")),
                preview=bool(data.get("preview")),
            )


def _limits(agent: Agent, settings: Settings) -> tuple[int, int]:
    limits = agent.limits or {}
    steps = min(int(limits.get("max_steps") or settings.agent_max_steps), settings.agent_max_steps)
    timeout = min(
        int(limits.get("timeout_s") or settings.agent_timeout_s), settings.agent_timeout_s
    )
    return steps, timeout


async def _person(session: AsyncSession, raw: Any) -> User | None:
    if not raw:
        return None
    user = await session.get(User, uuid.UUID(str(raw)))
    if user is None or user.is_agent or user.status != "active":
        return None
    return user


async def _messages(
    session: AsyncSession,
    ctx: Ctx,
    agent: Agent,
    run: AgentRun,
    requester: User | None,
    autonomy: str,
    now: datetime,
) -> list[dict[str, Any]]:
    trigger = run.trigger or {}
    task_id = trigger.get("task_id")
    project_id = trigger.get("project_id")
    ws = await session.get(Workspace, agent.workspace_id)
    memory = await memory_for(
        session, ctx, project_id=uuid.UUID(project_id) if project_id else None
    )
    local = now.astimezone(ZoneInfo(ctx.actor.timezone))
    prompt = load("agent")
    system = prompt.render(
        name=safe(agent.name),
        workspace=safe(ws.name if ws else ""),
        date=local.date().isoformat(),
        weekday=local.strftime("%A"),
        time=local.strftime("%H:%M"),
        tz=ctx.actor.timezone,
        autonomy_note=AUTONOMY_NOTE[autonomy],
        memory=(
            "Workspace memory (facts from admins):\n" + "\n".join(f"- {safe(m)}" for m in memory)
            if memory
            else ""
        ),
        instructions=agent.instructions or "(none)",
    )
    who = safe(requester.name) if requester is not None else "someone"
    kind = trigger.get("type")
    lines: list[str] = []
    if kind == "assigned":
        lines.append(f"{who} assigned you the task below. Do the work it asks for.")
    elif kind == "mentioned":
        lines.append(f"{who} mentioned you in a comment on the task below. Reply to it.")
        comment = (
            await session.get(Comment, uuid.UUID(trigger["comment_id"]))
            if trigger.get("comment_id")
            else None
        )
        if comment is not None:
            text = safe(plain_text(comment.body))[:4000]
            lines.append(f'<data source="comment">\n{text}\n</data>')
    elif kind == "manual":
        lines.append(f"{who} asked you to run now.")
    elif kind == "event":
        lines.append(f"Something happened: {trigger.get('event_type')}. Handle it as instructed.")
    else:
        lines.append(f"Your scheduled run ({trigger.get('fire_time', '')}).")
    if trigger.get("for_user_id") and requester is not None:
        lines.append(f"You are working for {who}; you can see only what they can see.")
    if trigger.get("input"):
        lines.append(f'<data source="input">\n{safe(str(trigger["input"]))[:20000]}\n</data>')
    if task_id:
        lines.append((await task_ctx(session, ctx, uuid.UUID(task_id), now=now)).text)
    elif project_id:
        lines.append((await project_ctx(session, ctx, uuid.UUID(project_id), now=now)).text)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(lines)},
    ]


async def alert_admins(
    session: AsyncSession, ctx: Ctx, agent: Agent, title: str, snippet: str
) -> None:
    since = datetime.now(UTC) - ALERT_EVERY
    recent = await session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.kind == "agent_alert",
            Notification.entity_id == agent.id,
            Notification.created_at >= since,
        )
    )
    if recent:
        return
    admins = (
        await session.execute(
            select(User.id).where(
                User.workspace_id == agent.workspace_id,
                User.role == "admin",
                User.status == "active",
                User.is_agent.is_(False),
            )
        )
    ).scalars()
    for admin_id in admins:
        await notify(
            session,
            ctx,
            user_id=admin_id,
            kind="agent_alert",
            entity_type="agent",
            entity_id=agent.id,
            title=title[:300],
            snippet=snippet[:500],
        )


async def _usage(session: AsyncSession, run_id: uuid.UUID) -> tuple[int, int, Decimal]:
    row = (
        await session.execute(
            select(
                func.coalesce(func.sum(LlmCall.tokens_in), 0),
                func.coalesce(func.sum(LlmCall.tokens_out), 0),
                func.coalesce(func.sum(LlmCall.cost_usd), 0),
            ).where(LlmCall.agent_run_id == run_id)
        )
    ).one()
    return int(row[0]), int(row[1]), Decimal(row[2])


async def _apply_policy(
    session: AsyncSession,
    ctx: Ctx,
    registry: ToolRegistry,
    agent: Agent,
    run: AgentRun,
    proposals: list[ProposedCall],
    autonomy: str,
    requester: User | None,
    trace: _Trace,
) -> dict[str, Any]:
    """Sort the previewed writes by the policy and act on them. Returns the run's output parts."""
    acting_as_agent = ctx.actor.is_agent
    config = await get_ai_config(session, agent.workspace_id)
    allow_medium = config.allow_medium_auto is True
    to_apply: list[ProposedCall] = []
    to_propose: list[ProposedCall] = []
    suggestions: list[str] = []
    for call in proposals:
        out = await registry.invoke(session, ctx, call.tool, call.args, mode="dry_run")
        if not out.ok:
            trace.add("skipped", f"{call.tool}: {out.result.summary}", name=call.tool)
            continue
        decision = policy.decide(autonomy, out.risk, call.tool, allow_medium_auto=allow_medium)
        if decision == "apply" and not acting_as_agent:
            decision = "propose"  # a per-user run never writes on someone's behalf unasked
        if decision == "apply":
            to_apply.append(call)
        elif decision == "propose":
            to_propose.append(call)
        else:
            suggestions.append(out.result.summary)
    output: dict[str, Any] = {"applied": [], "proposed": [], "suggestions": suggestions}
    recipient = requester.id if requester is not None else None

    if to_apply:
        p = await propose(
            session,
            ctx,
            registry,
            to_apply,
            source="agent",
            source_id=run.id,
            proposed_for=recipient or ctx.actor.id,
        )
        if p.action is not None:
            applied = await apply_as_agent(session, ctx, registry, p.action)
            output["applied"].append(str(p.action.id))
            trace.add(
                "applied" if applied.outcome == "applied" else "error",
                p.action.summary if applied.outcome == "applied" else p.action.error or "",
                action_id=str(p.action.id),
            )
        else:
            for name, out in p.failures:
                trace.add("skipped", f"{name}: {out.result.summary}", name=name)

    if to_propose:
        if recipient is None:
            trace.add("skipped", "Nobody to propose these changes to", count=len(to_propose))
        else:
            p = await propose(
                session,
                ctx,
                registry,
                to_propose,
                source="agent",
                source_id=run.id,
                proposed_for=recipient,
            )
            if p.action is not None:
                output["proposed"].append(str(p.action.id))
                trace.add(
                    "proposal", p.action.summary, action_id=str(p.action.id), risk=p.action.risk
                )
                task_id = (run.trigger or {}).get("task_id")
                await notify(
                    session,
                    ctx,
                    user_id=recipient,
                    kind="agent_proposal",
                    entity_type="task" if task_id else "agent_run",
                    entity_id=uuid.UUID(task_id) if task_id else run.id,
                    title=f"{agent.name} suggests: {p.action.summary}"[:300],
                )
            else:
                for name, out in p.failures:
                    trace.add("skipped", f"{name}: {out.result.summary}", name=name)
    for s in suggestions:
        trace.add("suggestion", s)
    return output


async def execute_run(
    session: AsyncSession,
    llm: LLM,
    registry: ToolRegistry,
    settings: Settings,
    run_id: uuid.UUID,
    *,
    now: datetime | None = None,
    handlers: Mapping[str, Handler] | None = None,
) -> str:
    """Run one claimed run to completion and record the outcome; returns the final status.
    Never raises: the run row keeps the error, and writes made before a failure roll back.
    ``handlers``: the host's code-backed agents (S5.1.5), by the name ``agent.handler`` gives."""
    run = await session.get(AgentRun, run_id)
    if run is None or run.status != "running":
        return "skipped"
    agent = await session.get(Agent, run.agent_id)
    account = await session.get(User, agent.user_id) if agent is not None else None
    if agent is None or account is None:
        run.status, run.error, run.finished_at = (
            "failed",
            "The agent no longer exists",
            datetime.now(UTC),
        )
        return run.status
    now = now or datetime.now(UTC)
    trace = _Trace()
    trigger = run.trigger or {}
    trace.add("trigger", f"{trigger.get('type')} trigger", trigger=trigger.get("type"))
    base_ctx = agent_ctx(agent, account, settings)
    status, error, output = "succeeded", None, {}
    savepoint = await session.begin_nested()
    try:
        if not settings.agents_enabled or not agent.enabled:
            raise _Cancelled(f"{agent.name} is turned off")
        handler = (handlers or {}).get(agent.handler or "") if agent.kind == "handler" else None
        if agent.kind == "handler" and handler is None:
            raise _Failed(f"No handler is registered for {agent.handler}")
        requester = await _person(session, trigger.get("requested_by"))
        for_user = await _person(session, trigger.get("for_user_id"))
        if trigger.get("for_user_id") and for_user is None:
            raise _Cancelled("The person this run was for is no longer active")
        ctx = on_behalf_ctx(for_user, settings) if for_user is not None else base_ctx
        if for_user is None and requester is not None and trigger.get("type") in ANSWERING:
            # a person asked: the agent sees only what both of them can see (2026-09-29)
            ctx = ctx.with_(
                acting_for=Actor(
                    id=requester.id,
                    workspace_id=requester.workspace_id,
                    role=requester.role,
                    email=requester.email,
                    name=requester.name,
                    timezone=requester.timezone,
                )
            )
        await _check_access(session, agent, ctx, trigger)
        autonomy = policy.effective_autonomy(agent.autonomy, external=bool(trigger.get("external")))
        if autonomy != agent.autonomy:
            trace.add("policy", f"External content: autonomy capped at {autonomy}")
        tools = ToolRegistry(t for n in agent.tools if (t := registry.get(n)) is not None)
        timeout_s = _limits(agent, settings)[1]
        if handler is not None:
            output = await _run_handler(
                session, llm, tools, settings, ctx, agent, run, handler, timeout_s, requester, trace
            )
        else:
            output = await _run_model(
                session, llm, tools, ctx, agent, run, autonomy, requester, now, trace
            )
        await savepoint.commit()
    except _Cancelled as e:
        await savepoint.rollback()
        status, error = "cancelled", str(e)
    except BudgetExceeded as e:
        await savepoint.rollback()
        status, error = "budget_exceeded", e.detail
        await alert_admins(
            session, base_ctx, agent, f"{agent.name} stopped: budget used up", e.detail
        )
    except AIDisabled as e:
        await savepoint.rollback()
        status, error = "cancelled", e.detail
    except (AIUnavailable, _Failed, _NoAccess) as e:
        await savepoint.rollback()
        status, error = "failed", getattr(e, "detail", None) or str(e)
    except Exception as e:  # the run records the failure; the worker keeps going
        await savepoint.rollback()
        log.exception("agent_run_failed", agent=agent.key, run_id=str(run.id))
        status, error = "failed", f"Something went wrong ({type(e).__name__})"
    if error:
        trace.add("error", error)
    run.tokens_in, run.tokens_out, run.cost_usd = await _usage(session, run.id)
    run.status, run.error, run.output = status, error, output or None
    run.trace = trace.steps
    run.finished_at = datetime.now(UTC)
    await session.flush()
    await _tell_requester(session, base_ctx, agent, run, status, error)
    if status == "failed":
        recent = await recent_statuses(session, agent.id, FAILURES_BEFORE_ALERT)
        if len(recent) == FAILURES_BEFORE_ALERT and all(s == "failed" for s in recent):
            await alert_admins(
                session,
                base_ctx,
                agent,
                f"{agent.name} failed {FAILURES_BEFORE_ALERT} times in a row",
                error or "",
            )
    await emit(
        session,
        base_ctx,
        type="agent_run.finished",
        entity_type="agent_run",
        entity_id=run.id,
        data={
            "agent_id": str(agent.id),
            "status": status,
            "task_id": trigger.get("task_id"),
        },
        channels=[
            f"workspace:{agent.workspace_id}",
            *([f"user:{trigger['requested_by']}"] if trigger.get("requested_by") else []),
        ],
    )
    return status


class _Cancelled(Exception):
    pass


class _Failed(Exception):
    pass


class _NoAccess(Exception):
    pass


async def _check_access(
    session: AsyncSession, agent: Agent, ctx: Ctx, trigger: dict[str, Any]
) -> None:
    """The run's task or project must be visible to the context the agent acts in, and inside
    the agent's scope (which narrows access, never grants it)."""
    task_id, project_id = trigger.get("task_id"), trigger.get("project_id")
    try:
        if task_id:
            task, _placement, _role = await get_visible_task(session, ctx, uuid.UUID(task_id))
            projects = await task_project_ids(session, task)
            if ctx.actor.is_agent and not await in_scope(session, agent, ctx, projects):
                # being assigned a task shows it to the agent, but it works only in projects it
                # was given (kickoff Q1)
                member = False
                for pid in projects:
                    try:
                        await get_visible_project(session, ctx, pid)
                        member = True
                    except NotFound:
                        continue
                if not member:
                    raise NotFound()
                raise _NoAccess(f"This task is outside {agent.name}'s scope")
        elif project_id:
            await get_visible_project(session, ctx, uuid.UUID(project_id))
            if ctx.actor.is_agent and not await in_scope(
                session, agent, ctx, [uuid.UUID(project_id)]
            ):
                raise _NoAccess(f"This project is outside {agent.name}'s scope")
    except NotFound as e:
        raise _NoAccess(
            f"{agent.name} doesn't have access to this. Give it access to the project first."
        ) from e


def _answer_doc(text: str, mention: User | None) -> dict[str, Any]:
    """The answer as a rich-text comment, @mentioning the person who asked (S5.2.1) so they're
    notified that the work is ready."""
    doc = text_doc(text)
    if mention is not None:
        node = {
            "type": "mention",
            "attrs": {"id": str(mention.id), "label": mention.name, "kind": "user"},
        }
        content = doc["content"]
        if content:
            content[0]["content"] = [node, {"type": "text", "text": " "}, *content[0]["content"]]
        else:
            content.append({"type": "paragraph", "content": [node]})
    return doc


async def _answer(
    session: AsyncSession,
    ctx: Ctx,
    run: AgentRun,
    agent: Agent,
    text: str,
    output: dict[str, Any],
    requester: User | None,
    trace: _Trace,
) -> None:
    """When a person asked (assigned, mentioned, run by hand on a task), reply in the task's
    thread, with any suggestions listed under the answer. Otherwise the answer stays on the run.

    For an assignment or a mention (S5.2.1, S5.2.2) the reply @mentions the person who asked,
    so they're notified even if they don't follow the task. An answer longer than
    ``LONG_ANSWER`` goes in an attached Markdown file, with its opening in the comment."""
    trigger = run.trigger or {}
    task_id = trigger.get("task_id")
    suggestions: list[str] = output.get("suggestions") or []
    asked = trigger.get("type") in ANSWERING
    if task_id is None or not ctx.actor.is_agent or not (asked or suggestions):
        return
    body = text if asked else ""
    if asked and len(body) > LONG_ANSWER:
        task = await session.get(Task, uuid.UUID(task_id))
        name = f"{agent.key}-{task_key(task.number) if task else 'result'}.md"
        attachment_id = await attach_file(
            session,
            ctx,
            ctx.settings,
            uuid.UUID(task_id),
            name,
            body.encode("utf-8"),
            "text/markdown",
        )
        output["attachment_id"] = str(attachment_id)
        trace.add("attachment", f"Attached the full answer as {name}")
        opening = body[:LONG_ANSWER_OPENING].rsplit("\n", 1)[0].rstrip()
        body = f"{opening}\n…\nThe full answer is in the attached file {name}."
    if suggestions:
        body = "\n".join([body, "Suggestions:", *(f"- {s}" for s in suggestions)]).strip()
    if not body.strip():
        return
    mention = requester if trigger.get("type") in ("assigned", "mentioned") else None
    m = await create_comment(session, ctx, uuid.UUID(task_id), _answer_doc(body, mention))
    output["comment_id"] = str(m.entity.id)
    trace.add("comment", body.split("\n", 1)[0], comment_id=str(m.entity.id))


async def _hand_off(
    session: AsyncSession,
    ctx: Ctx,
    agent: Agent,
    run: AgentRun,
    requester: User | None,
    output: dict[str, Any],
    trace: _Trace,
) -> None:
    """S5.2.1: after working on a task it was assigned, the agent hands it back for review: to
    the project's "Review" section if it has one (the agent stays the assignee), else to the
    task's creator (or the person who assigned it, when the creator can't take it). Nothing
    happens when someone already reassigned the task meanwhile. Each move is an ordinary,
    undoable change by the agent; one that isn't allowed is noted on the run, not fatal."""
    trigger = run.trigger or {}
    if trigger.get("type") != "assigned" or not trigger.get("task_id") or not ctx.actor.is_agent:
        return
    task_id = uuid.UUID(trigger["task_id"])
    task, placement, _role = await get_visible_task(session, ctx, task_id)
    if task.assignee_id != ctx.actor.id or task.completed_at is not None:
        trace.add("handoff", "Left as it is: the task was reassigned or completed meanwhile")
        return
    savepoint = await session.begin_nested()
    try:
        review = None
        if placement is not None and task.parent_id is None:
            review = await session.scalar(
                select(Section)
                .where(
                    Section.project_id == placement.project_id,
                    Section.deleted_at.is_(None),
                    func.lower(func.trim(Section.name)).in_(REVIEW_SECTIONS),
                )
                .order_by(Section.position)
                .limit(1)
            )
        if review is not None:
            if placement is not None and placement.section_id != review.id:
                await tasks.move_tasks(session, ctx, [task.id], section_id=review.id)
            output["handoff"] = {"section_id": str(review.id)}
            trace.add("handoff", f"Moved to {review.name} for review")
        else:
            creator = await _person(session, task.created_by)
            back_to = creator or requester
            if back_to is None:
                trace.add("handoff", "Nobody to hand the task back to")
                await savepoint.commit()
                return
            await tasks.update_task(session, ctx, task.id, {"assignee_id": back_to.id})
            output["handoff"] = {"assignee_id": str(back_to.id)}
            trace.add("handoff", f"Handed back to {back_to.name} for review")
        await savepoint.commit()
    except DomainError as e:
        await savepoint.rollback()
        trace.add("handoff", f"Couldn't hand the task back: {e.detail}")


async def _tell_requester(
    session: AsyncSession,
    ctx: Ctx,
    agent: Agent,
    run: AgentRun,
    status: str,
    error: str | None,
) -> None:
    """A run a person asked for that didn't finish: tell them, so an assigned task doesn't sit
    waiting in silence (S5.2.1). The notification opens the run, which explains why."""
    trigger = run.trigger or {}
    if status == "succeeded" or trigger.get("type") not in ANSWERING:
        return
    requester = await _person(session, trigger.get("requested_by"))
    if requester is None:
        return
    await notify(
        session,
        ctx,
        user_id=requester.id,
        kind="agent_alert",
        entity_type="agent_run",
        entity_id=run.id,
        title=f"{agent.name} couldn't finish what you asked"[:300],
        snippet=(error or status)[:500],
    )


async def _run_handler(
    session: AsyncSession,
    llm: LLM,
    tools: ToolRegistry,
    settings: Settings,
    ctx: Ctx,
    agent: Agent,
    run: AgentRun,
    handler: Handler,
    timeout_s: int,
    requester: User | None,
    trace: _Trace,
) -> dict[str, Any]:
    """S5.1.5 (ADR-0009): a code-backed agent. It gets the same context, access, timeout and
    trace as a model-driven one; autonomy doesn't apply to host code, but anything it chose to
    ``propose`` goes to the run's person for a decision."""
    hrun = HandlerRun(
        session=session,
        ctx=ctx,
        settings=settings,
        llm=llm,
        registry=tools,
        run_id=run.id,
        agent_key=agent.key,
        agent_name=agent.name,
        model_alias=agent.model_alias,
        trigger=run.trigger or {},
        step=lambda summary: trace.add("step", summary),
    )
    try:
        async with asyncio.timeout(timeout_s):
            result = await handler(hrun)
    except TimeoutError as e:
        raise _Failed(f"The run hit its time limit ({timeout_s} s)") from e
    except (BudgetExceeded, AIDisabled, AIUnavailable):
        raise
    except Exception as e:
        log.exception("agent_handler_failed", agent=agent.key, run_id=str(run.id))
        raise _Failed(f"The handler failed: {type(e).__name__}: {e}"[:300]) from e
    output = await _apply_policy(
        session, ctx, tools, agent, run, hrun.proposals, "confirm", requester, trace
    )
    text = result.text if result is not None else None
    output["text"] = text
    if text:
        await _answer(session, ctx, run, agent, text, output, requester, trace)
    await _hand_off(session, ctx, agent, run, requester, output, trace)
    return output


async def _run_model(
    session: AsyncSession,
    llm: LLM,
    tools: ToolRegistry,
    ctx: Ctx,
    agent: Agent,
    run: AgentRun,
    autonomy: str,
    requester: User | None,
    now: datetime,
    trace: _Trace,
) -> dict[str, Any]:
    """A model-driven agent: the shared tool loop, then the policy, then the answer."""
    messages = await _messages(session, ctx, agent, run, requester, autonomy, now)
    max_steps, timeout_s = _limits(agent, ctx.settings)
    try:
        async with asyncio.timeout(timeout_s):
            result = await run_tool_loop(
                session,
                llm,
                ctx,
                tools,
                messages=messages,
                feature=f"agent:{agent.key}",
                alias=agent.model_alias,  # type: ignore[arg-type]
                emit=trace.on_loop_event,
                max_steps=max_steps,
                prompt_version=load("agent").version,
                max_tokens=load("agent").max_tokens,
                agent_run_id=run.id,
            )
    except TimeoutError as e:
        raise _Failed(f"The run hit its time limit ({timeout_s} s)") from e
    run.steps = result.steps
    if result.text == OUT_OF_STEPS:
        trace.add("limit", f"Stopped at the step limit ({max_steps})")
    output = await _apply_policy(
        session, ctx, tools, agent, run, result.proposals, autonomy, requester, trace
    )
    output["text"] = result.text
    await _answer(session, ctx, run, agent, result.text, output, requester, trace)
    await _hand_off(session, ctx, agent, run, requester, output, trace)
    return output
