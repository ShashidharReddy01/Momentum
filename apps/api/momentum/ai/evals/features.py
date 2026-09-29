"""Run one eval case through the real feature code and record what happened (an
``Observation``). Every case runs in its own transaction that is rolled back afterwards, so
cases never see each other's changes (``llm_calls`` rows are written separately and stay,
which is how the report counts tokens and cost)."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.agents.loader import load_definitions
from momentum.agents.runtime import execute_run
from momentum.ai import citations, quick_add, summarize, write
from momentum.ai.agent_draft import draft_agent
from momentum.ai.breakdown import break_down, project_people
from momentum.ai.chat import run_chat, start_turn
from momentum.ai.command import run_command
from momentum.ai.context import Screen
from momentum.ai.errors import AIUnavailable
from momentum.ai.evals.workspace import EvalWorld
from momentum.ai.from_brief import plan_from_brief
from momentum.ai.llm import LLM
from momentum.ai.models import AiAction
from momentum.ai.nl_rule import compile_rule
from momentum.ai.plan_day import plan_day
from momentum.ai.rule_steps import run_kind
from momentum.ai.status_draft import draft_status
from momentum.ai.tools.registry import ToolRegistry
from momentum.ai.tools.write_tools import text_doc
from momentum.core.context import Ctx
from momentum.core.errors import DomainError
from momentum.core.settings import Settings
from momentum.domain.agents import service as agents
from momentum.domain.agents.models import AgentRun
from momentum.domain.agents.runs import enqueue_run
from momentum.domain.agents.schemas import AgentPatchIn
from momentum.domain.comments.service import create_comment
from momentum.domain.notifications.models import Notification
from momentum.domain.projects.models import Project
from momentum.domain.tasks import service as tasks
from momentum.domain.tasks.models import Task
from momentum.domain.teams.models import Team

FEATURES = (
    "command",
    "chat",
    "summarize_thread",
    "summarize_inbox",
    "breakdown",
    "status_draft",
    "plan_day",
    "write",
    "quick_add",
    "from_brief",
    "nl_rule",
    "ai_step",
    "agent_teammate",
    "agent_draft",
)


@dataclass
class Observation:
    text: str = ""
    tools: list[str] = field(default_factory=list)
    failed_tools: list[str] = field(default_factory=list)
    operations: list[dict[str, Any]] = field(default_factory=list)  # tool, args, diff
    risk: str | None = None
    clarified: bool = False
    candidates: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    grounded: bool | None = None
    notes: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    latency_ms: int = 0


def screen_for(spec: dict[str, Any] | None, world: EvalWorld) -> Screen:
    spec = spec or {}
    return Screen(
        kind=spec.get("kind", "home"),
        project_id=world.projects.get(spec["project"]) if spec.get("project") else None,
        task_id=world.task_ids.get(spec["task"]) if spec.get("task") else None,
        selected_task_ids=[
            world.task_ids[t] for t in spec.get("selected", []) if t in world.task_ids
        ],
    )


async def _operations(
    session: AsyncSession, action_id: str | uuid.UUID | None
) -> tuple[list[dict[str, Any]], str | None]:
    if not action_id:
        return [], None
    action = await session.get(AiAction, uuid.UUID(str(action_id)))
    if action is None:
        return [], None
    return list(action.operations), action.risk


async def run_case(
    session: AsyncSession,
    llm: LLM,
    registry: ToolRegistry,
    settings: Settings,
    world: EvalWorld,
    case: dict[str, Any],
    feature: str,
) -> Observation:
    obs = Observation()
    ctx = world.ctx(case.get("user", "ravi"), settings).with_(via="ai")
    now = datetime.now(UTC)
    started = time.monotonic()
    events: list[tuple[str, dict[str, Any]]] = []

    async def emit(kind: str, data: dict[str, Any]) -> None:
        events.append((kind, data))

    try:
        await _run(session, llm, registry, world, case, feature, ctx, now, emit, obs)
    except (DomainError, AIUnavailable) as e:
        obs.error = (
            getattr(e, "code", "error")
            if not isinstance(e, AIUnavailable)
            else f"ai_unavailable:{e.reason}"
        )
        obs.text = obs.text or str(getattr(e, "detail", "") or "")
    obs.latency_ms = int((time.monotonic() - started) * 1000)
    for kind, data in events:
        if kind == "tool_result":
            obs.tools.append(str(data["name"]))
            if not data.get("ok"):
                obs.failed_tools.append(str(data["name"]))
        elif kind == "token":
            obs.text += str(data.get("text") or "")
        elif kind == "citation":
            obs.citations.append(data)
        elif kind == "clarify":
            obs.clarified = True
            obs.candidates = list(data.get("candidates") or [])
        elif kind == "action_proposed":
            obs.operations, obs.risk = await _operations(session, data["action_id"])
        elif kind == "done" and "grounded" in data:
            obs.grounded = bool(data["grounded"])
        elif kind == "error":
            obs.error = str(data.get("reason"))
    return obs


async def _run(
    session: AsyncSession,
    llm: LLM,
    registry: ToolRegistry,
    world: EvalWorld,
    case: dict[str, Any],
    feature: str,
    ctx: Ctx,
    now: datetime,
    emit: Any,
    obs: Observation,
) -> None:
    inp = case.get("input", "")
    if feature == "command":
        await run_command(
            session,
            llm,
            ctx,
            registry,
            inp,
            screen=screen_for(case.get("screen"), world),
            now=now,
            emit=emit,
        )
    elif feature == "chat":
        screen = screen_for(case.get("screen"), world)
        questions = [*case.get("history", []), inp]  # earlier questions, then the scored one
        conv_id: uuid.UUID | None = None
        for i, question in enumerate(questions):
            turn = await start_turn(session, ctx, question, conversation_id=conv_id, screen=screen)
            conv_id = turn.conversation.id
            last = i == len(questions) - 1
            await run_chat(
                session,
                llm,
                ctx,
                registry,
                (conv_id, turn.message.id),
                screen=screen,
                now=now,
                emit=emit if last else _ignore,
            )
    elif feature == "summarize_thread":
        r = await summarize.summarize_thread(
            session, llm, ctx, world.task_ids[case["task"]], now=now
        )
        obs.text, obs.citations = r.text, r.citations
        obs.data = {"count": r.count}
    elif feature == "summarize_inbox":
        inbox = await summarize.summarize_inbox(session, llm, ctx, now=now)
        obs.text, obs.citations = inbox.text, inbox.citations
        unread = (
            await session.execute(
                select(Notification, Task.number)
                .outerjoin(Task, Task.id == Notification.entity_id)
                .where(
                    Notification.user_id == ctx.actor.id,
                    Notification.read_at.is_(None),
                    Notification.archived_at.is_(None),
                )
                .order_by(Notification.created_at.desc())
            )
        ).all()
        # what the judge checks the summary against (the model saw exactly these)
        source = []
        for n, num in unread:
            key = f"[T-{num}] " if num else ""
            source.append(f"{n.kind.replace('_', ' ')} {key}{n.title}: {n.snippet or ''}")
        obs.data = {"source": source}
    elif feature == "breakdown":
        b = await break_down(
            session,
            llm,
            ctx,
            registry,
            world.task_ids[case["task"]],
            hint=case.get("hint"),
            now=now,
        )
        obs.notes = b.notes
        obs.operations, obs.risk = await _operations(session, b.action_id)
        task_project = case.get("project", "Launch Plan")
        project = await session.get(Project, world.projects[task_project])
        assert project is not None
        obs.data = {"project_people": [str(u.id) for u in await project_people(session, project)]}
    elif feature == "status_draft":
        d = await draft_status(session, llm, ctx, world.projects[case["project"]], now=now)
        obs.notes = d.notes
        body = d.draft
        items = [
            i.text
            for key in ("completed", "slipped", "blockers", "next")
            for i in getattr(body.sections, key)
        ]
        obs.text = "\n".join([body.title, body.summary, *items])
        obs.data = {"status": body.status, "items": items, "facts": d.facts}
        obs.citations = [c.to_json() for c in await citations.resolve(session, ctx, obs.text)]
    elif feature == "plan_day":
        p = await plan_day(session, llm, ctx, registry, now=now)
        obs.text, obs.notes = p.rationale, p.notes
        obs.citations = [c.to_json() for c in await citations.resolve(session, ctx, obs.text)]
        obs.data = {"today": p.today, "later": p.later}
        obs.operations, obs.risk = await _operations(session, p.action_id)
    elif feature == "write":
        obs.text = await write.rewrite(
            llm,
            ctx,
            action=case["action"],
            text=inp,
            tone=case.get("tone"),
            language=case.get("language"),
        )
        obs.data = {"input": inp}
    elif feature == "quick_add":
        q = await quick_add.parse(session, llm, ctx, inp, now=now)
        obs.data = q.model_dump(mode="json")
        obs.notes = q.unresolved
    elif feature == "from_brief":
        start = date.fromisoformat(case["start_on"]) if case.get("start_on") else None
        end = date.fromisoformat(case["end_on"]) if case.get("end_on") else None
        team = case.get("team")
        team_id = None
        if team:
            team_id = (await session.execute(select(Team.id).where(Team.name == team))).scalar_one()
        brief = await plan_from_brief(
            session, llm, ctx, registry, inp, now=now, team_id=team_id, start_on=start, end_on=end
        )
        obs.notes = brief.notes
        obs.data = {
            "end_on": brief.end_on.isoformat(),
            "requested_end": case.get("end_on"),
            "tasks": brief.tasks,
        }
        obs.operations, obs.risk = await _operations(session, brief.action_id)
    elif feature == "nl_rule":
        compiled = await compile_rule(
            session, llm, ctx, world.projects[case.get("project", "Launch Plan")], inp
        )
        obs.clarified = compiled.question is not None
        obs.text = compiled.question or compiled.sentence or ""
        obs.data = {"rule": compiled.named, "sentence": compiled.sentence}
    elif feature == "ai_step":
        # The rule action itself (S4.1.5), run as the rule's author would: the case's writes are
        # rolled back with the case's transaction like every other feature's.
        field = case.get("field")
        field_id = (
            "priority" if field == "priority" else str(world.fields[field]) if field else None
        )
        step = await run_kind(
            session, llm, ctx, world.task_ids[case["task"]], case["kind"], field_id, now=now
        )
        obs.text = step.comment or step.summary
        obs.notes = step.notes
        # `source` is what the model was shown, so the judge can check the draft against it.
        obs.data = {
            "summary": step.summary,
            "comment": step.comment,
            "source": step.source or None,
            **step.values,
        }
    elif feature == "agent_draft":
        drafted = await draft_agent(llm, ctx, registry, inp)
        obs.text = drafted.agent.instructions
        obs.notes = drafted.notes
        obs.data = drafted.agent.model_dump(mode="json")
    elif feature == "agent_teammate":
        await _teammate(session, llm, registry, world, case, ctx, now, obs)
    else:
        raise ValueError(f"unknown eval feature {feature!r}")


class _Unbilled:
    """The eval's LLM without run attribution: usage rows are written in their own transaction,
    and the case's run row (rolled back with the case) never exists for them to point at."""

    def __init__(self, llm: LLM) -> None:
        self._llm = llm

    def __getattr__(self, name: str) -> Any:
        return getattr(self._llm, name)

    async def complete(self, *args: Any, **kwargs: Any) -> Any:
        kwargs.pop("agent_run_id", None)
        return await self._llm.complete(*args, **kwargs)

    def stream(self, *args: Any, **kwargs: Any) -> Any:
        kwargs.pop("agent_run_id", None)
        return self._llm.stream(*args, **kwargs)


