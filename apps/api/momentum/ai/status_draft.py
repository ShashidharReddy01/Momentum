"""S3.4.3 "Draft status": Mo drafts a project status update from what actually happened.

The server first collects the **facts** for the window (default: the last 7 days in the user's
timezone): tasks completed, open tasks that are overdue or whose due date was pushed later,
open tasks blocked by unfinished work, and work due in the next week. Each fact carries its
task key. The model sees only those facts (as data) and submits a structured draft.

Then the draft is checked, not trusted (AC: every claim references real activity): each item
in completed / slipped / blockers / next must cite at least one key **from the facts**; items
that cite nothing, or only keys outside the facts, are removed with a note, and stray keys in
the summary are stripped (also noted). Nothing is stored: the user edits the draft and posts it
through the normal status-update endpoint (``generated_by_ai``), or discards it.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai import prompts
from momentum.ai.context.tokens import safe
from momentum.ai.llm import LLM
from momentum.ai.structured import extract
from momentum.core.activity import Activity
from momentum.core.context import Ctx
from momentum.core.errors import Forbidden
from momentum.core.ids import task_key
from momentum.domain.access import ROLE_RANK, get_visible_project
from momentum.domain.status_updates.models import StatusUpdate
from momentum.domain.status_updates.schemas import StatusItem, StatusSections, StatusUpdateIn
from momentum.domain.tasks.models import Task, TaskDependency, TaskProject
from momentum.domain.users.models import User

MAX_PER_FACT = 25
KEY = re.compile(r"\[(T-\d+)\]")


class DraftItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=400, description="One claim, citing [T-n] keys")


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["on_track", "at_risk", "off_track", "on_hold", "complete"]
    title: str = Field(min_length=1, max_length=150)
    summary: str = Field(default="", max_length=1500)
    completed: list[DraftItem] = Field(default_factory=list, max_length=15)
    slipped: list[DraftItem] = Field(default_factory=list, max_length=15)
    blockers: list[DraftItem] = Field(default_factory=list, max_length=15)
    next: list[DraftItem] = Field(default_factory=list, max_length=15)


@dataclass
class Facts:
    completed: list[str] = field(default_factory=list)
    overdue: list[str] = field(default_factory=list)
    pushed: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    due_soon: list[str] = field(default_factory=list)
    keys: set[str] = field(default_factory=set)

    def total(self) -> int:
        return sum(
            len(x) for x in (self.completed, self.overdue, self.pushed, self.blocked, self.due_soon)
        )


@dataclass
class DraftResult:
    draft: StatusUpdateIn
    notes: list[str]
    facts: dict[str, int]
    since: date


def _local_day_start(d: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(d, time.min, tz).astimezone(UTC)


async def collect_facts(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID, *, since: date, today: date
) -> Facts:
    tz = ZoneInfo(ctx.actor.timezone)
    start = _local_day_start(since, tz)
    placed = select(TaskProject.task_id).where(TaskProject.project_id == project_id)
    in_project = and_(
        or_(Task.id.in_(placed), Task.parent_id.in_(placed)), Task.deleted_at.is_(None)
    )
    facts = Facts()
    names: dict[uuid.UUID, str] = {
        uid: n for uid, n in (await session.execute(select(User.id, User.name))).tuples()
    }

    def line(t: Task, extra: str = "") -> str:
        key = task_key(t.number)
        facts.keys.add(key)
        bits = [names[t.assignee_id]] if t.assignee_id in names else ["unassigned"]
        if t.due_on:
            bits.append(f"due {t.due_on.isoformat()}")
        if extra:
            bits.append(extra)
        return f"[{key}] {safe(t.title)} ({', '.join(bits)})"

    async def tasks_where(*cond: object, order: object = Task.number) -> list[Task]:
        rows = await session.execute(
            select(Task).where(in_project, *cond).order_by(order).limit(MAX_PER_FACT)  # type: ignore[arg-type]
        )
        return list(rows.scalars())

    for t in await tasks_where(Task.completed_at >= start, order=Task.completed_at):
        facts.completed.append(line(t, f"completed {t.completed_at.astimezone(tz).date()}"))  # type: ignore[union-attr]
    open_ = Task.completed_at.is_(None)
    for t in await tasks_where(open_, Task.due_on < today, order=Task.due_on):
        facts.overdue.append(line(t, f"{(today - t.due_on).days} days overdue"))  # type: ignore[operator]
    # due dates pushed later during the window (from the activity trail)
    pushes = await session.execute(
        select(Activity.entity_id, Activity.diff)
        .where(
            Activity.workspace_id == ctx.workspace_id,
            Activity.entity_type == "task",
            Activity.created_at >= start,
            Activity.undone_at.is_(None),
            Activity.diff.has_key("due_on"),
        )
        .order_by(Activity.created_at)
    )
    pushed: dict[uuid.UUID, tuple[str, str]] = {}
    for tid, diff in pushes.tuples():
        old, new = (diff.get("due_on") or [None, None])[:2]
        if old and new and str(new) > str(old):
            first = pushed.get(tid, (str(old), str(new)))[0]
            pushed[tid] = (first, str(new))
    if pushed:
        for t in await tasks_where(open_, Task.id.in_(list(pushed))):
            old, new = pushed[t.id]
            facts.pushed.append(line(t, f"due date moved {old} → {new}"))
    blockers = (
        select(TaskDependency.task_id)
        .join(Task, Task.id == TaskDependency.depends_on_id)
        .where(Task.completed_at.is_(None), Task.deleted_at.is_(None))
    )
    for t in await tasks_where(open_, Task.id.in_(blockers)):
        facts.blocked.append(line(t, "blocked by unfinished work"))
    for t in await tasks_where(
        open_, Task.due_on >= today, Task.due_on <= today + timedelta(days=7), order=Task.due_on
    ):
        facts.due_soon.append(line(t))
    return facts


def _facts_text(project_name: str, since: date, today: date, facts: Facts, last: str) -> str:
    def block(title: str, lines: list[str]) -> list[str]:
        return [f"{title}:", *(f"- {x}" for x in lines)] if lines else [f"{title}: none"]

    parts = [
        f'<data source="project_facts" project="{safe(project_name)}">',
        f"Window: {since.isoformat()} to {today.isoformat()}",
        f"Latest status update: {last}",
        *block("Completed in the window", facts.completed),
        *block("Open and overdue", facts.overdue),
        *block("Due date pushed later in the window", facts.pushed),
        *block("Blocked by unfinished work", facts.blocked),
        *block("Due in the next 7 days", facts.due_soon),
        "</data>",
    ]
    return "\n".join(parts)


def check(draft: Draft, allowed: set[str]) -> tuple[StatusUpdateIn, list[str]]:
    """Keep only claims that cite at least one fact key; strip stray keys from the summary."""
    notes: list[str] = []

    def keep(items: list[DraftItem], section: str) -> list[StatusItem]:
        out = []
        for i in items:
            keys = set(KEY.findall(i.text))
            if keys & allowed:
                out.append(StatusItem(text=i.text.strip()))
            elif keys:
                notes.append(
                    f"Removed from {section}: “{i.text.strip()}” cites tasks outside this "
                    "project's recent activity."
                )
            else:
                notes.append(f"Removed from {section}: “{i.text.strip()}” cites no task.")
        return out

    sections = StatusSections(
        completed=keep(draft.completed, "Completed"),
        slipped=keep(draft.slipped, "Slipped"),
        blockers=keep(draft.blockers, "Blockers"),
        next=keep(draft.next, "Next"),
    )
    summary = draft.summary.strip()
    stray = [k for k in KEY.findall(summary) if k not in allowed]
    if stray:
        summary = KEY.sub(lambda m: m.group(0) if m.group(1) in allowed else "", summary)
        summary = re.sub(r"\s{2,}", " ", summary).strip()
        notes.append(
            "Removed references to " + ", ".join(sorted(set(stray))) + " from the summary."
        )
    return (
        StatusUpdateIn(
            status=draft.status,
            title=draft.title.strip(),
            summary=summary,
            sections=sections,
            generated_by_ai=True,
        ),
        notes,
    )


async def draft_status(
    session: AsyncSession,
    llm: LLM,
    ctx: Ctx,
    project_id: uuid.UUID,
    *,
    now: datetime,
    days: int = 7,
) -> DraftResult:
    project, role = await get_visible_project(session, ctx, project_id)
    if ROLE_RANK[role] < ROLE_RANK["editor"]:
        raise Forbidden("Only people who can edit this project can post its status")
    today = now.astimezone(ZoneInfo(ctx.actor.timezone)).date()
    since = today - timedelta(days=days)
    facts = await collect_facts(session, ctx, project.id, since=since, today=today)
    latest = (
        await session.execute(
            select(StatusUpdate)
            .where(
                StatusUpdate.entity_type == "project",
                StatusUpdate.entity_id == project.id,
                StatusUpdate.deleted_at.is_(None),
            )
            .order_by(StatusUpdate.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    last = (
        f"{latest.status.replace('_', ' ')} on {latest.created_at.date().isoformat()}: "
        f"{safe(latest.title)}"
        if latest
        else "none yet"
    )
    prompt = prompts.load("status_draft")
    out = await extract(
        llm,
        ctx,
        prompt=prompt,
        system=prompt.body,
        user=_facts_text(project.name, since, today, facts, last),
        schema=Draft,
        description="Submit the status update draft.",
    )
    draft, notes = check(out, facts.keys)
    if not facts.total():
        notes.insert(0, f"Nothing changed in {project.name} in the last {days} days.")
    counts = {
        "completed": len(facts.completed),
        "overdue": len(facts.overdue),
        "pushed": len(facts.pushed),
        "blocked": len(facts.blocked),
        "due_soon": len(facts.due_soon),
    }
    return DraftResult(draft, notes, counts, since)
