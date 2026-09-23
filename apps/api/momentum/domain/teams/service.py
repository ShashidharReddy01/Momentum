"""Teams: the unit of membership that owns projects (phase-1.md S1.1.1)."""

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
from momentum.core.permissions import Action, require
from momentum.core.undo import UndoConflict, undo_handler, undo_op
from momentum.domain.access import get_visible_team, require_team_manager, team_role
from momentum.domain.teams.models import Team, TeamMember
from momentum.domain.teams.schemas import TeamCreateIn, TeamPatchIn
from momentum.domain.users.models import User

EDITABLE = ("name", "description", "color")


def _channels(team_id: uuid.UUID) -> list[str]:
    return [f"team:{team_id}"]


# ---------- reads ----------


async def list_teams(session: AsyncSession, ctx: Ctx) -> list[tuple[Team, str | None, int]]:
    """Teams the caller belongs to (admins: all teams), with the caller's role and member count."""
    counts = (
        select(TeamMember.team_id, func.count().label("n")).group_by(TeamMember.team_id).subquery()
    )
    mine = (
        select(TeamMember.team_id, TeamMember.role)
        .where(TeamMember.user_id == ctx.actor.id)
        .subquery()
    )
    query = (
        select(Team, mine.c.role, func.coalesce(counts.c.n, 0))
        .outerjoin(mine, mine.c.team_id == Team.id)
        .outerjoin(counts, counts.c.team_id == Team.id)
        .where(Team.workspace_id == ctx.workspace_id, Team.deleted_at.is_(None))
        .order_by(func.lower(Team.name))
    )
    if not ctx.actor.is_admin:
        query = query.where(mine.c.role.is_not(None))
    return [(t, role, int(n)) for t, role, n in (await session.execute(query)).all()]


async def get_team(session: AsyncSession, ctx: Ctx, team_id: uuid.UUID) -> Team:
    return await get_visible_team(session, ctx, team_id)


async def team_summary(session: AsyncSession, ctx: Ctx, team: Team) -> tuple[str | None, int]:
    n = (
        await session.execute(
            select(func.count()).select_from(TeamMember).where(TeamMember.team_id == team.id)
        )
    ).scalar_one()
    return await team_role(session, ctx, team.id), int(n)


async def list_members(session: AsyncSession, team_id: uuid.UUID) -> list[tuple[User, str]]:
    rows = await session.execute(
        select(User, TeamMember.role)
        .join(TeamMember, TeamMember.user_id == User.id)
        .where(TeamMember.team_id == team_id)
        .order_by(TeamMember.role, func.lower(User.name))
    )
    return [(u, r) for u, r in rows.all()]


# ---------- writes ----------


async def create_team(session: AsyncSession, ctx: Ctx, data: TeamCreateIn) -> Mutation[Team]:
    require(ctx, Action.TEAM_CREATE)
    team = Team(
        workspace_id=ctx.workspace_id,
        name=data.name.strip(),
        description=data.description,
        color=data.color,
        created_by=ctx.actor.id,
    )
    session.add(team)
    await session.flush()
    session.add(TeamMember(team_id=team.id, user_id=ctx.actor.id, role="lead"))
    act = await record_activity(
        session,
        ctx,
        entity_type="team",
        entity_id=team.id,
        verb="team.created",
        changes={"name": (None, team.name)},
        undo=undo_op("teams.delete", team_id=team.id),
    )
    await emit(
        session,
        ctx,
        type="team.created",
        entity_type="team",
        entity_id=team.id,
        channels=_channels(team.id),
        activity_id=act.id,
    )
    await session.flush()
    return Mutation(team, act.id, version=team.version)


