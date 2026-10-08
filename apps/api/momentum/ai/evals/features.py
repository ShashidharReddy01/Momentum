"""Run one eval case through the real feature code and record what happened (an
``Observation``). Every case runs in its own transaction that is rolled back afterwards, so
cases never see each other's changes (``llm_calls`` rows are written separately and stay,
which is how the report counts tokens and cost)."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.agents import pulse
from momentum.agents.extensions import HandlerRun
from momentum.agents.loader import load_definitions
from momentum.agents.runtime import execute_run
from momentum.ai import (
    chart,
    citations,
    goal_assist,
    quick_add,
    summarize,
    workload_rebalance,
    write,
)
from momentum.ai.agent_draft import draft_agent
from momentum.ai.breakdown import break_down, project_people
from momentum.ai.chat import run_chat, start_turn
from momentum.ai.command import run_command
from momentum.ai.context import Screen
from momentum.ai.errors import AIUnavailable
from momentum.ai.evals.ask_features import ASK_FEATURES, run_ask
from momentum.ai.evals.insight_features import INSIGHT_FEATURES, run_insight
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
from momentum.ai.types import LAST_STEP_NOTE, Msg
from momentum.core.context import Ctx
from momentum.core.errors import DomainError
from momentum.core.settings import Settings
from momentum.domain.agents import service as agents
from momentum.domain.agents.models import AgentRun
from momentum.domain.agents.runs import enqueue_run
from momentum.domain.agents.schemas import AgentPatchIn
from momentum.domain.comments.models import Comment
from momentum.domain.comments.service import create_comment
from momentum.domain.goals import service as goals_service
from momentum.domain.goals.schemas import GoalIn
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
    "agent_pulse",
    "agent_sorter",
    "agent_herald",
    "agent_nudge",
    "agent_radar",
    "agent_architect",
    "agent_scribe",
    "goal_check_in",
    "workload_rebalance",
    "chart",
    *("file_qa", "file_tables", "file_vision", "file_injection"),
    "report_narrative",
    # Phase 7.5 S75-10: Mo on portfolios and dashboards
    *INSIGHT_FEATURES,
    # Phase 7.6 S76-03: a thread reply as an agent's answer
    *ASK_FEATURES,
    # Phase 7.6 S76-04: Mo answers spend questions from the records query engine
    "records_qa",
)
# Phase 7.5 (spec §11.3): Ask Mo about files, on the onboarding_v1 eval workspace
FILE_FEATURES = ("file_qa", "file_tables", "file_vision", "file_injection")


class RecordingRegistry(ToolRegistry):
    """The real registry, also keeping each call's name, arguments and output, so the file
    scorers can check that numbers came from tools and which queries ran."""

    def __init__(self, inner: ToolRegistry) -> None:
        super().__init__([t for n in inner.names if (t := inner.get(n)) is not None])
        self.calls: list[dict[str, Any]] = []

    async def invoke(self, *args: Any, **kwargs: Any) -> Any:
        out = await super().invoke(*args, **kwargs)
        raw = args[3] if len(args) > 3 else kwargs.get("arguments")
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except ValueError:
            parsed = {}
        self.calls.append(
            {"name": out.tool, "args": parsed, "ok": out.ok, "output": out.result.to_json()}
        )
        return out


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
            obs.data.setdefault("images", int(data.get("images") or 0))
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
    if feature in FILE_FEATURES:
        screen = screen_for(case.get("screen"), world)
        screen = Screen(
            kind=screen.kind,
            project_id=screen.project_id,
            task_id=screen.task_id,
            file_ids=[world.files[f] for f in case.get("files", [])],
        )
        recording = RecordingRegistry(registry)
        turn = await start_turn(session, ctx, inp, conversation_id=None, screen=screen)
        await run_chat(
            session,
            llm,
            ctx,
            recording,
            (turn.conversation.id, turn.message.id),
            screen=screen,
            now=now,
            emit=emit,
        )
        obs.data["tool_calls"] = recording.calls
    elif feature == "command":
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
    elif feature in ("chat", "records_qa"):
        screen = screen_for(case.get("screen"), world)
        if feature == "records_qa":  # its scorer reads what query_records returned
            registry = RecordingRegistry(registry)
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
        if isinstance(registry, RecordingRegistry):
            obs.data["tool_calls"] = registry.calls
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
    elif feature in INSIGHT_FEATURES:
        await run_insight(session, llm, world, case, feature, ctx, obs)
    elif feature in ASK_FEATURES:
        await run_ask(llm, case, ctx, obs)
    elif feature == "report_narrative":
        # Phase 7.5 (spec §6.1): the builder's facts as the person, then the narrative
        from momentum.ai.report_narrative import citables, narrate
        from momentum.domain.portfolios.models import Portfolio
        from momentum.reports.generate import build
        from momentum.reports.spec import FORMATS, ReportSpec

        rscope: dict[str, Any] = {}
        if case.get("project"):
            rscope["project_id"] = str(world.projects[case["project"]])
        else:
            pid = (
                await session.execute(
                    select(Portfolio.id).where(Portfolio.name == case["portfolio"])
                )
            ).scalar_one()
            rscope["portfolio_id"] = str(pid)
        kind = case["kind"]
        rspec = ReportSpec.model_validate(
            {"kind": kind, "scope": rscope, "format": FORMATS[kind][0]}
        )
        doc = await build(session, ctx, rspec)
        paragraphs = await narrate(llm, ctx, kind, doc.facts)
        obs.text = "\n".join(p.text for p in paragraphs)
        obs.data = {
            "paragraphs": len(paragraphs),
            "cites": [c for p in paragraphs for c in p.cites],
            "citables": citables(doc.facts),
            "source": doc.facts,  # the judge checks the paragraphs against these
        }
    elif feature == "goal_check_in":
        # S6.3.2: a goal made for the case (half its period gone), linked to eval projects
        today = now.date()
        g = (
            await goals_service.create_goal(
                session,
                ctx,
                GoalIn(
                    name=case["goal"],
                    period_start=today - timedelta(days=45),
                    period_end=today + timedelta(days=45),
                    progress_source=case.get("source", "projects"),
                    metric=case.get("metric"),
                ),
            )
        ).entity
        for name in case.get("projects", []):
            await goals_service.link(session, ctx, g.id, "project", world.projects[name])
        facts, _ = await goal_assist.facts_for(session, ctx, g, today)
        goal_draft = await goal_assist.draft_check_in(session, llm, ctx, g.id, today)
        obs.text = f"{goal_draft.draft.title}\n{goal_draft.draft.summary}"
        obs.data = {"status": goal_draft.draft.status, "ai": goal_draft.ai, "facts": facts}
    elif feature == "workload_rebalance":
        # S6.4.2: estimates (and due dates, days from today) on eval tasks put people over; the
        # moves come from code, the model only explains them (kept if every number is in the
        # facts). `by` sets a task the asker can't see (hidden load: never named or moved).
        today = now.date()
        for title, spec in case["tasks"].items():
            patch: dict[str, Any] = {"estimate_minutes": int(spec["estimate"])}
            if "due" in spec:
                patch["due_on"] = today + timedelta(days=int(spec["due"]))
            by = world.ctx(spec["by"], ctx.settings) if "by" in spec else ctx
            await tasks.update_task(session, by, world.task_ids[title], patch)
        sug = await workload_rebalance.suggest_rebalance(
            session, llm, ctx, registry, start=today, weeks=case.get("weeks", 3), today=today
        )
        obs.text = f"{sug.note.headline}\n{sug.note.summary}"
        obs.data = {
            "ai": sug.ai,
            "status": sug.rebalance.status,
            "facts": workload_rebalance.facts(sug.rebalance),
        }
        obs.operations, obs.risk = await _operations(session, sug.action_id)
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
    elif feature == "chart":
        # S6.5.2: a question → a chart, run as the asker; a case without `project: null` asks
        # inside Launch Plan (a project dashboard)
        scope = case.get("project", "Launch Plan")
        answer = await chart.ask_chart(
            session, llm, ctx, inp, world.projects[scope] if scope else None
        )
        obs.clarified = answer.question is not None
        res = answer.result
        # the title and every group label: a leak check reads what the chart would show
        obs.text = answer.question or "\n".join(
            [answer.title, *(g.label for g in (res.groups if res else []))]
        )
        obs.data = {
            "chart": chart.canonical(answer),
            "value": res.value if res else None,
            "groups": {g.label: g.value for g in res.groups} if res else None,
            "task_titles": [t.title for t in res.tasks] if res else None,
        }
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
    elif feature == "agent_pulse":
        await _pulse(session, llm, registry, world, case, ctx, now, obs)
    elif feature == "agent_sorter":
        await _sorter(session, llm, registry, world, case, ctx, now, obs)
    elif feature == "agent_herald":
        project = case.get("project", "Launch Plan")
        agent = await _install(session, registry, world, ctx, "status_reporter", project)
        trigger = {
            "type": "schedule",
            "project_id": str(world.projects[project]),
            "requested_by": str(ctx.actor.id),
        }
        await _execute(session, llm, registry, ctx, agent, trigger, now, obs)
        texts: list[str] = []
        for op in _op_args_of(obs.operations, "create_status_update"):
            for k in ("title", "summary", "completed", "slipped", "blockers", "next"):
                value = op.get(k)
                if isinstance(value, list):
                    texts.extend(str(x) for x in value)
                elif value:
                    texts.append(str(value))
        obs.citations = [
            c.to_json() for c in await citations.resolve(session, ctx, "\n".join(texts))
        ]
    elif feature == "agent_nudge":
        project = case.get("project", "Launch Plan")
        agent = await _install(session, registry, world, ctx, "nudger", project)
        trigger = {
            "type": "schedule",
            "project_id": str(world.projects[project]),
            # the workspace data's dates are days from the project owner's today
            "timezone": world.users[case.get("owner", "ravi")].timezone,
            "requested_by": str(ctx.actor.id),
        }
        await _execute(session, llm, registry, ctx, agent, trigger, now, obs)
        rows = (
            await session.execute(
                select(Task.title, Comment.body_text)
                .join(Comment, Comment.task_id == Task.id)
                .where(Comment.author_id == agent.user_id)
            )
        ).all()
        obs.data = {"nudged": [t for t, _ in rows]}
        obs.text = "\n".join(b for _, b in rows)
    elif feature == "agent_radar":
        project = case.get("project", "Launch Plan")
        agent = await _install(
            session, registry, world, ctx, "risk_watcher", project, owner=case.get("owner", "ravi")
        )
        trigger = {
            "type": "schedule",
            "project_id": str(world.projects[project]),
            "timezone": world.users[case.get("owner", "ravi")].timezone,
        }
        output = await _execute(session, llm, registry, ctx, agent, trigger, now, obs)
        risk = output.get("risk") or {}
        obs.data = {
            "level": risk.get("level"),
            "kinds": [x["kind"] for x in risk.get("signals", [])],
        }
        obs.text = str(risk.get("summary") or "")
        obs.citations = [c.to_json() for c in await citations.resolve(session, ctx, obs.text)]
    elif feature == "agent_architect":
        project = case.get("project", "Launch Plan")
        agent = await _install(session, registry, world, ctx, "planner", project)
        asked: dict[str, Any] = {"type": "manual", "requested_by": str(ctx.actor.id)}
        if case.get("task"):
            asked["task_id"] = str(world.task_ids[case["task"]])
        else:
            asked["project_id"] = str(world.projects[project])
        if inp:
            asked["input"] = inp
        await _execute(session, llm, registry, ctx, agent, asked, now, obs)
    elif feature == "agent_scribe":
        project = case.get("project", "Launch Plan")
        agent = await _install(session, registry, world, ctx, "meeting_notes", project)
        notes_run = {
            "type": "manual",
            "requested_by": str(ctx.actor.id),
            "project_id": str(world.projects[project]),
            "input": inp,
        }
        await _execute(session, llm, registry, ctx, agent, notes_run, now, obs)
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


class _Seen(_Unbilled):
    """``_Unbilled`` that also keeps what the model was last shown (the request, the task context
    and every tool result), so the judge can check "no invented facts" against it."""

    def __init__(self, llm: LLM) -> None:
        super().__init__(llm)
        self.messages: list[Msg] = []

    async def complete(self, *args: Any, **kwargs: Any) -> Any:
        self.messages = list(kwargs.get("messages") or [])
        return await super().complete(*args, **kwargs)

    def source(self) -> list[str]:
        """The non-system messages' text: what the answer may draw on (the instructions and
        the model's own earlier turns aside)."""
        out = []
        for m in self.messages:
            if m.get("role") in ("user", "tool") and isinstance(m.get("content"), str):
                out.append(str(m["content"]).replace(LAST_STEP_NOTE, "").strip())
        return out


