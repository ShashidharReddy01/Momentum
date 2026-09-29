"""S5.3.3 Herald · Status Reporter: a built-in code-backed agent (``handler:
momentum.status_reporter``) around the S3.4.3 status draft.

- **Friday 15:00 (workspace time)**, one run per project Herald belongs to (``per: project`` on
  its schedule), for the project's owner. A project where nothing happened in the last 7 days
  gets no draft and costs no model call.
- **@mentioned** on a task ("@Herald draft a status") or **run now** on a task or project: the
  draft is for the person who asked, and Herald answers in the thread.

The draft comes from ``ai.status_draft.draft_status``: facts collected in code, claims that don't
cite a fact dropped. It is never posted by Herald: it's proposed (``create_status_update``) to
that person, who publishes it from their inbox or the run page; publishing runs with their
permissions and is marked as coming from Herald. Model calls are billed to Herald's budget.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from momentum.ai.status_draft import collect_facts, draft_status
from momentum.domain.projects.models import Project
from momentum.domain.tasks.models import TaskProject

if TYPE_CHECKING:
    from momentum.agents.extensions import HandlerResult, HandlerRun

HANDLER = "momentum.status_reporter"
WINDOW_DAYS = 7
STATUS_WORDS = {
    "on_track": "on track",
    "at_risk": "at risk",
    "off_track": "off track",
    "on_hold": "on hold",
    "complete": "complete",
}


async def _project_id(hrun: HandlerRun) -> uuid.UUID | None:
    trigger = hrun.trigger
    if trigger.get("project_id"):
        return uuid.UUID(str(trigger["project_id"]))
    if trigger.get("task_id"):
        placement = (
            (
                await hrun.session.execute(
                    select(TaskProject).where(TaskProject.task_id == uuid.UUID(trigger["task_id"]))
                )
            )
            .scalars()
            .first()
        )
        return placement.project_id if placement is not None else None
    return None


def tool_args(project_id: uuid.UUID, draft: Any) -> dict[str, Any]:
    """A status draft (``StatusUpdateIn``) as ``create_status_update``'s arguments."""
    sections = draft.sections
    return {
        "project": str(project_id),
        "status": draft.status,
        "title": draft.title,
        "summary": draft.summary,
        "completed": [i.text for i in sections.completed],
        "slipped": [i.text for i in sections.slipped],
        "blockers": [i.text for i in sections.blockers],
        "next": [i.text for i in sections.next],
    }


async def status_reporter(hrun: HandlerRun) -> HandlerResult | None:
    from momentum.agents.extensions import HandlerResult

    session, ctx = hrun.session, hrun.ctx
    project_id = await _project_id(hrun)
    if project_id is None:
        hrun.step("No project to report on")
        return HandlerResult(text="Tell me which project: mention me on one of its tasks.")
    project = await session.get(Project, project_id)
    if project is None:
        return None
    now = datetime.now(UTC)
    scheduled = hrun.trigger.get("type") == "schedule"
    if scheduled:
        today = now.astimezone(ZoneInfo(ctx.actor.timezone)).date()
        facts = await collect_facts(
            session, ctx, project_id, since=today - timedelta(days=WINDOW_DAYS), today=today
        )
        if not facts.total():
            hrun.step(f"Nothing happened in {project.name} this week: no draft")
            return None
    result = await draft_status(session, hrun.llm, ctx, project_id, now=now, days=WINDOW_DAYS)
    draft = result.draft
    hrun.step(
        f"Drafted {project.name}: {STATUS_WORDS.get(draft.status, draft.status)} ({draft.title})"
    )
    for note in result.notes:
        hrun.step(note)
    hrun.propose("create_status_update", tool_args(project_id, draft))
    lines = [
        f"Drafted this week's status for {project.name}: "
        f"{STATUS_WORDS.get(draft.status, draft.status)} ({draft.title}).",
        "It's waiting for you to review and publish (your inbox, or this run's page).",
    ]
    if draft.summary:
        lines.insert(1, draft.summary)
    return HandlerResult(text="\n".join(lines))