async def update_team(
    session: AsyncSession,
    ctx: Ctx,
    team_id: uuid.UUID,
    patch: TeamPatchIn,
    *,
    record_undo: bool = True,
) -> Mutation[Team]:
    team = await get_visible_team(session, ctx, team_id)
    await require_team_manager(session, ctx, team)
    fields = patch.model_fields_set & set(EDITABLE)
    if "name" in fields and not (patch.name or "").strip():
        raise ValidationFailed("Team name can't be empty")
    changes: Diff = {}
    for f in fields:
        new = getattr(patch, f)
        if f == "name" and isinstance(new, str):
            new = new.strip()
        old = getattr(team, f)
        if old != new:
            changes[f] = (old, new)
            setattr(team, f, new)
    if not changes:
        return Mutation(team, None, version=team.version)
    team.version += 1
    act = await record_activity(
        session,
        ctx,
        entity_type="team",
        entity_id=team.id,
        verb="team.updated",
        changes=changes,
        undo=undo_op(
            "teams.update",
            team_id=team.id,
            version=team.version,
            patch={k: old for k, (old, _) in changes.items()},
        )
        if record_undo
        else None,
    )
    await emit(
        session,
        ctx,
        type="team.updated",
        entity_type="team",
        entity_id=team.id,
        data={"changes": {k: [o, n] for k, (o, n) in changes.items()}, "version": team.version},
        channels=_channels(team.id),
        activity_id=act.id,
    )
    return Mutation(team, act.id, version=team.version)


async def delete_team(session: AsyncSession, ctx: Ctx, team_id: uuid.UUID) -> Mutation[Team]:
    team = await get_visible_team(session, ctx, team_id)
    await require_team_manager(session, ctx, team)
    team.deleted_at = datetime.now(UTC)
    team.version += 1
    act = await record_activity(
        session,
        ctx,
        entity_type="team",
        entity_id=team.id,
        verb="team.deleted",
        undo=undo_op("teams.restore", team_id=team.id),
    )
    await emit(
        session,
        ctx,
        type="team.deleted",
        entity_type="team",
        entity_id=team.id,
        channels=_channels(team.id),
        activity_id=act.id,
    )
    return Mutation(team, act.id, version=team.version)


async def _leads(session: AsyncSession, team_id: uuid.UUID) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(TeamMember)
                .where(TeamMember.team_id == team_id, TeamMember.role == "lead")
            )
        ).scalar_one()
    )


async def add_member(
    session: AsyncSession, ctx: Ctx, team_id: uuid.UUID, user_id: uuid.UUID, role: str = "member"
) -> Mutation[TeamMember]:
    team = await get_visible_team(session, ctx, team_id)
    await require_team_manager(session, ctx, team)
    user = await session.get(User, user_id)
    if user is None or user.workspace_id != ctx.workspace_id or user.status == "disabled":
        raise NotFound("User not found")
    if await session.get(TeamMember, (team_id, user_id)) is not None:
        raise Conflict("Already a member of this team", code="duplicate")
    member = TeamMember(team_id=team_id, user_id=user_id, role=role)
    session.add(member)
    act = await record_activity(
        session,
        ctx,
        entity_type="team",
        entity_id=team_id,
        verb="team.member_added",
        changes={"member": (None, str(user_id))},
        undo=undo_op("teams.remove_member", team_id=team_id, user_id=user_id),
    )
    await emit(
        session,
        ctx,
        type="team.member_added",
        entity_type="team",
        entity_id=team_id,
        data={"user_id": str(user_id), "role": role},
        channels=[*_channels(team_id), f"user:{user_id}"],
        activity_id=act.id,
    )
    await session.flush()
    return Mutation(member, act.id)


async def set_member_role(
    session: AsyncSession, ctx: Ctx, team_id: uuid.UUID, user_id: uuid.UUID, role: str
) -> Mutation[TeamMember]:
    team = await get_visible_team(session, ctx, team_id)
    await require_team_manager(session, ctx, team)
    member = await session.get(TeamMember, (team_id, user_id))
    if member is None:
        raise NotFound("Not a member of this team")
    if member.role == role:
        return Mutation(member)
    if member.role == "lead" and role != "lead" and await _leads(session, team_id) <= 1:
        raise Conflict("A team needs at least one lead", code="last_lead")
    old = member.role
    member.role = role
    act = await record_activity(
        session,
        ctx,
        entity_type="team",
        entity_id=team_id,
        verb="team.member_role_changed",
        changes={"role": (old, role)},
        undo=undo_op("teams.set_role", team_id=team_id, user_id=user_id, role=old),
    )
    await emit(
        session,
        ctx,
        type="team.member_updated",
        entity_type="team",
        entity_id=team_id,
        data={"user_id": str(user_id), "role": role},
        channels=_channels(team_id),
        activity_id=act.id,
    )
    return Mutation(member, act.id)


