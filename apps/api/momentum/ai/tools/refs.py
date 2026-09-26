"""References the model uses to point at things, and their resolution.

A model rarely knows ids. It knows keys (``T-123``), names ("Website Revamp", "Ana") and fuzzy
titles ("the pricing copy task"). Resolution never guesses: a reference that matches more than
one thing fails with the candidates, so the caller can ask the user which one they meant
(ai-architecture §3; the J7 acceptance criterion). Every lookup goes through the same
visibility rules as the UI (``domain/access.py``), and a thing the actor can't see is reported
exactly like one that doesn't exist.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, or_, select

from momentum.ai.tools.base import ToolContext, ToolError
from momentum.ai.tools.views import task_briefs
from momentum.core.errors import NotFound
from momentum.core.ids import task_key
from momentum.domain.access import get_visible_project, get_visible_task, visible_projects_clause
from momentum.domain.projects.models import Project
from momentum.domain.sections.models import Section
from momentum.domain.sections.service import list_sections
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.teams.models import Team, TeamMember
from momentum.domain.users.models import User

KEY_RE = re.compile(r"^\s*[Tt]-(\d{1,9})\s*$")
MAX_CANDIDATES = 8
SELF_WORDS = {"me", "myself", "i"}


class TaskRef(BaseModel):
    """Exactly one of ``id``, ``key`` or ``title_query``. A bare string is accepted too:
    ``"T-12"`` is read as a key, a UUID as an id, anything else as a title query."""

    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID | None = Field(default=None, description="Task id, when known exactly")
    key: str | None = Field(
        default=None, pattern=r"^[Tt]-\d{1,9}$", description='Task key such as "T-123"'
    )
    title_query: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="Words from the task title, when neither the id nor the key is known",
    )
    project: str | None = Field(
        default=None,
        max_length=200,
        description="Project name or id to narrow a title_query",
    )

    @model_validator(mode="before")
    @classmethod
    def _from_string(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        if KEY_RE.match(value):
            return {"key": value.strip()}
        try:
            return {"id": str(uuid.UUID(value.strip()))}
        except ValueError:
            return {"title_query": value}

    @model_validator(mode="after")
    def _exactly_one(self) -> TaskRef:
        given = [v for v in (self.id, self.key, self.title_query) if v is not None]
        if len(given) != 1:
            raise ValueError("give exactly one of id, key or title_query")
        if self.project is not None and self.title_query is None:
            raise ValueError("project only narrows a title_query")
        return self


def _as_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value.strip())
    except ValueError:
        return None


# ---------------- tasks ----------------


async def resolve_task(tc: ToolContext, ref: TaskRef) -> tuple[Task, TaskProject | None, str]:
    """The task, its primary placement and the actor's role on it (``get_visible_task``)."""
    s, ctx = tc.session, tc.ctx
    if ref.id is not None:
        return await _visible(tc, ref.id, f"No task with id {ref.id} that you can see")
    if ref.key is not None:
        m = KEY_RE.match(ref.key)
        assert m is not None  # the field pattern guarantees it
        number = int(m.group(1))
        task_id = (
            await s.execute(
                select(Task.id).where(Task.workspace_id == ctx.workspace_id, Task.number == number)
            )
        ).scalar_one_or_none()
        missing = f"No task {task_key(number)} that you can see"
        if task_id is None:
            raise ToolError("not_found", missing)
        return await _visible(tc, task_id, missing)
    assert ref.title_query is not None
    return await _by_title(tc, ref.title_query, ref.project)


async def _visible(
    tc: ToolContext, task_id: uuid.UUID, missing: str
) -> tuple[Task, TaskProject | None, str]:
    try:
        return await get_visible_task(tc.session, tc.ctx, task_id)
    except NotFound:
        raise ToolError("not_found", missing) from None


async def _by_title(
    tc: ToolContext, query: str, project: str | None
) -> tuple[Task, TaskProject | None, str]:
    s, ctx = tc.session, tc.ctx
    q = " ".join(query.split())
    visible_projects = select(Project.id).where(visible_projects_clause(ctx))
    stmt = select(Task).where(
        Task.workspace_id == ctx.workspace_id,
        Task.deleted_at.is_(None),
        or_(
            func.lower(Task.title).contains(q.lower(), autoescape=True),
            Task.search_tsv.op("@@")(func.plainto_tsquery("simple", q)),
        ),
        # A cheap SQL pre-filter; every candidate is then checked with get_visible_task, which
        # also covers tasks visible only personally (assignee, creator, follower).
        or_(
            Task.id.in_(
                select(TaskProject.task_id).where(TaskProject.project_id.in_(visible_projects))
            ),
            Task.parent_id.is_not(None),
            Task.assignee_id == ctx.actor.id,
            Task.created_by == ctx.actor.id,
        ),
    )
    if project is not None:
        proj, _ = await resolve_project(tc, project)
        placed = select(TaskProject.task_id).where(TaskProject.project_id == proj.id)
        stmt = stmt.where(or_(Task.id.in_(placed), Task.parent_id.in_(placed)))
    exact_first = (func.lower(Task.title) == q.lower()).desc()
    rows = (
        (
            await s.execute(
                stmt.order_by(
                    exact_first, Task.completed_at.is_not(None), Task.number.desc()
                ).limit(25)
            )
        )
        .scalars()
        .all()
    )
    found: list[tuple[Task, TaskProject | None, str]] = []
    for task in rows:
        try:
            found.append(await get_visible_task(s, ctx, task.id))
        except NotFound:
            continue
    exact = [f for f in found if f[0].title.lower() == q.lower()]
    if len(exact) == 1:
        return exact[0]
    if len(found) == 1:
        return found[0]
    if not found:
        raise ToolError("not_found", f'No task matching "{q}" that you can see')
    pool = exact or found
    candidates = await task_candidates(tc, [t for t, _, _ in pool[:MAX_CANDIDATES]])
    raise ToolError(
        "ambiguous",
        f'"{q}" matches {len(pool)} tasks; ask the user which one they mean',
        candidates=candidates,
    )


