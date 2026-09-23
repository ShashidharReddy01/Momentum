"""Resolve an authenticated Principal to a Momentum user (auth-and-permissions.md §3).

Users are keyed by internal id + email. Provider identities are links, so moving to another
tenant or auth provider re-links by email instead of orphaning data.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.auth.base import Principal
from momentum.core.errors import AccountDisabled, NotInvited
from momentum.core.settings import Settings
from momentum.domain.users.models import User, UserIdentity
from momentum.domain.workspace.models import Workspace
from momentum.domain.workspace.service import ensure_default_workspace


def _email_allowed(settings: Settings, principal: Principal) -> bool:
    if settings.allowed_tenants and (principal.tenant_id or "") not in settings.allowed_tenants:
        return False
    if settings.allowed_domains:
        if not principal.email:
            return False
        domain = principal.email.rsplit("@", 1)[-1].lower()
        if domain not in settings.allowed_domains:
            return False
    return True


async def resolve_user(
    session: AsyncSession, settings: Settings, principal: Principal
) -> tuple[User, Workspace]:
    now = datetime.now(UTC)
    tenant = principal.tenant_id or ""
    workspace = await ensure_default_workspace(session, settings)

    identity = (
        await session.execute(
            select(UserIdentity).where(
                UserIdentity.provider == principal.provider,
                UserIdentity.tenant_id == tenant,
                UserIdentity.subject == principal.subject,
            )
        )
    ).scalar_one_or_none()

    user: User | None = None
    if identity is not None:
        user = await session.get(User, identity.user_id)

    if user is None and principal.email and settings.identity_link_by_email:
        user = (
            await session.execute(
                select(User).where(
                    User.workspace_id == workspace.id,
                    func.lower(User.email) == principal.email.lower(),
                )
            )
        ).scalar_one_or_none()
        if user is not None and not _email_allowed(settings, principal):
            raise NotInvited()

    if user is None:
        if not (
            settings.auto_provision and principal.email and _email_allowed(settings, principal)
        ):
            raise NotInvited()
        is_admin = principal.email.lower() in settings.bootstrap_admins or (
            settings.admin_role in principal.roles
        )
        user = User(
            workspace_id=workspace.id,
            email=principal.email.lower(),
            name=principal.name or principal.email.split("@")[0],
            role="admin" if is_admin else "member",
            status="active",
        )
        session.add(user)
        await session.flush()

    if user.status == "disabled":
        raise AccountDisabled()
    if user.status == "invited":
        user.status = "active"

    if identity is None:
        identity = UserIdentity(
            user_id=user.id,
            provider=principal.provider,
            tenant_id=tenant,
            subject=principal.subject,
            email_at_link=principal.email,
        )
        session.add(identity)
    identity.last_login_at = now

    if settings.sync_admin_role and settings.admin_role in principal.roles and user.role != "admin":
        user.role = "admin"
    user.last_seen_at = now
    await session.flush()
    return user, workspace
