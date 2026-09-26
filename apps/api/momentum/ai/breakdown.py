"""S3.4.2 "Break into subtasks": Mo proposes 3 to 10 subtasks for a task, the user reviews them in
a PreviewCard and applies (or not). Nothing is created here.

The model sees the task (``task_ctx``) and the project's people, and submits a structured list
(``ai/structured.py``). Its output is then checked, not trusted:

- assignees must be **people on the task's project** (explicit members, plus the team's members
  for a team-visible project; viewers excluded). Anyone else — unknown names, people outside the
  project — is dropped with a note, never assigned;
- due dates before today, or after the parent's due date, are dropped with a note;
- titles that repeat an existing subtask (or each other) are skipped with a note.

What remains becomes one ``create_subtasks`` call, previewed through ``ai/actions.py`` like any
AI change (source ``inline``), so apply, stale checks and one-step undo come for free.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai import prompts
from momentum.ai.actions import ProposedCall, propose
from momentum.ai.context import task_ctx
from momentum.ai.context.tokens import safe
from momentum.ai.llm import LLM
from momentum.ai.structured import extract
from momentum.ai.tools.registry import ToolRegistry
from momentum.core.context import Ctx
from momentum.core.errors import Forbidden, ValidationFailed
from momentum.core.ids import task_key
from momentum.domain.access import ROLE_RANK, get_visible_task
from momentum.domain.projects.models import Project, ProjectMember
from momentum.domain.tasks.models import Task
from momentum.domain.teams.models import TeamMember
from momentum.domain.users.models import User

MIN_SUBTASKS, MAX_SUBTASKS = 3, 10


class ProposedSubtask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    assignee: str | None = Field(default=None, max_length=200, description="A project member")
    due_on: date | None = None


class Breakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subtasks: list[ProposedSubtask] = Field(min_length=MIN_SUBTASKS, max_length=MAX_SUBTASKS)


@dataclass
class BreakdownResult:
    action_id: uuid.UUID | None
    notes: list[str] = field(default_factory=list)
    count: int = 0


async def project_people(session: AsyncSession, project: Project) -> list[User]:
    """Who can be assigned work on a project: explicit members except viewers, plus the
    team's members when the project is team-visible. Disabled users excluded."""
    explicit = select(ProjectMember.user_id).where(
        ProjectMember.project_id == project.id, ProjectMember.role != "viewer"
    )
    viewers = select(ProjectMember.user_id).where(
        ProjectMember.project_id == project.id, ProjectMember.role == "viewer"
    )
    ids = explicit
    if project.privacy == "team":
        team = select(TeamMember.user_id).where(TeamMember.team_id == project.team_id)
        ids = explicit.union(team)  # type: ignore[assignment]
    rows = await session.execute(
        select(User)
        .where(User.id.in_(ids), User.id.not_in(viewers), User.status != "disabled")
        .order_by(func.lower(User.name))
    )
    return list(rows.scalars())


def _match_person(name: str, people: list[User]) -> User | None:
    v = name.strip().lstrip("@").lower()
    if not v:
        return None
    keys: list[Callable[[User], str]] = [
        lambda p: p.email.lower(),
        lambda p: p.name.lower(),
        lambda p: p.name.lower().split()[0],
    ]
    for key in keys:
        hits = [p for p in people if key(p) == v]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            return None  # ambiguous: never guess
    return None


async def break_down(
    session: AsyncSession,
    llm: LLM,
    ctx: Ctx,
    registry: ToolRegistry,
    task_id: uuid.UUID,
    *,
    hint: str | None,
    now: datetime,
) -> BreakdownResult:
    task, placement, role = await get_visible_task(session, ctx, task_id)
    if ROLE_RANK[role] < ROLE_RANK["editor"]:
        raise Forbidden("You can't add subtasks to this task")
    project = await session.get(Project, placement.project_id) if placement else None
    people = await project_people(session, project) if project else []
    today = now.astimezone(ZoneInfo(ctx.actor.timezone)).date()
    prompt = prompts.load("breakdown")
    user = [
        (await task_ctx(session, ctx, task.id, now=now)).text,
        "Project members: " + (", ".join(safe(p.name) for p in people) or "(none)"),
    ]
    if hint and hint.strip():
        user.append(f'<data source="guidance">{safe(hint)[:500]}</data>')
    out = await extract(
        llm,
        ctx,
        prompt=prompt,
        system=prompt.render(today=today.isoformat()),
        user="\n\n".join(user),
        schema=Breakdown,
        description="Submit the proposed subtasks.",
    )

    existing = {
        t.lower()
        for t in (
            await session.execute(
                select(Task.title).where(Task.parent_id == task.id, Task.deleted_at.is_(None))
            )
        ).scalars()
    }
    notes: list[str] = []
    items: list[dict[str, object]] = []
    for s in out.subtasks:
        title = " ".join(s.title.split())
        if title.lower() in existing:
            notes.append(f"Skipped “{title}”: it's already a subtask or listed twice.")
            continue
        existing.add(title.lower())
        item: dict[str, object] = {"title": title}
        if s.assignee:
            person = _match_person(s.assignee, people)
            if person is None:
                notes.append(
                    f"“{title}”: {s.assignee} isn't someone on this project, so it's unassigned."
                )
            else:
                item["assignee"] = str(person.id)
        if s.due_on:
            if s.due_on < today:
                notes.append(f"“{title}”: dropped a due date in the past ({s.due_on}).")
            elif task.due_on and s.due_on > task.due_on:
                notes.append(
                    f"“{title}”: dropped a due date after {task_key(task.number)}'s ({s.due_on})."
                )
            else:
                item["due_on"] = s.due_on.isoformat()
        items.append(item)
    if not items:
        raise ValidationFailed("Mo didn't come up with any new subtasks. Try adding guidance.")
    p = await propose(
        session,
        ctx,
        registry,
        [ProposedCall("create_subtasks", {"parent": task_key(task.number), "subtasks": items})],
        source="inline",
        source_id=task.id,
        summary=f"Break {task_key(task.number)} into {len(items)} subtasks",
    )
    if p.action is None:
        detail = "; ".join(out.result.summary for _, out in p.failures)
        raise ValidationFailed(detail[:300] or "The subtasks couldn't be previewed")
    return BreakdownResult(p.action.id, notes, len(items))
