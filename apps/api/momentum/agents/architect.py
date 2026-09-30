"""S5.3.5 Architect · Planner: a built-in code-backed agent (``handler: momentum.planner``) around
S3.4.6 "project from brief" and S3.4.2 "break into subtasks".

What it plans depends on what it's given:

- **a brief** ("Run now" with text, or text long enough to be one): a new project with sections,
  tasks, dates inside the requested window and owners from the team (``plan_from_brief``);
- **a task** (assigned, @mentioned, or run on a task with little or no text): its subtasks, with
  the comment or text as guidance (``break_down``).

The plan is never applied by Architect: it's proposed (``confirm``) to the person who asked, who
reviews it on the run page or from their inbox. **Capacity (S6.4.1):** for each suggested owner
it adds a note when their estimated work already planned inside the plan's window exceeds their
hours there (the workload capacity model), or, when little of it is estimated, when they already
have ``CAPACITY_WARN`` or more open tasks due in it.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from momentum.ai.breakdown import break_down
from momentum.ai.from_brief import plan_from_brief
from momentum.core.errors import ValidationFailed
from momentum.domain.projects.models import Project
from momentum.domain.users.models import User
from momentum.domain.workload import service as workload

if TYPE_CHECKING:
    from momentum.agents.extensions import HandlerResult, HandlerRun

HANDLER = "momentum.planner"
BRIEF_CHARS = 200  # text longer than this is a brief, not guidance for a task
CAPACITY_WARN = 8  # open tasks due in the window before a note is added


def _assignees(calls: list[Any]) -> set[uuid.UUID]:
    found: set[uuid.UUID] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                if k == "assignee" and isinstance(v, str):
                    with contextlib.suppress(ValueError):
                        found.add(uuid.UUID(v))
                else:
                    walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    for call in calls:
        walk(call.args)
    return found


async def capacity_notes(
    hrun: HandlerRun, people: set[uuid.UUID], start: date, end: date
) -> list[str]:
    """A heads-up per suggested owner who is already full in the plan's window: planned effort
    over their capacity (S6.4.1), or ``CAPACITY_WARN``+ open tasks due there when unestimated."""
    loads = await workload.load_between(
        hrun.session, hrun.settings, hrun.ctx.workspace_id, people, start, end
    )
    notes = []
    for person_id in sorted(loads):
        planned, capacity, open_due = loads[person_id]
        over = planned > capacity
        if not over and open_due < CAPACITY_WARN:
            continue
        person = await hrun.session.get(User, person_id)
        name = person.name if person else "Someone"
        if over:
            notes.append(
                f"Capacity: {name} already has {planned / 60:.0f}h planned against "
                f"{capacity / 60:.0f}h available in this window."
            )
        else:
            notes.append(f"Capacity: {name} already has {open_due} open tasks due in this window.")
    return notes


async def planner(hrun: HandlerRun) -> HandlerResult | None:
    from momentum.agents.extensions import HandlerResult

    session, ctx, trigger = hrun.session, hrun.ctx, hrun.trigger
    now = datetime.now(UTC)
    text = str(trigger.get("input") or "").strip()
    if trigger.get("type") == "mentioned" and trigger.get("comment_id"):
        from momentum.domain.comments.models import Comment

        comment = await session.get(Comment, uuid.UUID(str(trigger["comment_id"])))
        text = (comment.body_text if comment else "").strip()
    task_id = uuid.UUID(str(trigger["task_id"])) if trigger.get("task_id") else None

    if task_id is not None and len(text) <= BRIEF_CHARS:
        result = await break_down(
            session,
            hrun.llm,
            ctx,
            hrun.registry,
            task_id,
            hint=text or None,
            now=now,
            propose_action=False,
        )
        for call in result.calls:
            hrun.propose(call.tool, call.args)
        today = now.date()
        notes = [
            *result.notes,
            *await capacity_notes(
                hrun, _assignees(result.calls), today, today + timedelta(days=30)
            ),
        ]
        for n in notes:
            hrun.step(n)
        lines = [f"Proposed {result.count} subtasks for you to review and apply.", *notes]
        return HandlerResult(text="\n".join(lines))

    if not text:
        hrun.step("Nothing to plan: no brief and no task")
        return HandlerResult(
            text="Give me a brief (paste it when you run me) or run me on a task to break down."
        )
    team_id = None
    if trigger.get("project_id"):
        project = await session.get(Project, uuid.UUID(str(trigger["project_id"])))
        team_id = project.team_id if project else None
    try:
        brief = await plan_from_brief(
            session,
            hrun.llm,
            ctx,
            hrun.registry,
            text,
            now=now,
            team_id=team_id,
            propose_action=False,
        )
    except ValidationFailed as e:
        if e.code != "team_required":
            raise
        hrun.step("Asked which team the project is for")
        return HandlerResult(
            text="Which team is this project for? Run me from one of that team's projects "
            "(pick the project when you run me) and I'll plan it there."
        )
    for call in brief.calls:
        hrun.propose(call.tool, call.args)
    notes = [
        *brief.notes,
        *await capacity_notes(hrun, _assignees(brief.calls), brief.start_on, brief.end_on),
    ]
    for n in notes:
        hrun.step(n)
    lines = [
        f"Proposed a plan for {brief.name} in {brief.team}: {brief.tasks} tasks, "
        f"{brief.start_on:%b} {brief.start_on.day} to {brief.end_on:%b} {brief.end_on.day}. "
        "Review and apply it from your inbox or this run's page.",
        *notes,
        *(f"Open question: {q}" for q in brief.open_questions),
    ]
    return HandlerResult(text="\n".join(lines))
