"""S5.3.7 Radar · Risk Watcher: a built-in code-backed agent (``handler: momentum.risk_watcher``).

Weekdays at 08:00 (workspace time), one run per project it has been added to (``per: project``).
It computes heuristic risk signals in code (``domain/forecasts/signals.py``, shared with the
forecast's risk score since S6.5.3). When the project has a fresh stored forecast, Radar reads
its score and drivers instead of recomputing (``note_from_forecast``):

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
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai import prompts
from momentum.ai.context.tokens import safe
from momentum.ai.errors import AIUnavailable
from momentum.domain.agents.models import Agent, AgentRun
from momentum.domain.forecasts.models import Forecast
from momentum.domain.forecasts.service import SIGNAL_POINTS, fresh
from momentum.domain.forecasts.signals import level
from momentum.domain.forecasts.signals import signals as project_signals
from momentum.domain.projects.models import Project

if TYPE_CHECKING:
    from momentum.agents.extensions import HandlerResult, HandlerRun

HANDLER = "momentum.risk_watcher"
_KEY = re.compile(r"\bT-\d+\b")


async def signals(
    hrun: HandlerRun, project_id: uuid.UUID, today: date, now: datetime
) -> list[dict[str, Any]]:
    return await project_signals(hrun.session, project_id, today, now)


def note_from_forecast(f: Forecast) -> tuple[str, list[dict[str, Any]]]:
    """Radar's level and signals from a stored forecast (its drivers are Radar's signals plus
    the forecast against the due date)."""
    found = [
        {
            "kind": d["kind"],
            "text": d["text"],
            "tasks": list(d.get("tasks") or []),
            "weight": max(1, int(d["points"]) // SIGNAL_POINTS),
        }
        for d in f.drivers
    ]
    return f.risk_level, found


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
    stored = await fresh(session, project.id, now)
    if stored is not None:
        risk, found = note_from_forecast(stored)
        hrun.step(f"Read the stored forecast: risk {round(stored.risk_score)}/100")
    else:
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
