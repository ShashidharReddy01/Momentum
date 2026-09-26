from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.core.errors import Conflict, NotFound
from momentum.core.ids import new_id
from momentum.core.permissions import Action, require
from momentum.domain.integrations.models import ImportJob
from momentum.domain.projects.models import Project
from momentum.domain.users.models import User
from momentum.domain.workspace.models import Workspace


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
    include_agents: bool = False,
) -> list[User]:
    """Active workspace members for pickers, optionally filtered by name/email prefix."""
    query = select(User).where(User.workspace_id == ctx.workspace_id, User.status != "disabled")
    if not include_agents:
        query = query.where(User.is_agent.is_(False))
    if q:
        like = f"%{q.strip().lower()}%"
        query = query.where(
            (func.lower(User.name).like(like)) | (func.lower(User.email).like(like))
        )
    result = await session.execute(query.order_by(func.lower(User.name)).limit(min(limit, 200)))
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