async def _pulse(
    session: AsyncSession,
    llm: LLM,
    registry: ToolRegistry,
    world: EvalWorld,
    case: dict[str, Any],
    ctx: Ctx,
    now: datetime,
    obs: Observation,
) -> None:
    """S5.3.1: Pulse's digest for the case's person (what it would send), checked against the
    database: every open task of theirs due today or overdue must be listed, and the summary
    line may cite only listed tasks."""
    person = ctx.with_(via="agent")
    hrun = HandlerRun(
        session=session,
        ctx=person,
        settings=ctx.settings,
        llm=_Unbilled(llm),  # type: ignore[arg-type]
        registry=registry,
        run_id=uuid.uuid4(),
        agent_key="daily_digest",
        agent_name="Pulse",
        model_alias="fast",
        trigger={"type": "schedule", "for_user_id": str(ctx.actor.id)},
        step=obs.notes.append,
    )
    digest = await pulse.gather(hrun, now)
    intro = None if digest.empty() else await pulse._intro(hrun, digest)
    obs.text = intro or ""
    today = pulse._local_today(ctx.actor.timezone, now)
    due = (
        await session.execute(
            select(Task.number).where(
                Task.assignee_id == ctx.actor.id,
                Task.completed_at.is_(None),
                Task.deleted_at.is_(None),
                Task.due_on <= today,
            )
        )
    ).scalars()
    listed = " ".join(digest.due_today + digest.overdue)
    obs.data = {
        "empty": digest.empty(),
        "missing": [n for n in due if f"T-{n} " not in listed + " "],
        "digest": digest.text(),
    }
    obs.citations = [c.to_json() for c in await citations.resolve(session, ctx, obs.text)]


