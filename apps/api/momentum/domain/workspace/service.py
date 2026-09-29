from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import record_activity
from momentum.core.context import Ctx
from momentum.core.errors import NotFound, ValidationFailed
from momentum.core.events import emit
from momentum.core.ids import new_id
from momentum.core.mutation import Mutation
from momentum.core.permissions import Action, require
from momentum.core.settings import Settings
from momentum.core.undo import undo_handler, undo_op
from momentum.domain.workspace.models import Workspace


async def get_by_slug(session: AsyncSession, slug: str) -> Workspace | None:
    result = await session.execute(select(Workspace).where(Workspace.slug == slug))
    return result.scalar_one_or_none()


async def ensure_default_workspace(session: AsyncSession, settings: Settings) -> Workspace:
    """Single-workspace mode: return the default workspace, creating it on first use. Safe when
    several first requests arrive at once (insert-or-keep, then read)."""
    ws = await get_by_slug(session, settings.default_workspace_slug)
    if ws is None:
        await session.execute(
            insert(Workspace)
            .values(
                id=new_id(),
                name=settings.default_workspace_name,
                slug=settings.default_workspace_slug,
            )
            .on_conflict_do_nothing(index_elements=["slug"])
        )
        ws = await get_by_slug(session, settings.default_workspace_slug)
        assert ws is not None
    return ws


# ---------------- AI configuration (S3.5.2) ----------------


class AiConfig(BaseModel):
    """Admin-editable AI policy, stored in ``workspaces.settings['ai']``.

    Each field is an *override*: ``None`` means "use the deployment's value from
    ``momentum.core.settings``", so an untouched workspace behaves exactly as its environment
    configures it. See ``effective_ai`` for how the two combine.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    monthly_budget_usd: float | None = Field(default=None, ge=0)
    # Whether members' "apply low-risk changes without asking" preference is honoured at all.
    allow_auto_apply: bool | None = None
    # S5.1.4: may agents at `auto` apply medium-risk changes on their own (ai-architecture §4)?
    # Off unless an admin turns it on.
    allow_medium_auto: bool | None = None


class EffectiveAi(BaseModel):
    """What the running system actually does, after combining environment and workspace."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    monthly_budget_usd: float
    allow_auto_apply: bool
    allow_medium_auto: bool


def effective_ai(settings: Settings, config: AiConfig) -> EffectiveAi:
    """Environment bounds the workspace: an admin can switch AI **off** where the deployment
    allows it, but never on where the deployment disabled it (``MOMENTUM_AI_ENABLED`` stays the
    outer kill switch, so a misconfigured workspace can't start spending)."""
    return EffectiveAi(
        enabled=settings.ai_enabled and (config.enabled is not False),
        monthly_budget_usd=(
            settings.ai_monthly_budget_usd
            if config.monthly_budget_usd is None
            else config.monthly_budget_usd
        ),
        allow_auto_apply=config.allow_auto_apply is not False,
        allow_medium_auto=config.allow_medium_auto is True,
    )


def read_ai_config(ws: Workspace) -> AiConfig:
    return AiConfig.model_validate((ws.settings or {}).get("ai") or {})


async def get_ai_config(session: AsyncSession, workspace_id: Any) -> AiConfig:
    ws = await session.get(Workspace, workspace_id)
    if ws is None:
        raise NotFound("Workspace not found")
    return read_ai_config(ws)


async def get_ai_config_for_admin(session: AsyncSession, ctx: Ctx) -> tuple[AiConfig, EffectiveAi]:
    """The admin settings page (S3.5.2): the raw overrides (for the edit form) and what they
    currently resolve to. Workspace admins only; everyone else uses ``get_ai_config`` internally
    without this gate (e.g. to decide whether their own low-risk auto-apply preference applies)."""
    require(ctx, Action.WORKSPACE_ADMIN)
    config = await get_ai_config(session, ctx.workspace_id)
    return config, effective_ai(ctx.settings, config)


async def set_ai_config(session: AsyncSession, ctx: Ctx, config: AiConfig) -> Mutation[EffectiveAi]:
    """Change the workspace's AI policy. Workspace admins only: it governs whether Mo runs at all
    and how much it may spend."""
    require(ctx, Action.WORKSPACE_ADMIN)
    ws = await session.get(Workspace, ctx.workspace_id)
    if ws is None:
        raise NotFound("Workspace not found")
    before = read_ai_config(ws)
    # JSONB is mutated wholesale so SQLAlchemy sees the change.
    ws.settings = {**(ws.settings or {}), "ai": config.model_dump()}
    act = await record_activity(
        session,
        ctx,
        entity_type="workspace",
        entity_id=ws.id,
        verb="workspace.ai_settings_updated",
        changes={
            field: (getattr(before, field), getattr(config, field))
            for field in AiConfig.model_fields
            if getattr(before, field) != getattr(config, field)
        },
        undo=undo_op("workspace.set_ai_settings", **before.model_dump()),
    )
    await emit(
        session,
        ctx,
        type="workspace.ai_settings_changed",
        entity_type="workspace",
        entity_id=ws.id,
        data={},
        channels=[f"workspace:{ws.id}"],
        activity_id=act.id,
    )
    await session.flush()
    return Mutation(effective_ai(ctx.settings, config), act.id)


@undo_handler("workspace.set_ai_settings")
async def _undo_set_ai_config(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    await set_ai_config(session, ctx, AiConfig.model_validate(args))


# ---------------- workspace timezone (S5.1.2) ----------------


def workspace_timezone(ws: Workspace) -> str:
    """The workspace's timezone (IANA name), for schedules that say ``timezone: workspace``
    (agents, S5.1.2). Stored in ``workspaces.settings['timezone']``; default UTC."""
    return str((ws.settings or {}).get("timezone") or "UTC")


async def set_workspace_timezone(session: AsyncSession, ctx: Ctx, tz: str) -> Mutation[str]:
    require(ctx, Action.WORKSPACE_ADMIN)
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ValidationFailed(f"Unknown timezone {tz!r}") from e
    ws = await session.get(Workspace, ctx.workspace_id)
    if ws is None:
        raise NotFound("Workspace not found")
    before = workspace_timezone(ws)
    if before == tz:
        return Mutation(tz)
    ws.settings = {**(ws.settings or {}), "timezone": tz}
    act = await record_activity(
        session,
        ctx,
        entity_type="workspace",
        entity_id=ws.id,
        verb="workspace.timezone_changed",
        changes={"timezone": (before, tz)},
        undo=undo_op("workspace.set_timezone", tz=before),
    )
    await emit(
        session,
        ctx,
        type="workspace.settings_changed",
        entity_type="workspace",
        entity_id=ws.id,
        data={"timezone": tz},
        channels=[f"workspace:{ws.id}"],
        activity_id=act.id,
    )
    await session.flush()
    return Mutation(tz, act.id)


@undo_handler("workspace.set_timezone")
async def _undo_set_timezone(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    await set_workspace_timezone(session, ctx, str(args["tz"]))
