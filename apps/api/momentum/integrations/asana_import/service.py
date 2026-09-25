"""S2.7.1: the Asana importer's orchestration (`docs/integrations/asana-import.md §5`).

**Runs synchronously inside the API request, not as a background job** — a deliberate deviation
from the roadmap's "background job with progress events," disclosed here and in STATUS.md rather
than silently narrowed. The spec is explicit that the PAT is "never stored"; a Procrastinate job's
arguments sit in that queue's own database table until a worker dequeues them, which would put the
PAT at rest in the database for however long that takes — exactly what "never stored" rules out.
Building a genuinely job-queue-safe way to hand a short-lived secret to a worker (an ephemeral,
worker-affinity cache, or a client-held token the worker calls back for) is real infrastructure
this codebase doesn't have yet, and disproportionate to build for this slice. Running inline means
the PAT lives only in this request's `AsanaClient` instance and is never durable anywhere — at the
cost of no incremental progress streaming and no resumability from a partial run (also disclosed;
see STATUS.md). The `ImportJob` row this still writes give the frontend/AC a real summary to show,
just computed by the time the HTTP response returns rather than polled.

**Also intentionally not built this slice** (see STATUS.md's full list): dependencies, comments/
stories, likes/reactions, attachments, custom fields and their values, status updates, portfolios/
goals, the HTML→Tiptap rich-text converter (plain-text fallback only, see `mapping.html_to_plain`),
subtask recursion past one level, and per-page checkpointing/resume. Idempotency (the AC's "re-run
updates rather than duplicates") is implemented as *skip-if-already-linked*, not field-level
update-in-place — re-running is safe (nothing duplicates) but doesn't push changed Asana field
values into an already-imported row.

A failure partway through raises out of `run_import` and — since it runs inside the caller's own
`uow.transaction()` — rolls back everything this call wrote, `ImportJob` row included. That's a
deliberate simplification paired with "no resumability": a failed run leaves nothing partial to
clean up or resume from, at the cost of not keeping a persisted "failed" record to show the user
(the router surfaces the error directly in its response instead).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.core.ordering import key_between
from momentum.domain.integrations.models import ExternalLink, ImportJob
from momentum.domain.projects.models import Project
from momentum.domain.sections.models import Section
from momentum.domain.tags.models import Tag, TaskTag
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.tasks.service import _next_number
from momentum.domain.teams.models import Team, TeamMember
from momentum.domain.users.models import User
from momentum.integrations.asana_import.mapping import html_to_plain, map_privacy, map_task_type

DEFAULT_TAG_COLOR = "#94a3b8"


class AsanaClientLike(Protocol):
    async def team_users(self, team_gid: str) -> list[dict[str, Any]]: ...
    async def projects(self, team_gid: str) -> list[dict[str, Any]]: ...
    async def sections(self, project_gid: str) -> list[dict[str, Any]]: ...
    async def tasks(self, section_gid: str) -> list[dict[str, Any]]: ...
    async def subtasks(self, task_gid: str) -> list[dict[str, Any]]: ...
    async def tags(self, workspace_gid: str) -> list[dict[str, Any]]: ...


class _Counters:
    def __init__(self) -> None:
        self.teams = 0
        self.projects = 0
        self.sections = 0
        self.tasks = 0
        self.subtasks = 0
        self.tags = 0
        self.users_matched = 0
        self.users_unmatched = 0
        self.skipped: list[str] = []

    def as_dict(self) -> dict[str, Any]:
        return {
            "teams": self.teams,
            "projects": self.projects,
            "sections": self.sections,
            "tasks": self.tasks,
            "subtasks": self.subtasks,
            "tags": self.tags,
            "users_matched": self.users_matched,
            "users_unmatched": self.users_unmatched,
            "skipped": self.skipped,
        }


async def _get_or_create(
    session: AsyncSession,
    ctx: Ctx,
    *,
    entity_type: str,
    external_id: str,
    create: Callable[[], Awaitable[uuid.UUID]],
) -> tuple[uuid.UUID, bool]:
    """Idempotency primitive: an `external_links(asana, entity_type, external_id)` row already
    existing means this object was imported before — reuse its id rather than creating a
    duplicate. Returns (entity_id, created)."""
    existing = (
        await session.execute(
            select(ExternalLink).where(
                ExternalLink.provider == "asana",
                ExternalLink.entity_type == entity_type,
                ExternalLink.external_id == external_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing.entity_id, False
    entity_id = await create()
    session.add(
        ExternalLink(
            workspace_id=ctx.workspace_id,
            entity_type=entity_type,
            entity_id=entity_id,
            provider="asana",
            external_id=external_id,
        )
    )
    return entity_id, True


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value[:10])


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def _match_users(
    session: AsyncSession, ctx: Ctx, client: AsanaClientLike, team_gid: str, counters: _Counters
) -> dict[str, uuid.UUID]:
    by_email: dict[str, uuid.UUID] = {}
    for u in await client.team_users(team_gid):
        email = (u.get("email") or "").strip().lower()
        if not email:
            counters.users_unmatched += 1
            continue
        user = (
            await session.execute(
                select(User).where(
                    User.workspace_id == ctx.workspace_id, func.lower(User.email) == email
                )
            )
        ).scalar_one_or_none()
        if user is not None:
            by_email[email] = user.id
            counters.users_matched += 1
        else:
            # Invite-placeholder creation (the spec's other option for an unmatched user) isn't
            # built this slice — unmatched Asana users simply don't map to an assignee/author.
            counters.users_unmatched += 1
    return by_email


async def _import_task(
    session: AsyncSession,
    ctx: Ctx,
    t: dict[str, Any],
    *,
    project_id: uuid.UUID | None,
    section_id: uuid.UUID | None,
    position: str | None,
    parent_id: uuid.UUID | None,
    tag_by_gid: dict[str, uuid.UUID],
    user_by_email: dict[str, uuid.UUID],
    counters: _Counters,
) -> uuid.UUID | None:
    task_type = map_task_type(t.get("resource_subtype"))
    if task_type is None:
        counters.skipped.append(f"task {t.get('gid')}: unsupported resource_subtype")
        return None

    async def create() -> uuid.UUID:
        assignee_email = ((t.get("assignee") or {}).get("email") or "").strip().lower()
        creator_email = ((t.get("created_by") or {}).get("email") or "").strip().lower()
        task = Task(
            workspace_id=ctx.workspace_id,
            number=await _next_number(session, ctx.workspace_id),
            title=(t.get("name") or "Untitled")[:500],
            description_text=html_to_plain(t.get("html_notes") or t.get("notes")),
            type=task_type,
            assignee_id=user_by_email.get(assignee_email),
            start_on=_parse_date(t.get("start_on")),
            due_on=_parse_date(t.get("due_on")),
            due_at=_parse_datetime(t.get("due_at")),
            completed_at=_parse_datetime(t.get("completed_at")) if t.get("completed") else None,
            parent_id=parent_id,
            created_by=user_by_email.get(creator_email),
            created_via="import",
        )
        session.add(task)
        await session.flush()
        return task.id

    task_id, created = await _get_or_create(
        session, ctx, entity_type="task", external_id=t["gid"], create=create
    )
    if created and project_id is not None and section_id is not None:
        session.add(
            TaskProject(
                task_id=task_id, project_id=project_id, section_id=section_id, position=position
            )
        )
        counters.tasks += 1
    elif created:
        counters.subtasks += 1
    if created:
        for tag_gid in t.get("tags") or []:
            gid = tag_gid["gid"] if isinstance(tag_gid, dict) else tag_gid
            tag_id = tag_by_gid.get(gid)
            if tag_id is not None:
                session.add(TaskTag(task_id=task_id, tag_id=tag_id))
    return task_id


async def run_import(
    session: AsyncSession,
    ctx: Ctx,
    client: AsanaClientLike,
    *,
    workspace_gid: str,
    team_gid: str,
    team_name: str,
    project_gids: list[str] | None = None,
) -> ImportJob:
    assert ctx.actor.id is not None
    job = ImportJob(
        workspace_id=ctx.workspace_id, source="asana", status="running", started_by=ctx.actor.id
    )
    session.add(job)
    await session.flush()
    await _run_import_body(
        session,
        ctx,
        client,
        job=job,
        workspace_gid=workspace_gid,
        team_gid=team_gid,
        team_name=team_name,
        project_gids=project_gids,
    )
    return job


async def _run_import_body(
    session: AsyncSession,
    ctx: Ctx,
    client: AsanaClientLike,
    *,
    job: ImportJob,
    workspace_gid: str,
    team_gid: str,
    team_name: str,
    project_gids: list[str] | None,
) -> None:
    counters = _Counters()

    async def create_team() -> uuid.UUID:
        team = Team(workspace_id=ctx.workspace_id, name=team_name, created_by=ctx.actor.id)
        session.add(team)
        await session.flush()
        return team.id

    team_id, team_created = await _get_or_create(
        session, ctx, entity_type="team", external_id=team_gid, create=create_team
    )
    if team_created:
        counters.teams += 1

    user_by_email = await _match_users(session, ctx, client, team_gid, counters)
    for user_id in user_by_email.values():
        existing = await session.get(TeamMember, (team_id, user_id))
        if existing is None:
            session.add(TeamMember(team_id=team_id, user_id=user_id))

    tag_by_gid: dict[str, uuid.UUID] = {}
    for tg in await client.tags(workspace_gid):

        async def create_tag(tg: dict[str, Any] = tg) -> uuid.UUID:
            tag = Tag(workspace_id=ctx.workspace_id, name=tg["name"][:50], color=DEFAULT_TAG_COLOR)
            session.add(tag)
            await session.flush()
            return tag.id

        tag_id, created = await _get_or_create(
            session, ctx, entity_type="tag", external_id=tg["gid"], create=create_tag
        )
        tag_by_gid[tg["gid"]] = tag_id
        if created:
            counters.tags += 1

    asana_projects = await client.projects(team_gid)
    if project_gids:
        wanted = set(project_gids)
        asana_projects = [p for p in asana_projects if p["gid"] in wanted]

    for p in asana_projects:

        async def create_project(p: dict[str, Any] = p) -> uuid.UUID:
            project = Project(
                workspace_id=ctx.workspace_id,
                team_id=team_id,
                name=p["name"][:200],
                privacy=map_privacy(p.get("privacy_setting")),
                archived_at=datetime.now(UTC) if p.get("archived") else None,
                start_on=_parse_date(p.get("start_on")),
                due_on=_parse_date(p.get("due_on")),
                created_by=ctx.actor.id,
                created_via="import",
            )
            session.add(project)
            await session.flush()
            return project.id

        project_id, created = await _get_or_create(
            session, ctx, entity_type="project", external_id=p["gid"], create=create_project
        )
        if created:
            counters.projects += 1

        last_section_pos: str | None = None
        for s in await client.sections(p["gid"]):
            section_pos = key_between(last_section_pos, None)

            async def create_section(
                s: dict[str, Any] = s,
                project_id: uuid.UUID = project_id,
                section_pos: str = section_pos,
            ) -> uuid.UUID:
                section = Section(
                    workspace_id=ctx.workspace_id,
                    project_id=project_id,
                    name=s["name"][:200],
                    position=section_pos,
                )
                session.add(section)
                await session.flush()
                return section.id

            section_id, created = await _get_or_create(
                session, ctx, entity_type="section", external_id=s["gid"], create=create_section
            )
            if created:
                counters.sections += 1
            section_row = await session.get(Section, section_id)
            last_section_pos = section_row.position if section_row else last_section_pos

            last_task_pos: str | None = None
            for t in await client.tasks(s["gid"]):
                pos = key_between(last_task_pos, None)
                last_task_pos = pos
                task_id = await _import_task(
                    session,
                    ctx,
                    t,
                    project_id=project_id,
                    section_id=section_id,
                    position=pos,
                    parent_id=None,
                    tag_by_gid=tag_by_gid,
                    user_by_email=user_by_email,
                    counters=counters,
                )
                if task_id is not None and (t.get("num_subtasks") or 0) > 0:
                    for st in await client.subtasks(t["gid"]):
                        await _import_task(
                            session,
                            ctx,
                            st,
                            project_id=None,
                            section_id=None,
                            position=None,
                            parent_id=task_id,
                            tag_by_gid=tag_by_gid,
                            user_by_email=user_by_email,
                            counters=counters,
                        )

    job.status = "done"
    job.stats = counters.as_dict()
    job.finished_at = datetime.now(UTC)
    await session.flush()