def _op_args_of(operations: list[dict[str, Any]], tool: str) -> list[dict[str, Any]]:
    return [op.get("args") or {} for op in operations if op.get("tool") == tool]


async def _install(
    session: AsyncSession,
    registry: ToolRegistry,
    world: EvalWorld,
    ctx: Ctx,
    key: str,
    project: str,
    *,
    owner: str = "ravi",
) -> Any:
    """Install a starter (switched on) with editor access to a project, inside the case (given
    by ``owner``, an admin of that project)."""
    admin = world.ctx("admin", ctx.settings)
    definition = next(d for d, _source in load_definitions() if d.key == key)
    [installed] = await agents.install_definitions(
        session, admin, [(definition, "starter")], registry.names, force=True
    )
    agent = installed.agent
    await agents.update_agent(session, admin, agent.id, AgentPatchIn(enabled=True), registry.names)
    sharer = world.ctx(owner, ctx.settings)
    await agents.add_to_project(session, sharer, agent.id, world.projects[project], "editor")
    return agent


async def _execute(
    session: AsyncSession,
    llm: LLM,
    registry: ToolRegistry,
    ctx: Ctx,
    agent: Any,
    trigger: dict[str, Any],
    now: datetime,
    obs: Observation,
) -> dict[str, Any]:
    """Run one agent run through the real runtime and record what it did on ``obs``."""
    run_id = await enqueue_run(session, agent, trigger, None)
    assert run_id is not None
    run = await session.get(AgentRun, run_id)
    assert run is not None
    run.status = "running"
    await execute_run(session, _Unbilled(llm), registry, ctx.settings, run_id, now=now)  # type: ignore[arg-type]
    await session.refresh(run)
    output = run.output or {}
    obs.text = str(output.get("text") or "")
    for step in run.trace:
        if step.get("kind") == "tool":
            obs.tools.append(str(step.get("name")))
            if not step.get("ok"):
                obs.failed_tools.append(str(step.get("name")))
    for action_id in [*output.get("proposed", []), *output.get("applied", [])]:
        ops, risk = await _operations(session, action_id)
        obs.operations.extend(ops)
        obs.risk = obs.risk or risk
    if run.status != "succeeded":
        obs.error = f"run_{run.status}: {run.error}"
    return output


