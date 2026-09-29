"""S5.1.6 (ADR-0009): API tokens, so scripts outside Momentum can call its API.

- A token acts as one user: a person (their own token) or an **agent account** (issued by an
  admin, so an external script shows up as that agent). It never gets more than that user may do,
  and its **scopes narrow it further** (``SCOPES``).
- The secret is shown once. Only its SHA-256 is stored, with a short prefix for recognising it.
- Tokens expire (at most a year) and can be revoked; either makes them fail at once.
- Tokens are made in the app (a signed-in session), never with another token.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import record_activity
from momentum.core.context import Ctx
from momentum.core.errors import Forbidden, NotFound, ValidationFailed
from momentum.core.events import emit
from momentum.core.mutation import Mutation
from momentum.core.permissions import Action, can
from momentum.domain.users.models import ApiToken, User

TOKEN_PREFIX = "mtm_"  # noqa: S105 - a public marker, not a secret
# read: any GET · tasks:write: tasks, projects, sections, comments, fields, tags, forms, undo ·
# attachments:write: uploads · ai: Mo and agent runs · admin: everything else (still only what
# the user's own role allows)
SCOPES = ("read", "tasks:write", "attachments:write", "ai", "admin")
MAX_DAYS = 365
DEFAULT_DAYS = 90
TOUCH_EVERY = timedelta(minutes=1)  # last_used_at is refreshed at most this often


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _check_request(ctx: Ctx, scopes: list[str], days: int | None) -> None:
    if ctx.via == "api" or ctx.actor.id is None or ctx.actor.is_agent:
        raise Forbidden("Tokens are created in the app by a signed-in person")
    if not scopes or any(s not in SCOPES for s in scopes) or len(set(scopes)) != len(scopes):
        raise ValidationFailed(f"Scopes must be some of: {', '.join(SCOPES)}")
    if days is not None and not 1 <= days <= MAX_DAYS:
        raise ValidationFailed(f"A token lasts between 1 and {MAX_DAYS} days")


async def create_token(
    session: AsyncSession,
    ctx: Ctx,
    *,
    name: str,
    scopes: list[str],
    expires_in_days: int | None = DEFAULT_DAYS,
    for_user: User | None = None,
) -> tuple[Mutation[ApiToken], str]:
    """A new token for the caller, or — admins only — for an agent account. Returns the token
    row and the secret (shown once, never stored)."""
    _check_request(ctx, scopes, expires_in_days)
    days = expires_in_days or DEFAULT_DAYS
    if for_user is None:
        owner_id = ctx.actor.id
        assert owner_id is not None
        if ctx.actor.role == "guest" and scopes != ["read"]:
            raise ValidationFailed("Guests can only make read-only tokens")
    else:
        if not can(ctx, Action.WORKSPACE_ADMIN):
            raise Forbidden("Only workspace admins issue tokens for agents")
        if not for_user.is_agent or for_user.workspace_id != ctx.workspace_id:
            raise ValidationFailed("Tokens for someone else can only be for an agent")
        owner_id = for_user.id
    if "admin" in scopes and for_user is None and not ctx.actor.is_admin:
        raise ValidationFailed("Only admins can make tokens with the admin scope")
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    token = ApiToken(
        workspace_id=ctx.workspace_id,
        user_id=owner_id,
        name=name.strip()[:100] or "Token",
        token_hash=hash_token(raw),
        prefix=raw[: len(TOKEN_PREFIX) + 6],
        scopes=list(scopes),
        expires_at=datetime.now(UTC) + timedelta(days=days),
    )
    session.add(token)
    await session.flush()
    # never the secret or its hash: name, prefix, scopes, owner, expiry
    act = await record_activity(
        session,
        ctx,
        entity_type="api_token",
        entity_id=token.id,
        verb="api_token.created",
        changes={
            "name": (None, token.name),
            "prefix": (None, token.prefix),
            "scopes": (None, token.scopes),
            "user_id": (None, owner_id),
        },
    )
    await emit(
        session,
        ctx,
        type="api_token.created",
        entity_type="api_token",
        entity_id=token.id,
        data={"user_id": str(owner_id)},
        channels=[f"user:{owner_id}"],
        activity_id=act.id,
    )
    return Mutation(token, act.id), raw


async def list_tokens(session: AsyncSession, ctx: Ctx, user_id: uuid.UUID) -> list[ApiToken]:
    """A person's own tokens, or (admins) an agent's."""
    if user_id != ctx.actor.id:
        owner = await session.get(User, user_id)
        if owner is None or not owner.is_agent or not can(ctx, Action.WORKSPACE_ADMIN):
            raise NotFound("Not found")
    rows = await session.execute(
        select(ApiToken)
        .where(ApiToken.user_id == user_id, ApiToken.workspace_id == ctx.workspace_id)
        .order_by(ApiToken.created_at.desc())
    )
    return list(rows.scalars())


async def revoke_token(session: AsyncSession, ctx: Ctx, token_id: uuid.UUID) -> Mutation[ApiToken]:
    token = await session.get(ApiToken, token_id)
    if token is None or token.workspace_id != ctx.workspace_id:
        raise NotFound("Token not found")
    owner = await session.get(User, token.user_id)
    mine = token.user_id == ctx.actor.id
    admin_for_agent = owner is not None and owner.is_agent and can(ctx, Action.WORKSPACE_ADMIN)
    if not (mine or admin_for_agent):
        raise NotFound("Token not found")
    if token.revoked_at is not None:
        return Mutation(token)
    token.revoked_at = datetime.now(UTC)
    act = await record_activity(
        session,
        ctx,
        entity_type="api_token",
        entity_id=token.id,
        verb="api_token.revoked",
        changes={"revoked_at": (None, token.revoked_at)},
    )
    await emit(
        session,
        ctx,
        type="api_token.revoked",
        entity_type="api_token",
        entity_id=token.id,
        data={"user_id": str(token.user_id)},
        channels=[f"user:{token.user_id}"],
        activity_id=act.id,
    )
    return Mutation(token, act.id)


async def authenticate_token(session: AsyncSession, raw: str) -> tuple[ApiToken, User] | None:
    """The live token and its active user for a presented secret, else None."""
    if not raw.startswith(TOKEN_PREFIX):
        return None
    token = (
        await session.execute(select(ApiToken).where(ApiToken.token_hash == hash_token(raw)))
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if token is None or token.revoked_at is not None:
        return None
    if token.expires_at is not None and token.expires_at <= now:
        return None
    user = await session.get(User, token.user_id)
    if user is None or user.status != "active" or user.workspace_id != token.workspace_id:
        return None
    if token.last_used_at is None or now - token.last_used_at >= TOUCH_EVERY:
        token.last_used_at = now
    return token, user
