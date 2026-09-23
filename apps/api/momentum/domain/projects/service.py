"""Projects: containers of sections and tasks, owned by a team (phase-1.md S1.1.2)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import Diff, record_activity
from momentum.core.context import Ctx
from momentum.core.errors import Conflict, NotFound, ValidationFailed
from momentum.core.events import emit
from momentum.core.mutation import Mutation
from momentum.core.ordering import key_between
from momentum.core.undo import UndoConflict, undo_handler, undo_op
from momentum.domain.access import (
    get_visible_project,
    get_visible_team,
    require_project_role,
    visible_projects_clause,
)
from momentum.domain.projects.models import Favorite, Project, ProjectMember
from momentum.domain.projects.schemas import ProjectCreateIn, ProjectPatchIn
from momentum.domain.sections.models import Section
from momentum.domain.teams.models import Team
from momentum.domain.users.models import User

DEFAULT_SECTION = "To do"
DETAIL_FIELDS = ("name", "color", "default_view")  # editors
ADMIN_FIELDS = ("privacy",)  # project admins


def _channels(project_id: uuid.UUID) -> list[str]:
    return [f"project:{project_id}"]


# ---------- reads ----------


async def list_projects(
    session: AsyncSession,
    ctx: Ctx,
    *,
    team_id: uuid.UUID | None = None,
    archived: bool = False,
) -> list[Project]:
    query = select(Project).where(visible_projects_clause(ctx))
    if team_id is not None:
        query = query.where(Project.team_id == team_id)
    query = query.where(
        Project.archived_at.is_not(None) if archived else Project.archived_at.is_(None)
    )
    return list((await session.execute(query.order_by(func.lower(Project.name)))).scalars())


async def favorite_ids(session: AsyncSession, ctx: Ctx) -> set[uuid.UUID]:
    rows = await session.execute(
        select(Favorite.entity_id).where(
            Favorite.user_id == ctx.actor.id, Favorite.entity_type == "project"
        )
    )
    return set(rows.scalars())


async def list_favorites(session: AsyncSession, ctx: Ctx) -> list[Project]:
    query = (
        select(Project)
        .join(Favorite, (Favorite.entity_id == Project.id) & (Favorite.entity_type == "project"))
        .where(
            Favorite.user_id == ctx.actor.id,
            visible_projects_clause(ctx),
            Project.archived_at.is_(None),
        )
        .order_by(Favorite.position)
    )
    return list((await session.execute(query)).scalars())


async def get_project(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID
) -> tuple[Project, str]:
    return await get_visible_project(session, ctx, project_id)


async def project_members(session: AsyncSession, project_id: uuid.UUID) -> list[tuple[User, str]]:
    rows = await session.execute(
        select(User, ProjectMember.role)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == project_id)
        .order_by(func.lower(User.name))
    )
    return [(u, r) for u, r in rows.all()]


async def project_sections(session: AsyncSession, project_id: uuid.UUID) -> list[Section]:
    rows = await session.execute(
        select(Section)
        .where(Section.project_id == project_id, Section.deleted_at.is_(None))
        .order_by(Section.position)
    )
    return list(rows.scalars())


# ---------- writes ----------


async def create_project(
    session: AsyncSession, ctx: Ctx, data: ProjectCreateIn
) -> Mutation[Project]:
    await get_visible_team(session, ctx, data.team_id)  # must be a member of the team (or admin)
    project = Project(
        workspace_id=ctx.workspace_id,
        team_id=data.team_id,
        name=data.name.strip(),
        privacy=data.privacy,
        color=data.color,
        owner_id=ctx.actor.id,
        created_by=ctx.actor.id,
        created_via=ctx.via,
    )
    session.add(project)
    await session.flush()
    session.add(ProjectMember(project_id=project.id, user_id=ctx.actor.id, role="admin"))
    session.add(
        Section(
            workspace_id=ctx.workspace_id,
            project_id=project.id,
            name=DEFAULT_SECTION,
            position=key_between(None, None),
        )
    )
    act = await record_activity(
        session,
        ctx,
        entity_type="project",
        entity_id=project.id,
        verb="project.created",
        changes={"name": (None, project.name)},
        undo=undo_op("projects.delete", project_id=project.id),
    )
    await emit(
        session,
        ctx,
        type="project.created",
        entity_type="project",
        entity_id=project.id,
        data={"team_id": str(project.team_id)},
        channels=[*_channels(project.id), f"team:{project.team_id}"],
        activity_id=act.id,
    )
    await session.flush()
    return Mutation(project, act.id, version=project.version)


async def update_project(
    session: AsyncSession,
    ctx: Ctx,
    project_id: uuid.UUID,
    patch: ProjectPatchIn,
    *,
    record_undo: bool = True,
) -> Mutation[Project]:
    project, role = await get_visible_project(session, ctx, project_id)
    fields = patch.model_fields_set
    if fields & set(ADMIN_FIELDS):
        require_project_role(role, "admin", "change privacy")
    if fields & set(DETAIL_FIELDS):
        require_project_role(role, "editor", "edit this project")
    if "name" in fields and not (patch.name or "").strip():
        raise ValidationFailed("Project name can't be empty")
    for f in ("privacy", "default_view"):
        if f in fields and getattr(patch, f) is None:
            raise ValidationFailed(f"{f} can't be empty")
    changes: Diff = {}
    for f in fields & {*DETAIL_FIELDS, *ADMIN_FIELDS}:
        new = getattr(patch, f)
        if f == "name" and isinstance(new, str):
            new = new.strip()
        old = getattr(project, f)
        if old != new:
            changes[f] = (old, new)
            setattr(project, f, new)
    if not changes:
        return Mutation(project, version=project.version)
    project.version += 1
    act = await record_activity(
        session,
        ctx,
        entity_type="project",
        entity_id=project.id,
        verb="project.updated",
        changes=changes,
        undo=undo_op(
            "projects.update",
            project_id=project.id,
            version=project.version,
            patch={k: o for k, (o, _) in changes.items()},
        )
        if record_undo
        else None,
    )
    await emit(
        session,
        ctx,
        type="project.updated",
        entity_type="project",
        entity_id=project.id,
        data={"changes": {k: [o, n] for k, (o, n) in changes.items()}, "version": project.version},
        channels=_channels(project.id),
        activity_id=act.id,
    )
    return Mutation(project, act.id, version=project.version)


async def set_archived(
    session: AsyncSession,
    ctx: Ctx,
    project_id: uuid.UUID,
    archived: bool,
    *,
    record_undo: bool = True,
) -> Mutation[Project]:
    project, role = await get_visible_project(session, ctx, project_id)
    require_project_role(role, "admin", "archive this project")
    if (project.archived_at is not None) == archived:
        return Mutation(project, version=project.version)
    old = project.archived_at
    project.archived_at = datetime.now(UTC) if archived else None
    project.version += 1
    verb = "project.archived" if archived else "project.unarchived"
    act = await record_activity(
        session,
        ctx,
        entity_type="project",
        entity_id=project.id,
        verb=verb,
        changes={"archived_at": (old, project.archived_at)},
        undo=undo_op("projects.set_archived", project_id=project.id, archived=not archived)
        if record_undo
        else None,
    )
    await emit(
        session,
        ctx,
        type=verb,
        entity_type="project",
        entity_id=project.id,
        channels=[*_channels(project.id), f"team:{project.team_id}"],
        activity_id=act.id,
    )
    return Mutation(project, act.id, version=project.version)


async def delete_project(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID
) -> Mutation[Project]:
    project, role = await get_visible_project(session, ctx, project_id)
    require_project_role(role, "admin", "delete this project")
    project.deleted_at = datetime.now(UTC)
    project.version += 1
    act = await record_activity(
        session,
        ctx,
        entity_type="project",
        entity_id=project.id,
        verb="project.deleted",
        undo=undo_op("projects.restore", project_id=project.id),
    )
    await emit(
        session,
        ctx,
        type="project.deleted",
        entity_type="project",
        entity_id=project.id,
        channels=[*_channels(project.id), f"team:{project.team_id}"],
        activity_id=act.id,
    )
    return Mutation(project, act.id, version=project.version)


# ---------- members ----------


async def _explicit_admins(session: AsyncSession, project_id: uuid.UUID) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(ProjectMember)
                .where(ProjectMember.project_id == project_id, ProjectMember.role == "admin")
            )
        ).scalar_one()
    )


async def add_member(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID, user_id: uuid.UUID, role: str
) -> Mutation[ProjectMember]:
    project, my_role = await get_visible_project(session, ctx, project_id)
    require_project_role(my_role, "admin", "share this project")
    user = await session.get(User, user_id)
    if user is None or user.workspace_id != ctx.workspace_id or user.status == "disabled":
        raise NotFound("User not found")
    if await session.get(ProjectMember, (project_id, user_id)) is not None:
        raise Conflict("Already a member of this project", code="duplicate")
    member = ProjectMember(project_id=project_id, user_id=user_id, role=role)
    session.add(member)
    act = await record_activity(
        session,
        ctx,
        entity_type="project",
        entity_id=project_id,
        verb="project.member_added",
        changes={"member": (None, f"{user_id}:{role}")},
        undo=undo_op("projects.remove_member", project_id=project_id, user_id=user_id),
    )
    await emit(
        session,
        ctx,
        type="project.member_added",
        entity_type="project",
        entity_id=project_id,
        data={"user_id": str(user_id), "role": role},
        channels=[*_channels(project_id), f"user:{user_id}"],
        activity_id=act.id,
    )
    await session.flush()
    return Mutation(member, act.id, version=project.version)


async def set_member_role(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID, user_id: uuid.UUID, role: str
) -> Mutation[ProjectMember]:
    _, my_role = await get_visible_project(session, ctx, project_id)
    require_project_role(my_role, "admin", "change roles")
    member = await session.get(ProjectMember, (project_id, user_id))
    if member is None:
        raise NotFound("Not a member of this project")
    if member.role == role:
        return Mutation(member)
    if member.role == "admin" and await _explicit_admins(session, project_id) <= 1:
        raise Conflict("A project needs at least one admin", code="last_admin")
    old = member.role
    member.role = role
    act = await record_activity(
        session,
        ctx,
        entity_type="project",
        entity_id=project_id,
        verb="project.member_role_changed",
        changes={"role": (old, role)},
        undo=undo_op("projects.set_role", project_id=project_id, user_id=user_id, role=old),
    )
    await emit(
        session,
        ctx,
        type="project.member_updated",
        entity_type="project",
        entity_id=project_id,
        data={"user_id": str(user_id), "role": role},
        channels=[*_channels(project_id), f"user:{user_id}"],
        activity_id=act.id,
    )
    return Mutation(member, act.id)


async def remove_member(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID, user_id: uuid.UUID
) -> Mutation[ProjectMember]:
    _, my_role = await get_visible_project(session, ctx, project_id)
    if user_id != ctx.actor.id:
        require_project_role(my_role, "admin", "remove members")
    member = await session.get(ProjectMember, (project_id, user_id))
    if member is None:
        raise NotFound("Not a member of this project")
    if member.role == "admin" and await _explicit_admins(session, project_id) <= 1:
        raise Conflict(
            "A project needs at least one admin. Make someone else admin first.", code="last_admin"
        )
    role = member.role
    await session.delete(member)
    act = await record_activity(
        session,
        ctx,
        entity_type="project",
        entity_id=project_id,
        verb="project.member_removed",
        changes={"member": (f"{user_id}:{role}", None)},
        undo=undo_op("projects.add_member", project_id=project_id, user_id=user_id, role=role),
    )
    await emit(
        session,
        ctx,
        type="project.member_removed",
        entity_type="project",
        entity_id=project_id,
        data={"user_id": str(user_id)},
        channels=[*_channels(project_id), f"user:{user_id}"],
        activity_id=act.id,
    )
    await session.flush()
    return Mutation(member, act.id)


# ---------- favorites ----------


async def set_favorite(
    session: AsyncSession,
    ctx: Ctx,
    project_id: uuid.UUID,
    *,
    after_id: uuid.UUID | None = None,
    before_id: uuid.UUID | None = None,
) -> Favorite:
    """Star a project, or move an existing star between two other starred projects."""
    await get_visible_project(session, ctx, project_id)
    assert ctx.actor.id is not None

    async def pos(pid: uuid.UUID | None) -> str | None:
        if pid is None:
            return None
        fav = await session.get(Favorite, (ctx.actor.id, "project", pid))
        if fav is None:
            raise NotFound("Neighbor is not a favorite")
        return fav.position

    a, b = await pos(after_id), await pos(before_id)
    if a is None and b is None and after_id is None and before_id is None:
        last = (
            await session.execute(
                select(func.max(Favorite.position)).where(
                    Favorite.user_id == ctx.actor.id, Favorite.entity_type == "project"
                )
            )
        ).scalar_one_or_none()
        a = last
    fav = await session.get(Favorite, (ctx.actor.id, "project", project_id))
    position = key_between(a, b)
    if fav is None:
        fav = Favorite(
            user_id=ctx.actor.id, entity_type="project", entity_id=project_id, position=position
        )
        session.add(fav)
    else:
        fav.position = position
    await session.flush()
    return fav


async def unset_favorite(session: AsyncSession, ctx: Ctx, project_id: uuid.UUID) -> None:
    fav = await session.get(Favorite, (ctx.actor.id, "project", project_id))
    if fav is not None:
        await session.delete(fav)
        await session.flush()


# ---------- undo handlers ----------


def _pid(args: dict[str, Any]) -> uuid.UUID:
    return uuid.UUID(str(args["project_id"]))


@undo_handler("projects.update")
async def _undo_update(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    project, _ = await get_visible_project(session, ctx, _pid(args))
    if project.version != int(args["version"]):
        raise UndoConflict("This project changed after your edit")
    await update_project(
        session, ctx, project.id, ProjectPatchIn(**args["patch"]), record_undo=False
    )


@undo_handler("projects.set_archived")
async def _undo_archive(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    await set_archived(session, ctx, _pid(args), bool(args["archived"]), record_undo=False)


@undo_handler("projects.restore")
async def _undo_delete(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    project, _ = await get_visible_project(session, ctx, _pid(args), include_deleted=True)
    if project.deleted_at is None:
        raise UndoConflict("Project is not deleted")
    project.deleted_at = None
    project.version += 1
    await record_activity(
        session, ctx, entity_type="project", entity_id=project.id, verb="project.restored"
    )
    await emit(
        session,
        ctx,
        type="project.restored",
        entity_type="project",
        entity_id=project.id,
        channels=[*_channels(project.id), f"team:{project.team_id}"],
    )


@undo_handler("projects.delete")
async def _undo_create(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    project, role = await get_visible_project(session, ctx, _pid(args))
    require_project_role(role, "admin", "delete this project")
    project.deleted_at = datetime.now(UTC)
    project.version += 1
    await record_activity(
        session, ctx, entity_type="project", entity_id=project.id, verb="project.deleted"
    )
    await emit(
        session,
        ctx,
        type="project.deleted",
        entity_type="project",
        entity_id=project.id,
        channels=[*_channels(project.id), f"team:{project.team_id}"],
    )


@undo_handler("projects.remove_member")
async def _undo_add_member(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    member = await session.get(ProjectMember, (_pid(args), uuid.UUID(str(args["user_id"]))))
    if member is not None:
        if member.role == "admin" and await _explicit_admins(session, member.project_id) <= 1:
            raise UndoConflict("A project needs at least one admin")
        await session.delete(member)


@undo_handler("projects.add_member")
async def _undo_remove_member(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    key = (_pid(args), uuid.UUID(str(args["user_id"])))
    if await session.get(ProjectMember, key) is None:
        session.add(ProjectMember(project_id=key[0], user_id=key[1], role=str(args["role"])))


@undo_handler("projects.set_role")
async def _undo_set_role(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    member = await session.get(ProjectMember, (_pid(args), uuid.UUID(str(args["user_id"]))))
    if member is None:
        raise UndoConflict("That person is no longer in the project")
    member.role = str(args["role"])


async def team_name(session: AsyncSession, team_id: uuid.UUID) -> str:
    team = await session.get(Team, team_id)
    if team is None:
        raise Conflict("Team missing")
    return team.name