async def _teammate(
    session: AsyncSession,
    llm: LLM,
    registry: ToolRegistry,
    world: EvalWorld,
    case: dict[str, Any],
    ctx: Ctx,
    now: datetime,
    obs: Observation,
) -> None:
    """S5.3.8: the Teammate starter on one task, through the real runtime (its packaged
    definition, its own account with editor access to the project, the policy, the answer in
    the thread, the hand-off). The case's person assigns the task (``input`` becomes its
    description: the request) or mentions the agent (``input`` is the comment)."""
    settings = ctx.settings
    admin = world.ctx("admin", settings)
    definition = next(d for d, _source in load_definitions() if d.key == "teammate")
    [installed] = await agents.install_definitions(
        session, admin, [(definition, "starter")], registry.names, force=True
    )
    agent = installed.agent
    await agents.update_agent(session, admin, agent.id, AgentPatchIn(enabled=True), registry.names)
    owner = world.ctx("ravi", settings)
    await agents.add_to_project(
        session, owner, agent.id, world.projects[case.get("project", "Launch Plan")], "editor"
    )
    task_id = world.task_ids[case["task"]]
    trigger: dict[str, Any] = {"task_id": str(task_id), "requested_by": str(ctx.actor.id)}
    person = ctx.with_(via="web")
    if case.get("trigger", "assigned") == "assigned":
        if case.get("input"):
            await tasks.update_task(
                session, person, task_id, {"description": text_doc(case["input"])}
            )
        trigger["type"] = "assigned"
    else:
        m = await create_comment(session, person, task_id, text_doc(case.get("input", "")))
        trigger |= {"type": "mentioned", "comment_id": str(m.entity.id)}
    run_id = await enqueue_run(session, agent, trigger, None)
    assert run_id is not None
    run = await session.get(AgentRun, run_id)
    assert run is not None
    run.status = "running"
    await execute_run(session, _Unbilled(llm), registry, settings, run_id, now=now)  # type: ignore[arg-type]
    await session.refresh(run)
    output = run.output or {}
    obs.text = str(output.get("text") or "")
    for step in run.trace:
        if step.get("kind") == "tool":
            obs.tools.append(str(step.get("name")))
            if not step.get("ok"):
                obs.failed_tools.append(str(step.get("name")))
    if output.get("proposed"):
        obs.operations, obs.risk = await _operations(session, output["proposed"][0])
    obs.citations = [c.to_json() for c in await citations.resolve(session, ctx, obs.text)]
    obs.data = {"status": run.status, "handoff": output.get("handoff")}
    if run.status != "succeeded":
        obs.error = f"run_{run.status}: {run.error}"


async def _ignore(kind: str, data: dict[str, Any]) -> None:
    return None
