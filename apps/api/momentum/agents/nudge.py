"""S5.3.4 Nudge · Nudger: a built-in code-backed agent (``handler: momentum.nudger``).

Weekdays at 10:00 (workspace time), one run per project it has been added to (``per: project``).
It picks, in code, the open top-level tasks with a person assigned that are either overdue by
more than a day or untouched for five days, and skips a task when:

- it waits on someone else's unfinished work (an open blocker assigned to another person);
- its assignee snoozed nudges on it (``my_task_placements.nudge_snoozed_until``, kickoff Q7) or
  turned nudges off altogether (the ``nudge_me`` notification preference);
- Nudge already commented on it in the last 2 days, or has escalated it already.

Each remaining task gets one short comment @mentioning the assignee; the fourth one escalates:
it also @mentions the project owner, and Nudge stops there. The model only phrases the messages
(one call per run, ``nudge`` prompt); a message that cites another task or runs long is replaced
by a plain template, as is every message when the gateway is down. Comments are Nudge's own
(``auto``, comments only): marked as AI, and removable like any comment.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from momentum.ai import prompts
from momentum.ai.context.tokens import safe
from momentum.ai.errors import AIUnavailable
from momentum.ai.structured import extract
from momentum.core.ids import task_key
from momentum.domain.comments.models import Comment
from momentum.domain.comments.service import create_comment
from momentum.domain.mytasks.models import MyTaskPlacement
from momentum.domain.projects.models import Project
from momentum.domain.tasks.models import Task, TaskDependency, TaskProject
from momentum.domain.users.models import User

if TYPE_CHECKING:
    from momentum.agents.extensions import HandlerResult, HandlerRun

HANDLER = "momentum.nudger"
OVERDUE_AFTER_DAYS = 1  # overdue by more than this
STALE_AFTER = timedelta(days=5)
NUDGE_EVERY = timedelta(days=2)
ESCALATE_AT = 4  # the 4th comment on a task escalates (after 3 nudges), then Nudge stops
MAX_PER_RUN = 20
MESSAGE_CHARS = 280
_KEY = re.compile(r"\bT-\d+\b")


@dataclass
class Candidate:
    task: Task
    assignee: User
    reason: str  # "overdue" | "stale"
    days: int
    nudges: int  # Nudge's earlier comments on it
    key: str = ""

    @property
    def escalate(self) -> bool:
        return self.nudges + 1 >= ESCALATE_AT


class _Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(max_length=20)
    text: str = Field(min_length=1, max_length=600)


class _Messages(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: list[_Message] = Field(default_factory=list, max_length=MAX_PER_RUN)


def _nudges_allowed(person: User) -> bool:
    prefs = (person.prefs or {}).get("notifications") or {}
    return prefs.get("nudge_me", True) is not False


async def candidates(
    hrun: HandlerRun, project_id: uuid.UUID, today: date, now: datetime
) -> list[Candidate]:
    session = hrun.session
    me = hrun.ctx.actor.id
    rows = (
        await session.execute(
            select(Task, User)
            .join(TaskProject, TaskProject.task_id == Task.id)
            .join(User, User.id == Task.assignee_id)
            .where(
                TaskProject.project_id == project_id,
                Task.parent_id.is_(None),
                Task.deleted_at.is_(None),
                Task.completed_at.is_(None),
                User.is_agent.is_(False),
                User.status == "active",
            )
            .order_by(Task.due_on.asc().nulls_last(), Task.number)
        )
    ).all()
    out: list[Candidate] = []
    for task, person in rows:
        if not _nudges_allowed(person):
            continue
        overdue_days = (today - task.due_on).days if task.due_on else 0
        last_human = await session.scalar(
            select(func.max(Comment.created_at)).where(
                Comment.task_id == task.id,
                Comment.deleted_at.is_(None),
                Comment.author_id != me,
            )
        )
        touched = max(t for t in (task.updated_at, last_human) if t is not None)
        if overdue_days > OVERDUE_AFTER_DAYS:
            reason, days = "overdue", overdue_days
        elif now - touched >= STALE_AFTER:
            reason, days = "stale", (now - touched).days
        else:
            continue
        mine = (
            await session.execute(
                select(func.count(), func.max(Comment.created_at)).where(
                    Comment.task_id == task.id,
                    Comment.author_id == me,
                    Comment.deleted_at.is_(None),
                )
            )
        ).one()
        count, last_nudge = int(mine[0]), mine[1]
        if count >= ESCALATE_AT or (last_nudge is not None and now - last_nudge < NUDGE_EVERY):
            continue
        snoozed = await session.scalar(
            select(MyTaskPlacement.nudge_snoozed_until).where(
                MyTaskPlacement.user_id == person.id, MyTaskPlacement.task_id == task.id
            )
        )
        if snoozed is not None and snoozed >= today:
            continue
        waiting = await session.scalar(
            select(func.count())
            .select_from(TaskDependency)
            .join(Task, Task.id == TaskDependency.depends_on_id)
            .where(
                TaskDependency.task_id == task.id,
                Task.deleted_at.is_(None),
                Task.completed_at.is_(None),
                (Task.assignee_id.is_(None)) | (Task.assignee_id != person.id),
            )
        )
        if waiting:
            continue
        out.append(Candidate(task, person, reason, days, count, task_key(task.number)))
        if len(out) >= MAX_PER_RUN:
            break
    return out


def template(c: Candidate, owner: User | None) -> str:
    first = c.assignee.name.split()[0]
    what = (
        f"is {c.days} days overdue" if c.reason == "overdue" else f"hasn't moved in {c.days} days"
    )
    if c.escalate and owner is not None:
        return (
            f"{c.key} {what} and has had {c.nudges} reminders. {owner.name.split()[0]}, "
            f"could you check in with {first}?"
        )
    return f"Hi {first}, {c.key} {what}. Do you need help, or a new date?"


async def _phrased(hrun: HandlerRun, found: list[Candidate], owner: User | None) -> dict[str, str]:
    """The model's wording per task key; anything unusable falls back to the template."""
    lines = []
    for c in found:
        what = (
            f"overdue by {c.days} days" if c.reason == "overdue" else f"untouched for {c.days} days"
        )
        role = f"escalation to the owner {owner.name}" if c.escalate and owner else "reminder"
        lines.append(
            f"- {c.key} “{safe(c.task.title)}”, assignee {safe(c.assignee.name)}, {what}, "
            f"{c.nudges} earlier reminders, write a {role}"
        )
    prompt = prompts.load("nudge")
    try:
        out = await extract(
            hrun.llm,
            hrun.ctx,
            prompt=prompt,
            system=prompt.body,
            user='<data source="tasks">\n' + "\n".join(lines) + "\n</data>",
            schema=_Messages,
            description="Submit one message per task.",
        )
    except AIUnavailable:
        hrun.step("The model was unavailable: used plain reminders")
        return {}
    phrased: dict[str, str] = {}
    for m in out.messages:
        text = " ".join(m.text.split())
        if len(text) <= MESSAGE_CHARS and set(_KEY.findall(text)) <= {m.key}:
            phrased[m.key] = text
    return phrased