async def _sorter(
    session: AsyncSession,
    llm: LLM,
    registry: ToolRegistry,
    world: EvalWorld,
    case: dict[str, Any],
    ctx: Ctx,
    now: datetime,
    obs: Observation,
) -> None:
    """S5.3.2: a new task arrives in Launch Plan (created by the case's person, or by a form);
    Sorter triages it through the real runtime. Scored on what it proposes."""
    project = case.get("project", "Launch Plan")
    agent = await _install(session, registry, world, ctx, "triage", project)
    person = ctx.with_(via=case.get("via", "web"))
    created = (
        await tasks.create_task(session, person, world.projects[project], case["title"])
    ).entity[0]
    if case.get("input"):
        await tasks.update_task(
            session, person, created.id, {"description": text_doc(case["input"])}
        )
    trigger = {
        "type": "event",
        "event_type": "task.created",
        "task_id": str(created.id),
        "project_id": str(world.projects[project]),
        "requested_by": str(ctx.actor.id),
        "external": case.get("via") == "form",
    }
    await _execute(session, llm, registry, ctx, agent, trigger, now, obs)
    obs.data = {"task_key": f"T-{created.number}"}


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
    seen = _Seen(llm)
    await execute_run(session, seen, registry, settings, run_id, now=now)  # type: ignore[arg-type]
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
    obs.data = {"status": run.status, "handoff": output.get("handoff"), "source": seen.source()}
    if run.status != "succeeded":
        obs.error = f"run_{run.status}: {run.error}"


async def _ignore(kind: str, data: dict[str, Any]) -> None:
    return None
