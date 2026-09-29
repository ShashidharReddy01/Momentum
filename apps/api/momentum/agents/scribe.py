"""S5.3.6 Scribe · Meeting Notes: a built-in code-backed agent
(``handler: momentum.meeting_notes``).

Give it meeting notes or a transcript: pasted or loaded from a file with "Run now" (txt, md,
vtt), or on a task, where it reads the task's description and the text of its attachments (docx,
pdf, txt, md, vtt: extracted on upload). It returns the decisions and one proposed task per
action item, with an owner only when the notes name someone on the project, a due date only when
the notes give one (never in the past), and a link back to where the notes came from. The tasks
are proposed (``confirm``) to the person who ran it; on a task, Scribe also answers in the
thread. Email-in (Phase 7) will hand an email's body to the same handler as its ``input``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from momentum.ai import prompts
from momentum.ai.breakdown import match_person, project_people
from momentum.ai.context.tokens import safe
from momentum.ai.structured import extract
from momentum.core.ids import task_key
from momentum.domain.attachments.models import Attachment
from momentum.domain.projects.models import Project
from momentum.domain.tasks.models import Task, TaskProject

if TYPE_CHECKING:
    from momentum.agents.extensions import HandlerResult, HandlerRun

HANDLER = "momentum.meeting_notes"
MAX_NOTES = 30_000
MAX_ITEMS = 20  # one proposal holds at most 20 operations


class ActionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=300, description="Verb-first, e.g. 'Send the deck'")
    owner: str | None = Field(default=None, max_length=200, description="A name from the notes")
    due_on: date | None = None
    quote: str = Field(default="", max_length=300, description="The line it came from")


class MeetingSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200, description="What the meeting was, briefly")
    decisions: list[str] = Field(default_factory=list, max_length=20)
    action_items: list[ActionItem] = Field(default_factory=list, max_length=40)


async def _notes(hrun: HandlerRun) -> tuple[str, Task | None]:
    trigger = hrun.trigger
    task = None
    if trigger.get("task_id"):
        task = await hrun.session.get(Task, uuid.UUID(str(trigger["task_id"])))
    text = str(trigger.get("input") or "").strip()
    if text or task is None:
        return text[:MAX_NOTES], task
    parts = [task.description_text or ""]
    files = (
        await hrun.session.execute(
            select(Attachment)
            .where(
                Attachment.task_id == task.id,
                Attachment.deleted_at.is_(None),
                Attachment.text_extract.is_not(None),
            )
            .order_by(Attachment.created_at)
        )
    ).scalars()
    for f in files:
        parts.append(f"[{f.filename}]\n{f.text_extract}")
        hrun.step(f"Read {f.filename}")
    return "\n\n".join(p for p in parts if p.strip())[:MAX_NOTES], task


async def _project(hrun: HandlerRun, task: Task | None) -> Project | None:
    if hrun.trigger.get("project_id"):
        return await hrun.session.get(Project, uuid.UUID(str(hrun.trigger["project_id"])))
    if task is not None:
        placement = (
            (await hrun.session.execute(select(TaskProject).where(TaskProject.task_id == task.id)))
            .scalars()
            .first()
        )
        if placement is not None:
            return await hrun.session.get(Project, placement.project_id)
    return None


async def meeting_notes(hrun: HandlerRun) -> HandlerResult | None:
    from momentum.agents.extensions import HandlerResult

    notes, task = await _notes(hrun)
    if not notes:
        hrun.step("No notes to read")
        return HandlerResult(
            text="Paste the notes when you run me, or run me on a task that has them attached."
        )
    project = await _project(hrun, task)
    if project is None:
        hrun.step("No project for the action items")
        return HandlerResult(
            text="Which project should the action items go in? Pick one when you run me."
        )
    ctx = hrun.ctx
    person_tz = ctx.acting_for.timezone if ctx.acting_for else ctx.actor.timezone
    today = datetime.now(UTC).astimezone(ZoneInfo(person_tz)).date()
    people = await project_people(hrun.session, project)
    prompt = prompts.load("meeting_notes")
    summary = await extract(
        hrun.llm,
        ctx,
        prompt=prompt,
        system=prompt.render(
            today=today.isoformat(), people=", ".join(safe(p.name) for p in people) or "(none)"
        ),
        user=f'<data source="meeting_notes">\n{safe(notes)}\n</data>',
        schema=MeetingSummary,
        description="Submit the decisions and action items.",
    )
    source = f" (from {task_key(task.number)})" if task is not None else ""
    notes_out: list[str] = []
    lines: list[str] = []
    for item in summary.action_items[:MAX_ITEMS]:
        args: dict[str, Any] = {
            "project": str(project.id),
            "title": item.title,
            "description": (
                f"From the meeting notes: {summary.title}{source}."
                + (f'\n"{item.quote}"' if item.quote else "")
            ),
        }
        owner = match_person(item.owner, people) if item.owner else None
        if item.owner and owner is None:
            notes_out.append(f"“{item.title}”: {item.owner} isn't on {project.name}; unassigned.")
        elif owner is not None:
            args["assignee"] = owner.email
        if item.due_on is not None:
            if item.due_on < today:
                notes_out.append(f"“{item.title}”: dropped a date in the past ({item.due_on}).")
            else:
                args["due_on"] = item.due_on.isoformat()
        hrun.propose("create_task", args)
        who = f" ({owner.name})" if owner else ""
        when = f", due {args['due_on']}" if "due_on" in args else ""
        lines.append(f"- {item.title}{who}{when}")
    if len(summary.action_items) > MAX_ITEMS:
        notes_out.append(f"Kept the first {MAX_ITEMS} action items.")
    for n in notes_out:
        hrun.step(n)
    out = [f"{summary.title}"]
    if summary.decisions:
        out += ["Decisions:", *(f"- {d}" for d in summary.decisions)]
    if lines:
        out += [
            f"Action items, proposed as tasks in {project.name} for you to review and apply:",
            *lines,
        ]
    else:
        out.append("No action items in these notes.")
    out += notes_out
    return HandlerResult(text="\n".join(out))