def _doc(text: str, mention: list[User]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    for person in mention:
        nodes += [
            {
                "type": "mention",
                "attrs": {"id": str(person.id), "label": person.name, "kind": "user"},
            },
            {"type": "text", "text": " "},
        ]
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [*nodes, {"type": "text", "text": text}]}],
    }


async def nudger(hrun: HandlerRun) -> HandlerResult | None:
    from momentum.agents.extensions import HandlerResult

    session, ctx = hrun.session, hrun.ctx
    if not ctx.actor.is_agent or not hrun.trigger.get("project_id"):
        hrun.step("Nudge runs on a schedule, once per project")
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
    found = await candidates(hrun, project.id, today, now)
    if not found:
        hrun.step(f"Nothing to nudge in {project.name}")
        return None
    owner = await session.get(User, project.owner_id) if project.owner_id else None
    if owner is not None and (owner.status != "active" or owner.is_agent):
        owner = None
    phrased = await _phrased(hrun, found, owner)
    done = []
    for c in found:
        text = phrased.get(c.key) or template(c, owner)
        who = [c.assignee]
        if c.escalate and owner is not None and owner.id != c.assignee.id:
            who.append(owner)
        await create_comment(session, ctx, c.task.id, _doc(text, who))
        verb = "Escalated" if c.escalate else "Nudged"
        hrun.step(f"{verb} {c.key} ({c.reason}, {c.days} days)")
        done.append(f"- {c.key} {c.task.title}: {verb.lower()} ({c.reason})")
    return HandlerResult(text=f"{project.name}:\n" + "\n".join(done))