async def task_candidates(tc: ToolContext, tasks: list[Task]) -> list[dict[str, Any]]:
    return [
        {k: b[k] for k in ("key", "title", "project", "status") if k in b}
        for b in await task_briefs(tc, tasks)
    ]


# ---------------- projects, sections, teams ----------------


def _pick(
    items: list[Any], value: str, name_of: Any, what: str, describe: Any
) -> Any:  # shared exact-then-contains matching with ambiguity reporting
    v = " ".join(value.split()).lower()
    exact = [i for i in items if name_of(i).lower() == v]
    if len(exact) == 1:
        return exact[0]
    partial = exact or [i for i in items if v in name_of(i).lower()]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise ToolError("not_found", f'No {what} named "{value}" that you can see')
    raise ToolError(
        "ambiguous",
        f'"{value}" matches {len(partial)} {what}s; ask the user which one they mean',
        candidates=[describe(i) for i in partial[:MAX_CANDIDATES]],
    )


async def resolve_project(tc: ToolContext, value: str) -> tuple[Project, str]:
    """A visible project by id or name, with the actor's role."""
    s, ctx = tc.session, tc.ctx
    pid = _as_uuid(value)
    if pid is not None:
        try:
            return await get_visible_project(s, ctx, pid)
        except NotFound:
            raise ToolError("not_found", f"No project with id {pid} that you can see") from None
    projects = list(
        (
            await s.execute(
                select(Project)
                .where(visible_projects_clause(ctx), Project.is_template.is_(False))
                .order_by(func.lower(Project.name))
            )
        )
        .scalars()
        .all()
    )
    chosen: Project = _pick(
        projects,
        value,
        lambda p: p.name,
        "project",
        lambda p: {"id": str(p.id), "name": p.name},
    )
    return await get_visible_project(s, ctx, chosen.id)


async def resolve_section(tc: ToolContext, project_id: uuid.UUID, value: str) -> Section:
    sections = await list_sections(tc.session, project_id)
    sid = _as_uuid(value)
    if sid is not None:
        for sec in sections:
            if sec.id == sid:
                return sec
        raise ToolError("not_found", f"No section with id {sid} in that project")
    chosen: Section = _pick(
        sections, value, lambda x: x.name, "section", lambda x: {"id": str(x.id), "name": x.name}
    )
    return chosen


async def resolve_team(tc: ToolContext, value: str) -> Team:
    """A team the actor belongs to (or any team, for a workspace admin)."""
    s, ctx = tc.session, tc.ctx
    stmt = select(Team).where(Team.workspace_id == ctx.workspace_id, Team.deleted_at.is_(None))
    if not ctx.actor.is_admin:
        stmt = stmt.where(
            Team.id.in_(select(TeamMember.team_id).where(TeamMember.user_id == ctx.actor.id))
        )
    teams = list((await s.execute(stmt.order_by(func.lower(Team.name)))).scalars().all())
    tid = _as_uuid(value)
    if tid is not None:
        for team in teams:
            if team.id == tid:
                return team
        raise ToolError("not_found", f"No team with id {tid} that you belong to")
    chosen: Team = _pick(
        teams, value, lambda t: t.name, "team", lambda t: {"id": str(t.id), "name": t.name}
    )
    return chosen


# ---------------- people ----------------


async def resolve_person(tc: ToolContext, value: str) -> User:
    """A workspace member by "me", id, email or name (full name, then first name, then part)."""
    s, ctx = tc.session, tc.ctx
    v = value.strip().lstrip("@").strip()
    if v.lower() in SELF_WORDS:
        if ctx.actor.id is None:
            raise ToolError("not_found", "There is no current user to refer to as me")
        me = await s.get(User, ctx.actor.id)
        assert me is not None
        return me
    people = list(
        (
            await s.execute(
                select(User)
                .where(User.workspace_id == ctx.workspace_id, User.status != "disabled")
                .order_by(func.lower(User.name))
            )
        )
        .scalars()
        .all()
    )
    uid = _as_uuid(v)
    if uid is not None:
        for p in people:
            if p.id == uid:
                return p
        raise ToolError("not_found", f"No person with id {uid} in this workspace")
    if "@" in v:
        for p in people:
            if p.email.lower() == v.lower():
                return p
        raise ToolError("not_found", f"No person with email {v} in this workspace")
    low = " ".join(v.split()).lower()
    first = [p for p in people if p.name.lower() == low] or [
        p for p in people if p.name.lower().split()[:1] == [low]
    ]
    if len(first) == 1:
        return first[0]
    chosen: User = _pick(
        first or people,
        v,
        lambda p: p.name,
        "person",
        lambda p: {"id": str(p.id), "name": p.name, "email": p.email},
    )
    return chosen