async def remove_member(
    session: AsyncSession, ctx: Ctx, team_id: uuid.UUID, user_id: uuid.UUID
) -> Mutation[TeamMember]:
    team = await get_visible_team(session, ctx, team_id)
    if user_id != ctx.actor.id:  # leaving yourself is always allowed (subject to the lead rule)
        await require_team_manager(session, ctx, team)
    member = await session.get(TeamMember, (team_id, user_id))
    if member is None:
        raise NotFound("Not a member of this team")
    if member.role == "lead" and await _leads(session, team_id) <= 1:
        raise Conflict(
            "A team needs at least one lead. Make someone else lead first.", code="last_lead"
        )
    role = member.role
    await session.delete(member)
    act = await record_activity(
        session,
        ctx,
        entity_type="team",
        entity_id=team_id,
        verb="team.member_removed",
        changes={"member": (str(user_id), None)},
        undo=undo_op("teams.add_member", team_id=team_id, user_id=user_id, role=role),
    )
    await emit(
        session,
        ctx,
        type="team.member_removed",
        entity_type="team",
        entity_id=team_id,
        data={"user_id": str(user_id)},
        channels=[*_channels(team_id), f"user:{user_id}"],
        activity_id=act.id,
    )
    await session.flush()
    return Mutation(member, act.id)


# ---------- undo handlers ----------


def _uuid(args: dict[str, Any], key: str) -> uuid.UUID:
    return uuid.UUID(str(args[key]))


@undo_handler("teams.update")
async def _undo_update(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    team = await get_visible_team(session, ctx, _uuid(args, "team_id"))
    if team.version != int(args["version"]):
        raise UndoConflict("This team changed after your edit")
    await update_team(session, ctx, team.id, TeamPatchIn(**args["patch"]), record_undo=False)


@undo_handler("teams.restore")
async def _undo_delete(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    team = await session.get(Team, _uuid(args, "team_id"))
    if team is None or team.workspace_id != ctx.workspace_id:
        raise NotFound()
    team.deleted_at = None
    team.version += 1
    await record_activity(session, ctx, entity_type="team", entity_id=team.id, verb="team.restored")
    await emit(
        session,
        ctx,
        type="team.restored",
        entity_type="team",
        entity_id=team.id,
        channels=_channels(team.id),
    )


@undo_handler("teams.delete")
async def _undo_create(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    team = await get_visible_team(session, ctx, _uuid(args, "team_id"))
    team.deleted_at = datetime.now(UTC)
    team.version += 1
    await record_activity(session, ctx, entity_type="team", entity_id=team.id, verb="team.deleted")
    await emit(
        session,
        ctx,
        type="team.deleted",
        entity_type="team",
        entity_id=team.id,
        channels=_channels(team.id),
    )


@undo_handler("teams.add_member")
async def _undo_remove(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    team_id, user_id = _uuid(args, "team_id"), _uuid(args, "user_id")
    if await session.get(TeamMember, (team_id, user_id)) is None:
        session.add(TeamMember(team_id=team_id, user_id=user_id, role=str(args["role"])))
        await record_activity(
            session,
            ctx,
            entity_type="team",
            entity_id=team_id,
            verb="team.member_added",
            changes={"member": (None, str(user_id))},
        )


@undo_handler("teams.remove_member")
async def _undo_add(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    team_id, user_id = _uuid(args, "team_id"), _uuid(args, "user_id")
    member = await session.get(TeamMember, (team_id, user_id))
    if member is not None:
        if member.role == "lead" and await _leads(session, team_id) <= 1:
            raise UndoConflict("A team needs at least one lead")
        await session.delete(member)
        await record_activity(
            session,
            ctx,
            entity_type="team",
            entity_id=team_id,
            verb="team.member_removed",
            changes={"member": (str(user_id), None)},
        )


@undo_handler("teams.set_role")
async def _undo_role(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    member = await session.get(TeamMember, (_uuid(args, "team_id"), _uuid(args, "user_id")))
    if member is None:
        raise UndoConflict("That person is no longer in the team")
    member.role = str(args["role"])
