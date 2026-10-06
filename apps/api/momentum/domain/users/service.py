from __future__ import annotations

import json
import uuid
from typing import Any, Literal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import jsonable_diff, record_activity
from momentum.core.context import Ctx
from momentum.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from momentum.core.events import emit
from momentum.core.ids import new_id
from momentum.core.mutation import Mutation
from momentum.core.permissions import Action, require
from momentum.core.undo import undo_handler, undo_op
from momentum.domain.access import visible_people_clause
from momentum.domain.agents.models import Agent
from momentum.domain.integrations.models import ImportJob
from momentum.domain.projects.models import Project
from momentum.domain.users.models import User, UserIdentity
from momentum.domain.workspace.models import Workspace

AgentFilter = Literal["assigned", "mentioned", "all"]


async def get_me(session: AsyncSession, ctx: Ctx) -> tuple[User, Workspace]:
    user = await session.get(User, ctx.actor.id)
    workspace = await session.get(Workspace, ctx.workspace_id)
    if user is None or workspace is None:
        raise NotFound()
    return user, workspace


async def list_dev_login_users(session: AsyncSession, workspace_id: uuid.UUID) -> list[User]:
    """Users offered on the dev login page (dev modes only)."""
    result = await session.execute(
        select(User)
        .where(
            User.workspace_id == workspace_id, User.status != "disabled", User.is_agent.is_(False)
        )
        .order_by(User.role, User.name)
    )
    return list(result.scalars())


async def list_users(
    session: AsyncSession,
    ctx: Ctx,
    *,
    q: str | None = None,
    limit: int = 50,
    agents: AgentFilter | None = None,
) -> list[User]:
    """Active workspace members for pickers, optionally filtered by name/email prefix.
    ``agents`` (S5.2.1) adds agent accounts: ``assigned``/``mentioned`` the enabled agents that
    act on that trigger (the assignee picker, @mentions), ``all`` every agent (to show the names
    of agents already on a task)."""
    query = select(User).where(
        User.workspace_id == ctx.workspace_id,
        User.status != "disabled",
        visible_people_clause(ctx, User.id),
    )
    if agents is None:
        query = query.where(User.is_agent.is_(False))
    elif agents != "all":
        offered = select(Agent.user_id).where(
            Agent.workspace_id == ctx.workspace_id,
            Agent.enabled.is_(True),
            Agent.triggers.contains([{"type": agents}]),
        )
        query = query.where(User.is_agent.is_(False) | User.id.in_(offered))
    if q:
        like = f"%{q.strip().lower()}%"
        query = query.where(
            (func.lower(User.name).like(like)) | (func.lower(User.email).like(like))
        )
    result = await session.execute(query.order_by(func.lower(User.name)).limit(min(limit, 1000)))
    return list(result.scalars())


async def get_view_prefs(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID
) -> dict[str, Any] | None:
    user = await session.get(User, ctx.actor.id)
    views = (user.prefs or {}).get("views", {}) if user else {}
    value = views.get(str(project_id))
    return value if isinstance(value, dict) else None


async def set_view_prefs(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID, prefs: dict[str, Any]
) -> None:
    """Store one project's view prefs atomically (concurrent saves for other projects are kept)."""
    await session.execute(
        text(
            "UPDATE users SET prefs = jsonb_set(coalesce(prefs, '{}'::jsonb), '{views}', "
            "coalesce(prefs->'views', '{}'::jsonb) "
            "|| jsonb_build_object(cast(:pid as text), cast(:value as jsonb))) WHERE id = :uid"
        ),
        {"pid": str(project_id), "value": json.dumps(prefs), "uid": ctx.actor.id},
    )


async def list_members(session: AsyncSession, ctx: Ctx) -> list[User]:
    """Every workspace member, active/invited/disabled alike — for the admin Members page.

    Unlike `list_users` (pickers: active, non-agent only), this is deliberately unfiltered so an
    admin can see who's invited-but-not-joined or disabled.
    """
    require(ctx, Action.USERS_MANAGE)
    result = await session.execute(
        select(User)
        .where(User.workspace_id == ctx.workspace_id, User.is_agent.is_(False))
        .order_by(User.status, func.lower(User.name))
    )
    return list(result.scalars())


