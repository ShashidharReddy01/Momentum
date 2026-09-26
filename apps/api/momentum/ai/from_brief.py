"""S3.4.6 "Project from brief": a pasted (or uploaded text) brief → a plan preview (sections,
tasks, dates, people) → the user applies it and the project is created. Nothing is created
here: the plan becomes one ``create_project_from_plan`` call proposed as an AI action (medium
risk), so apply, undo and the audit trail are the same as every AI change.

The model (``smart`` alias) plans in **relative days** and names **roles**, which the server
turns into real dates and people:

- dates: ``start_on`` (default today) + offsets. With a requested end date, a plan that runs
  past it is scaled to fit (every due date ≤ the end date), with a note; the model is also told
  the deadline up front;
- people: a role's person must be a member of the project's team; anyone else (unknown, or not
  on that team) leaves the task unassigned, with a note naming them;
- the team: the one asked for (the user must belong to it) or the user's only team.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai import prompts
from momentum.ai.actions import ProposedCall, propose
from momentum.ai.breakdown import match_person
from momentum.ai.llm import LLM
from momentum.ai.structured import extract
from momentum.ai.tools.registry import ToolRegistry
from momentum.core.context import Ctx
from momentum.core.errors import NotFound, ValidationFailed
from momentum.domain.teams.models import Team, TeamMember
from momentum.domain.users.models import User

MAX_BRIEF = 20_000


class BriefTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    role: str | None = Field(default=None, max_length=80)
    start_offset: int = Field(default=0, ge=0, le=730)
    due_offset: int = Field(ge=0, le=730)
    description: str | None = Field(default=None, max_length=2000)


class BriefSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    tasks: list[BriefTask] = Field(min_length=1, max_length=30)


class BriefRole(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(min_length=1, max_length=80)
    person: str | None = Field(default=None, max_length=120)


class BriefPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    sections: list[BriefSection] = Field(min_length=1, max_length=12)
    roles: list[BriefRole] = Field(default_factory=list, max_length=20)
    open_questions: list[str] = Field(default_factory=list, max_length=10)


@dataclass
class BriefResult:
    action_id: uuid.UUID
    name: str
    team: str
    start_on: date
    end_on: date
    tasks: int
    notes: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)


async def _team(session: AsyncSession, ctx: Ctx, team_id: uuid.UUID | None) -> Team:
    mine = select(TeamMember.team_id).where(TeamMember.user_id == ctx.actor.id)
    q = select(Team).where(
        Team.workspace_id == ctx.workspace_id, Team.deleted_at.is_(None), Team.id.in_(mine)
    )
    if team_id is not None:
        team = (await session.execute(q.where(Team.id == team_id))).scalar_one_or_none()
        if team is None:
            raise NotFound("You aren't a member of that team")
        return team
    teams = list((await session.execute(q.order_by(func.lower(Team.name)))).scalars())
    if len(teams) == 1:
        return teams[0]
    if not teams:
        raise ValidationFailed("You aren't in any team, so a project can't be created")
    raise ValidationFailed("Choose the team this project belongs to", code="team_required")


def fit_dates(
    plan: BriefPlan, start_on: date, end_on: date | None
) -> tuple[dict[tuple[int, int], tuple[date, date]], list[str]]:
    """Real (start, due) per task, scaled into ``[start_on, end_on]`` when the plan runs over."""
    notes: list[str] = []
    span = max(t.due_offset for s in plan.sections for t in s.tasks)
    scale = 1.0
    if end_on is not None:
        window = (end_on - start_on).days
        if window < 0:
            raise ValidationFailed("The end date is before the start date")
        if span > window:
            scale = window / span if span else 1.0
            notes.append(
                f"The plan needed {span} days; dates were compressed to finish by {end_on}."
            )
    out: dict[tuple[int, int], tuple[date, date]] = {}
    for si, sec in enumerate(plan.sections):
        for ti, t in enumerate(sec.tasks):
            due_off = math.floor(t.due_offset * scale)
            start_off = min(math.floor(t.start_offset * scale), due_off)
            out[(si, ti)] = (
                start_on + timedelta(days=start_off),
                start_on + timedelta(days=due_off),
            )
    return out, notes


async def plan_from_brief(
    session: AsyncSession,
    llm: LLM,
    ctx: Ctx,
    registry: ToolRegistry,
    brief: str,
    *,
    now: datetime,
    name: str | None = None,
    team_id: uuid.UUID | None = None,
    start_on: date | None = None,
    end_on: date | None = None,
) -> BriefResult:
    brief = brief.strip()
    if not brief:
        raise ValidationFailed("Paste or upload a brief first")
    if len(brief) > MAX_BRIEF:
        raise ValidationFailed(f"The brief is too long (at most {MAX_BRIEF} characters)")
    team = await _team(session, ctx, team_id)
    today = now.astimezone(ZoneInfo(ctx.actor.timezone)).date()
    start = start_on or today
    if end_on is not None and end_on < start:
        raise ValidationFailed("The end date is before the start date")
    prompt = prompts.load("project_brief")
    deadline = (
        f" The project starts on {start} and must finish by {end_on}: every due_offset must be "
        f"at most {(end_on - start).days}."
        if end_on
        else f" The project starts on {start}."
    )
    text = brief.replace("<", "&lt;").replace(">", "&gt;")
    plan = await extract(
        llm,
        ctx,
        prompt=prompt,
        system=prompt.render(deadline=deadline),
        user=f'<data source="brief">\n{text}\n</data>',
        schema=BriefPlan,
        description="Submit the project plan.",
    )
    notes: list[str] = []
    people = list(
        (
            await session.execute(
                select(User)
                .join(TeamMember, TeamMember.user_id == User.id)
                .where(TeamMember.team_id == team.id, User.status != "disabled")
            )
        ).scalars()
    )
    role_person: dict[str, User | None] = {}
    for r in plan.roles:
        key = r.role.strip().lower()
        if not r.person:
            role_person[key] = None
            notes.append(f"Nobody is named as {r.role}; those tasks are unassigned.")
            continue
        person = match_person(r.person, people)
        role_person[key] = person
        if person is None:
            notes.append(
                f"{r.person} ({r.role}) isn't a member of {team.name}; their tasks are unassigned."
            )
    dates, date_notes = fit_dates(plan, start, end_on)
    notes += date_notes
    sections = []
    for si, sec in enumerate(plan.sections):
        items = []
        for ti, t in enumerate(sec.tasks):
            s_on, d_on = dates[(si, ti)]
            item: dict[str, object] = {"title": t.title, "due_on": d_on.isoformat()}
            if s_on < d_on:
                item["start_on"] = s_on.isoformat()
            person = role_person.get((t.role or "").strip().lower())
            if person is not None:
                item["assignee"] = str(person.id)
            if t.description:
                item["description"] = t.description
            items.append(item)
        sections.append({"name": sec.name, "tasks": items})
    project_name = (name or "").strip() or plan.name.strip()
    count = sum(len(sec.tasks) for sec in plan.sections)
    proposal = await propose(
        session,
        ctx,
        registry,
        [
            ProposedCall(
                "create_project_from_plan",
                {"name": project_name, "team": str(team.id), "sections": sections},
            )
        ],
        source="inline",
        summary=f"Create project {project_name} ({len(sections)} sections, {count} tasks)",
    )
    if proposal.action is None:
        detail = "; ".join(o.result.summary for _, o in proposal.failures)
        raise ValidationFailed(detail[:300] or "The plan couldn't be previewed")
    last_due = max(d for _, d in dates.values())
    return BriefResult(
        proposal.action.id,
        project_name,
        team.name,
        start,
        last_due,
        count,
        notes,
        [q.strip() for q in plan.open_questions if q.strip()],
    )
