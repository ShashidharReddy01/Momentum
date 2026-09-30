"""S6.3.2: AI for goals. Both features read facts computed in code and propose; nothing is saved
until a person acts.

- **Check-in draft**: the facts (progress, pace against the period, the metric, the linked work's
  status/completion/overdue/latest update, sub-goals) go to the model, which drafts status, title
  and summary. The draft is kept only if every number in it appears in the facts; otherwise, or
  when the gateway is down, the draft is built in code from the same facts.
- **Suggested projects**: hybrid retrieval (meaning + words) over the projects and tasks the
  person can see, with the goal's name and description as the query; task hits count for their
  project. Already-linked projects are left out. Each suggestion says what matched.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai import prompts, retrieval
from momentum.ai.context.tokens import safe
from momentum.ai.errors import AIUnavailable
from momentum.ai.llm import LLM
from momentum.ai.structured import extract
from momentum.core.context import Ctx
from momentum.domain.goals import service as goals
from momentum.domain.goals.models import Goal
from momentum.domain.projects.models import Project
from momentum.domain.status_updates.service import STATUS_LABELS
from momentum.domain.tasks.models import TaskProject

NUMBER = re.compile(r"\d+")
Status = Literal["on_track", "at_risk", "off_track", "on_hold", "complete"]


def _pct(v: float | None) -> str:
    return "no data" if v is None else f"{round(v * 100)}%"


def pace(g: Goal, today: date) -> float:
    """How much of the goal's period has passed, 0..1."""
    total = (g.period_end - g.period_start).days or 1
    return max(0.0, min(1.0, (today - g.period_start).days / total))


async def facts_for(
    session: AsyncSession, ctx: Ctx, g: Goal, today: date
) -> tuple[list[str], float | None]:
    """The fact lines the draft may use, and the goal's progress for this viewer."""
    progress = await goals.compute_progress(session, ctx)
    value = progress.by_goal.get(g.id)
    lines = [
        f"Goal: {safe(g.name)} ({g.period_label or f'{g.period_start} to {g.period_end}'})",
        f"Progress: {_pct(value)}; {round(pace(g, today) * 100)}% of the period has passed",
        f"Current status: {STATUS_LABELS.get(g.status or '', 'no check-in yet')}",
    ]
    if g.metric:
        m = g.metric
        unit = f" {safe(str(m.get('unit') or ''))}".rstrip()
        now = m.get("current", "not measured")
        lines.append(f"Metric: {now} now, from {m.get('start', 0)} towards {m.get('target')}{unit}")
    links, hidden = await goals.link_views(session, ctx, g, progress)
    for link in links:
        lines.append(
            f"Linked {link['entity_type']} {safe(link['name'])}: "
            f"{STATUS_LABELS.get(link['status'] or '', 'no status')}, {_pct(link['progress'])} done"
        )
        if link["entity_type"] == "project":
            p = await session.get(Project, link["id"])
            if p is not None and p.due_on:
                lines.append(f"  due {p.due_on.isoformat()}")
    if hidden:
        lines.append(f"{hidden} more linked projects the reader can't see are left out")
    all_goals, _ = await goals.list_goals(session, ctx)
    for c in (x for x in all_goals if x.parent_id == g.id):
        lines.append(f"Sub-goal {safe(c.name)}: {_pct(progress.by_goal.get(c.id))}")
    return lines, value


class CheckInDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Status
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=1500)


def _grounded(draft: CheckInDraft, facts: str) -> bool:
    known = set(NUMBER.findall(facts))
    return all(n in known for n in NUMBER.findall(f"{draft.title} {draft.summary}"))


def plain_draft(g: Goal, value: float | None, today: date) -> CheckInDraft:
    """The code-built draft: status by pace, the numbers in words."""
    elapsed = pace(g, today)
    if value is None:
        status: Status = "on_track" if g.status is None else g.status  # type: ignore[assignment]
        title = "No progress data yet"
        summary = "Nothing measures this goal yet: add a metric, link work, or add sub-goals."
    else:
        gap = elapsed - value
        status = (
            "complete"
            if value >= 1
            else "on_track"
            if gap <= 0.1
            else "at_risk"
            if gap <= 0.25
            else "off_track"
        )
        title = f"{round(value * 100)}% done with {round(elapsed * 100)}% of the period gone"
        summary = ""
    return CheckInDraft(status=status, title=title[:200], summary=summary)


@dataclass
class DraftResult:
    draft: CheckInDraft
    ai: bool


async def draft_check_in(
    session: AsyncSession, llm: LLM, ctx: Ctx, goal_id: uuid.UUID, today: date
) -> DraftResult:
    g = await goals.get_goal(session, ctx, goal_id)
    goals._require_edit(ctx, g)  # a draft is for the person who'll post it
    lines, value = await facts_for(session, ctx, g, today)
    text = "\n".join(lines)
    prompt = prompts.load("goal_check_in")
    try:
        out = await extract(
            llm,
            ctx,
            prompt=prompt,
            system=prompt.body,
            user=f'<data source="goal_facts">\n{text}\n</data>',
            schema=CheckInDraft,
            description="Submit the check-in draft.",
        )
    except AIUnavailable:
        return DraftResult(plain_draft(g, value, today), ai=False)
    if not _grounded(out, text):
        return DraftResult(plain_draft(g, value, today), ai=False)
    return DraftResult(out, ai=True)


@dataclass
class Suggestion:
    project_id: uuid.UUID
    name: str
    reason: str


async def suggest_projects(
    session: AsyncSession, llm: LLM, ctx: Ctx, goal_id: uuid.UUID, *, k: int = 5
) -> list[Suggestion]:
    g = await goals.get_goal(session, ctx, goal_id)
    # the name alone first (the keyword half ANDs every word, so a long query can match
    # nothing), then name + description for meaning; merged, best first
    queries = [g.name] + ([f"{g.name} {g.description}"] if g.description else [])
    hits: list[retrieval.Hit] = []
    seen: set[tuple[str, uuid.UUID]] = set()
    for q in queries:
        for h in await retrieval.search(
            session, llm, ctx, q, k=20, types=("project", "task"), feature="goal_links"
        ):
            if (h.entity_type, h.entity_id) not in seen:
                seen.add((h.entity_type, h.entity_id))
                hits.append(h)
    linked = {
        link.entity_id
        for link in (await goals.compute_progress(session, ctx)).links.get(g.id, [])
        if link.entity_type == "project"
    }
    task_projects: dict[uuid.UUID, uuid.UUID] = {}
    task_ids = [h.entity_id for h in hits if h.entity_type == "task"]
    if task_ids:
        for tid, pid in (
            await session.execute(
                select(TaskProject.task_id, TaskProject.project_id).where(
                    TaskProject.task_id.in_(task_ids)
                )
            )
        ).all():
            task_projects.setdefault(tid, pid)
    out: dict[uuid.UUID, Suggestion] = {}
    for h in hits:  # best first
        pid = h.entity_id if h.entity_type == "project" else task_projects.get(h.entity_id)
        if pid is None or pid in linked or pid in out:
            continue
        project = await session.get(Project, pid)
        if project is None or project.deleted_at is not None:
            continue
        reason: Any = (
            f"Its brief: “{h.snippet}”"
            if h.entity_type == "project"
            else f"Task {h.key} “{h.title}”"
        )
        out[pid] = Suggestion(pid, project.name, str(reason)[:200])
        if len(out) >= k:
            break
    return list(out.values())
