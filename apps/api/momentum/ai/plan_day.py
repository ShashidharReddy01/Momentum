"""S3.4.5 "Plan my day": Mo orders the user's open tasks for today and suggests what to move out
of Today, as a previewed change to their My Tasks (``plan_my_day`` tool → ``move_my_task``, the
one write path for personal placements). Nothing moves until the user applies it.

The model sees the user's open tasks (key, section, due date, priority, blocked or not) and
submits keys. The server keeps only keys of those tasks, drops duplicates, caps Today at
``CAPACITY``, and only moves to Later what is currently in Today; each correction is a note.
Estimates and calendar time come later (no estimates field yet; calendar is Phase 7).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai import prompts
from momentum.ai.actions import ProposedCall, propose
from momentum.ai.context.tokens import safe
from momentum.ai.llm import LLM
from momentum.ai.structured import extract
from momentum.ai.tools.registry import ToolRegistry
from momentum.core.context import Ctx
from momentum.core.errors import ValidationFailed
from momentum.core.ids import task_key
from momentum.domain.mytasks.service import list_my_tasks
from momentum.domain.tasks.models import Task, TaskDependency

CAPACITY = 8
MAX_LISTED = 60
KEY_IN = re.compile(r"T-\d+")
BUCKET_TEXT = {
    "recently_assigned": "Recently assigned",
    "today": "Today",
    "this_week": "This week",
    "later": "Later",
}


class DayPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    today: list[str] = Field(default_factory=list, max_length=30, description="Task keys, in order")
    later: list[str] = Field(default_factory=list, max_length=60, description="Task keys")
    rationale: str = Field(default="", max_length=800)


@dataclass
class PlanResult:
    action_id: uuid.UUID | None
    rationale: str
    today: list[str] = field(default_factory=list)
    later: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _keys(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        out += KEY_IN.findall(item)
    return out


async def plan_day(
    session: AsyncSession, llm: LLM, ctx: Ctx, registry: ToolRegistry, *, now: datetime
) -> PlanResult:
    rows = await list_my_tasks(session, ctx)
    if not rows:
        raise ValidationFailed("You have no open tasks to plan")
    local = now.astimezone(ZoneInfo(ctx.actor.timezone))
    today = local.date()
    ids = [t.id for t, _ in rows]
    blocked = set(
        (
            await session.execute(
                select(TaskDependency.task_id)
                .join(Task, Task.id == TaskDependency.depends_on_id)
                .where(
                    TaskDependency.task_id.in_(ids),
                    Task.completed_at.is_(None),
                    Task.deleted_at.is_(None),
                )
            )
        ).scalars()
    )
    by_key: dict[str, tuple[Task, str]] = {}
    lines = []
    for t, p in rows[:MAX_LISTED]:
        key = task_key(t.number)
        bucket = p.bucket if p else "recently_assigned"
        by_key[key] = (t, bucket)
        bits = [BUCKET_TEXT[bucket]]
        if t.due_on:
            late = (today - t.due_on).days
            bits.append(
                f"due {t.due_on.isoformat()}" + (f" ({late} days overdue)" if late > 0 else "")
            )
        if t.priority:
            bits.append(f"priority {t.priority}")
        if t.id in blocked:
            bits.append("blocked")
        lines.append(f"[{key}] {safe(t.title)} ({', '.join(bits)})")
    if len(rows) > MAX_LISTED:
        lines.append(f"(+{len(rows) - MAX_LISTED} more open tasks not shown)")
    prompt = prompts.load("plan_day")
    out = await extract(
        llm,
        ctx,
        prompt=prompt,
        system=prompt.render(
            today=today.isoformat(), weekday=local.strftime("%A"), capacity=CAPACITY
        ),
        user='<data source="my_tasks">\n' + "\n".join(lines) + "\n</data>",
        schema=DayPlan,
        description="Submit the plan for today.",
    )

    notes: list[str] = []
    plan_today: list[str] = []
    for key in _keys(out.today):
        if key not in by_key:
            notes.append(f"Left out {key}: it isn't one of your open tasks.")
        elif key not in plan_today:
            plan_today.append(key)
    if len(plan_today) > CAPACITY:
        notes.append(
            f"Kept the first {CAPACITY} for today; {', '.join(plan_today[CAPACITY:])} can wait."
        )
        plan_today = plan_today[:CAPACITY]
    plan_later: list[str] = []
    for key in _keys(out.later):
        if key not in by_key:
            notes.append(f"Left out {key}: it isn't one of your open tasks.")
        elif key in plan_today or key in plan_later:
            continue
        elif by_key[key][1] != "today":
            continue  # only what is in Today needs moving out
        else:
            plan_later.append(key)
    current_today = [k for k, (_, b) in by_key.items() if b == "today"]
    if not plan_later and plan_today == current_today:
        return PlanResult(None, out.rationale.strip(), plan_today, [], notes)
    if not plan_today and not plan_later:
        raise ValidationFailed("Mo couldn't make a plan from your tasks. Try again.")
    proposal = await propose(
        session,
        ctx,
        registry,
        [ProposedCall("plan_my_day", {"today": plan_today, "later": plan_later})],
        source="inline",
        summary=f"Plan my day: {len(plan_today)} for today"
        + (f", {len(plan_later)} to later" if plan_later else ""),
    )
    if proposal.action is None:
        detail = "; ".join(o.result.summary for _, o in proposal.failures)
        raise ValidationFailed(detail[:300] or "The plan couldn't be previewed")
    return PlanResult(proposal.action.id, out.rationale.strip(), plan_today, plan_later, notes)