async def invite_user(
    session: AsyncSession, ctx: Ctx, email: str, name: str | None, role: str
) -> User:
    """Create a placeholder member (`status="invited"`) by email, admin-only.

    No email is actually sent (synthetic-data-only environment, no email provider configured) —
    the point is the row: `auth/identity.py`'s `resolve_user` already flips `invited` -> `active`
    the moment this person signs in for the first time and their auth email matches. Idempotent
    on purpose: inviting an email that's already a member just returns that member unchanged,
    rather than erroring, since retrying an invite is a normal thing to do.
    """
    require(ctx, Action.USERS_MANAGE)
    email = email.strip().lower()
    existing = (
        await session.execute(
            select(User).where(User.workspace_id == ctx.workspace_id, User.email == email)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    if role not in ("admin", "member", "guest"):
        raise Conflict("role must be admin, member, or guest")
    user = User(
        id=new_id(),
        workspace_id=ctx.workspace_id,
        email=email,
        name=name or email.split("@")[0],
        role=role,
        status="invited",
        timezone="UTC",
        prefs={},
        is_agent=False,
    )
    session.add(user)
    await session.flush()
    # S7.5.4: an invitation is part of the admin trail (no undo: disable them instead)
    await record_activity(
        session,
        ctx,
        entity_type="user",
        entity_id=user.id,
        verb="user.invited",
        changes={"email": (None, email), "role": (None, role)},
    )
    return user


class OnboardingStatus:
    """Computed, not stored where a real signal already exists (`created_project`,
    `tried_import`) — only `used_command_palette` has no natural database record, so that one
    lives in `prefs.onboarding` (the same JSONB column view/list prefs already use)."""

    def __init__(
        self,
        *,
        created_project: bool,
        tried_import: bool,
        used_command_palette: bool,
        dismissed: bool,
    ) -> None:
        self.created_project = created_project
        self.tried_import = tried_import
        self.used_command_palette = used_command_palette
        self.dismissed = dismissed


async def get_onboarding_status(session: AsyncSession, ctx: Ctx) -> OnboardingStatus:
    user = await session.get(User, ctx.actor.id)
    onboarding = ((user.prefs or {}) if user else {}).get("onboarding", {})
    created_project = (
        await session.execute(
            select(Project.id)
            .where(
                Project.workspace_id == ctx.workspace_id,
                Project.created_by == ctx.actor.id,
                Project.deleted_at.is_(None),
            )
            .limit(1)
        )
    ).scalar_one_or_none() is not None
    tried_import = (
        await session.execute(
            select(ImportJob.id)
            .where(ImportJob.workspace_id == ctx.workspace_id, ImportJob.started_by == ctx.actor.id)
            .limit(1)
        )
    ).scalar_one_or_none() is not None
    return OnboardingStatus(
        created_project=created_project,
        tried_import=tried_import,
        used_command_palette=bool(onboarding.get("used_command_palette", False)),
        dismissed=bool(onboarding.get("dismissed", False)),
    )


async def mark_onboarding(
    session: AsyncSession,
    ctx: Ctx,
    *,
    used_command_palette: bool | None = None,
    dismissed: bool | None = None,
) -> None:
    """Set one or more of the client-only onboarding flags (see `OnboardingStatus`)."""
    patch: dict[str, Any] = {}
    if used_command_palette is not None:
        patch["used_command_palette"] = used_command_palette
    if dismissed is not None:
        patch["dismissed"] = dismissed
    if not patch:
        return
    await session.execute(
        text(
            "UPDATE users SET prefs = jsonb_set(coalesce(prefs, '{}'::jsonb), '{onboarding}', "
            "coalesce(prefs->'onboarding', '{}'::jsonb) || cast(:patch as jsonb)) WHERE id = :uid"
        ),
        {"patch": json.dumps(patch), "uid": ctx.actor.id},
    )


# ---------- S7.5.4: member administration ----------

ROLES = ("admin", "member", "guest")


async def _member(session: AsyncSession, ctx: Ctx, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None or user.workspace_id != ctx.workspace_id or user.is_agent:
        raise NotFound("Member not found")
    return user


async def _other_active_admins(session: AsyncSession, ctx: Ctx, user_id: uuid.UUID) -> int:
    return int(
        (
            await session.execute(
                select(func.count()).where(
                    User.workspace_id == ctx.workspace_id,
                    User.role == "admin",
                    User.status == "active",
                    User.is_agent.is_(False),
                    User.id != user_id,
                )
            )
        ).scalar_one()
    )


async def update_member(
    session: AsyncSession,
    ctx: Ctx,
    user_id: uuid.UUID,
    *,
    role: str | None = None,
    status: str | None = None,
    record_undo: bool = True,
) -> Mutation[User]:
    """An admin changes someone's role, or disables / re-enables them. A disabled person can't
    sign in or use their API tokens, and any open tab is disconnected (realtime re-checks access
    on ``user.updated``); their work stays where it is (``transfer_work`` hands it on).
    Re-enabling someone who never signed in makes them invited again."""
    require(ctx, Action.USERS_MANAGE)
    user = await _member(session, ctx, user_id)
    if role is not None and role not in ROLES:
        raise ValidationFailed("role must be admin, member or guest")
    if status is not None and status not in ("active", "disabled"):
        raise ValidationFailed("status must be active or disabled")
    new_status = status
    if status == "active" and user.status == "disabled":
        signed_in = (
            await session.execute(
                select(UserIdentity.user_id).where(UserIdentity.user_id == user.id).limit(1)
            )
        ).first()
        new_status = "active" if signed_in else "invited"
    elif status == "active":
        new_status = user.status  # already active or invited: nothing to do
    losing_admin = user.role == "admin" and (
        (role is not None and role != "admin") or new_status == "disabled"
    )
    if losing_admin and user.id == ctx.actor.id:
        raise Conflict("You can't remove your own admin access or disable yourself")
    if losing_admin and await _other_active_admins(session, ctx, user.id) == 0:
        raise Conflict("Momentum needs at least one active admin")
    changes: dict[str, tuple[Any, Any]] = {}
    if role is not None and role != user.role:
        changes["role"] = (user.role, role)
        user.role = role
    if new_status is not None and new_status != user.status:
        changes["status"] = (user.status, new_status)
        user.status = new_status
    if not changes:
        return Mutation(user)
    act = await record_activity(
        session,
        ctx,
        entity_type="user",
        entity_id=user.id,
        verb="user.updated",
        changes=changes,
        undo=undo_op(
            "users.update",
            user_id=user.id,
            role=changes.get("role", (None,))[0],
            status=changes.get("status", (None,))[0],
        )
        if record_undo
        else None,
    )
    await emit(
        session,
        ctx,
        type="user.updated",
        entity_type="user",
        entity_id=user.id,
        data={"changes": jsonable_diff(changes)},
        channels=[f"user:{user.id}"],
        activity_id=act.id,
    )
    return Mutation(user, act.id)


@undo_handler("users.update")
async def _undo_update(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    status = args.get("status")
    await update_member(
        session,
        ctx,
        uuid.UUID(str(args["user_id"])),
        role=args.get("role"),
        status="active" if status in ("active", "invited") else status,
        record_undo=False,
    )


class TransferResult:
    def __init__(self, tasks: int, projects: int, not_visible: int, batch_id: uuid.UUID) -> None:
        self.tasks = tasks
        self.projects = projects
        self.not_visible = not_visible
        self.batch_id = batch_id


async def transfer_work(
    session: AsyncSession, ctx: Ctx, from_id: uuid.UUID, to_id: uuid.UUID
) -> TransferResult:
    """Hand someone's open tasks and the projects they own to another member (a departure, a
    role change). Goes through the task and project services (notifications, activity, one
    batch). Tasks in projects the admin can't see (private ones) stay put and are counted:
    privacy isn't overridden; their project's admins can reassign them."""
    from momentum.domain.projects.schemas import ProjectPatchIn
    from momentum.domain.projects.service import update_project
    from momentum.domain.tasks.models import Task
    from momentum.domain.tasks.service import update_task

    require(ctx, Action.USERS_MANAGE)
    source = await _member(session, ctx, from_id)
    target = await _member(session, ctx, to_id)
    if source.id == target.id:
        raise ValidationFailed("Choose someone else to take the work")
    if target.status == "disabled":
        raise ValidationFailed("That person is disabled")
    batch = new_id()
    task_ids = (
        (
            await session.execute(
                select(Task.id).where(
                    Task.workspace_id == ctx.workspace_id,
                    Task.assignee_id == source.id,
                    Task.completed_at.is_(None),
                    Task.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    moved = hidden = 0
    for tid in task_ids:
        try:
            await update_task(session, ctx, tid, {"assignee_id": target.id}, batch_id=batch)
            moved += 1
        except (NotFound, Forbidden):
            hidden += 1
    project_ids = (
        (
            await session.execute(
                select(Project.id).where(
                    Project.workspace_id == ctx.workspace_id,
                    Project.owner_id == source.id,
                    Project.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    owned = 0
    for pid in project_ids:
        try:
            await update_project(session, ctx, pid, ProjectPatchIn(owner_id=target.id))
            owned += 1
        except (NotFound, Forbidden):
            hidden += 1
    return TransferResult(moved, owned, hidden, batch)
