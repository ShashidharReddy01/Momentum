"""S5.3.7 Radar · Risk Watcher: a built-in code-backed agent (``handler: momentum.risk_watcher``).

Weekdays at 08:00 (workspace time), one run per project it has been added to (``per: project``).
It computes heuristic risk signals in code (forecasts join in Phase 6):

- **overdue**: a quarter or more of the open tasks with a due date are overdue (at least 2);
- **blocked**: open tasks waiting on an open blocker that is itself overdue or blocked (a chain);
- **unassigned**: open tasks with nobody assigned, due within 3 days;
- **scope growth**: in the last 7 days, at least 5 tasks added and more than twice as many added
  as completed.

The note is ``{level, signals, summary}`` on the run (``output.risk``): shown on the project's
overview (``GET /projects/{id}/risk``, anyone who can see the project) and as a line in the
owner's Pulse digest. Radar changes nothing and notifies nobody itself (``suggest``). The model
writes one sentence explaining the signals, only when there are some, and only citing their tasks;
otherwise (or when the gateway is down) the summary is plain text built from the signals.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from momentum.ai import prompts
from momentum.ai.context.tokens import safe
from momentum.ai.errors import AIUnavailable
from momentum.core.ids import task_key
from momentum.domain.agents.models import Agent, AgentRun
from momentum.domain.projects.models import Project
from momentum.domain.tasks.models import Task, TaskDependency, TaskProject

if TYPE_CHECKING:
    from momentum.agents.extensions import HandlerResult, HandlerRun

HANDLER = "momentum.risk_watcher"
OVERDUE_SHARE = 0.25
OVERDUE_MIN = 2
NEAR_DUE_DAYS = 3
GROWTH_WINDOW = timedelta(days=7)
GROWTH_MIN = 5
LISTED = 5  # task keys named per signal
_KEY = re.compile(r"\bT-\d+\b")


def _keys(tasks: list[Task]) -> list[str]:
    return [f"{task_key(t.number)} {t.title}" for t in tasks[:LISTED]]


async def signals(
    hrun: HandlerRun, project_id: uuid.UUID, today: date, now: datetime
) -> list[dict[str, Any]]:
    session = hrun.session
    open_tasks = list(
        (
            await session.execute(
                select(Task)
                .join(TaskProject, TaskProject.task_id == Task.id)
                .where(
                    TaskProject.project_id == project_id,
                    Task.deleted_at.is_(None),
                    Task.completed_at.is_(None),
                )
                .order_by(Task.due_on.asc().nulls_last(), Task.number)
            )
        ).scalars()
    )
    found: list[dict[str, Any]] = []
    dated = [t for t in open_tasks if t.due_on is not None]
    overdue = [t for t in dated if t.due_on is not None and t.due_on < today]
    if len(overdue) >= OVERDUE_MIN and len(overdue) >= OVERDUE_SHARE * len(dated):
        found.append(
            {
                "kind": "overdue",
                "text": f"{len(overdue)} of {len(dated)} dated open tasks are overdue",
                "tasks": _keys(overdue),
                "weight": 2 if len(overdue) >= 0.5 * len(dated) else 1,
            }
        )
    ids = {t.id for t in open_tasks}
    blocker = aliased(Task)
    edges = (
        await session.execute(
            select(TaskDependency.task_id, blocker)
            .join(blocker, blocker.id == TaskDependency.depends_on_id)
            .where(
                TaskDependency.task_id.in_(ids),
                blocker.deleted_at.is_(None),
                blocker.completed_at.is_(None),
            )
        )
    ).all()
    blocked_ids = {tid for tid, _b in edges}
    chains = [
        tid
        for tid, b in edges
        if b.id in blocked_ids or (b.due_on is not None and b.due_on < today)
    ]
    if chains:
        chained = [t for t in open_tasks if t.id in set(chains)]
        found.append(
            {
                "kind": "blocked",
                "text": f"{len(chained)} task(s) wait on work that is itself overdue or blocked",
                "tasks": _keys(chained),
                "weight": 2 if len(chained) >= 3 else 1,
            }
        )
    near = [
        t
        for t in dated
        if t.assignee_id is None
        and t.due_on is not None
        and today <= t.due_on <= today + timedelta(days=NEAR_DUE_DAYS)
    ]
    if near:
        found.append(
            {
                "kind": "unassigned",
                "text": f"{len(near)} task(s) due within {NEAR_DUE_DAYS} days have no one assigned",
                "tasks": _keys(near),
                "weight": 1,
            }
        )
    since = now - GROWTH_WINDOW
    in_project = select(TaskProject.task_id).where(TaskProject.project_id == project_id)
    added = int(
        await session.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.id.in_(in_project), Task.deleted_at.is_(None), Task.created_at >= since)
        )
        or 0
    )
    done = int(
        await session.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.id.in_(in_project), Task.completed_at >= since)
        )
        or 0
    )
    if added >= GROWTH_MIN and added > 2 * done:
        found.append(
            {
                "kind": "scope",
                "text": f"{added} tasks added this week and {done} completed",
                "tasks": [],
                "weight": 1,
            }
        )
    return found


def level(found: list[dict[str, Any]]) -> str:
    score = sum(int(s["weight"]) for s in found)
    return "high" if score >= 4 else "medium" if score >= 2 else "low" if score else "none"


async def _summary(hrun: HandlerRun, project: Project, found: list[dict[str, Any]]) -> str:
    plain = "; ".join(s["text"] for s in found) + "."
    allowed = {k for s in found for k in _KEY.findall(" ".join(s["tasks"]))}
    facts = "\n".join(
        f"- {s['text']}" + (f": {', '.join(safe(t) for t in s['tasks'])}" if s["tasks"] else "")
        for s in found
    )
    prompt = prompts.load("radar_note")
    messages: list[Any] = [
        {
            "role": "system",
            "content": prompt.body,
        },
        {
            "role": "user",
            "content": (
                f'<data source="risk_signals" project="{safe(project.name)}">\n{facts}\n</data>'
            ),
        },
    ]
    try:
        completion = await hrun.complete(
            messages, max_tokens=prompt.max_tokens, prompt_version=prompt.version
        )
    except AIUnavailable:
        hrun.step("The model was unavailable: kept the plain summary")
        return plain
    text = " ".join((completion.text or "").split())[:400]
    if not text or not set(_KEY.findall(text)) <= allowed:
        hrun.step("Kept the plain summary: the model's cited tasks outside the signals")
        return plain
    return text


async def risk_watcher(hrun: HandlerRun) -> HandlerResult | None:
    from momentum.agents.extensions import HandlerResult

    session = hrun.session
    if not hrun.trigger.get("project_id"):
        hrun.step("Radar checks one project per run")
        return None
    project = await session.get(Project, uuid.UUID(str(hrun.trigger["project_id"])))
    if project is None:
        return None
    now = datetime.now(UTC)
    zone = str(hrun.trigger.get("timezone") or "UTC")
    try:
        today = now.astimezone(ZoneInfo(zone)).date()
    except (KeyError, ValueError):
        today = now.date()
    found = await signals(hrun, project.id, today, now)
    risk = level(found)
    if not found:
        hrun.step(f"No risk signals in {project.name}")
        hrun.output["risk"] = {
            "level": "none",
            "signals": [],
            "summary": "",
            "project": project.name,
        }
        return None
    summary = await _summary(hrun, project, found)
    hrun.step(f"{project.name}: {risk} risk ({', '.join(s['kind'] for s in found)})")
    hrun.output["risk"] = {
        "level": risk,
        "signals": [{k: s[k] for k in ("kind", "text", "tasks")} for s in found],
        "summary": summary,
        "project": project.name,
    }
    return HandlerResult(text=f"{project.name}: {risk} risk. {summary}")


async def latest_note(
    session: AsyncSession, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> tuple[AgentRun, Agent] | None:
    """Radar's latest risk note on a project (its most recent finished run there)."""
    row = (
        await session.execute(
            select(AgentRun, Agent)
            .join(Agent, Agent.id == AgentRun.agent_id)
            .where(
                Agent.workspace_id == workspace_id,
                Agent.handler == HANDLER,
                AgentRun.status == "succeeded",
                AgentRun.trigger["project_id"].astext == str(project_id),
                AgentRun.output["risk"].is_not(None),
            )
            .order_by(AgentRun.finished_at.desc())
            .limit(1)
        )
    ).first()
    return (row[0], row[1]) if row is not None else None
