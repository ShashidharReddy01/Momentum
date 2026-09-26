"""Per-user AI preferences (S3.2.2), kept in ``users.prefs['ai']`` like view prefs (a personal
setting, not shared data: no activity row, same precedent as ``set_view_prefs``)."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.domain.users.models import User


class AiPrefs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    auto_apply_low_risk: bool = False


async def get_prefs(session: AsyncSession, ctx: Ctx) -> AiPrefs:
    raw: dict[str, Any] | None = (
        await session.execute(select(User.prefs).where(User.id == ctx.actor.id))
    ).scalar_one_or_none()
    return AiPrefs.model_validate((raw or {}).get("ai") or {})


async def set_prefs(session: AsyncSession, ctx: Ctx, prefs: AiPrefs) -> AiPrefs:
    await session.execute(
        text(
            "UPDATE users SET prefs = jsonb_set(coalesce(prefs, '{}'::jsonb), '{ai}', "
            "cast(:value as jsonb)) WHERE id = :uid"
        ),
        {"value": json.dumps(prefs.model_dump()), "uid": ctx.actor.id},
    )
    return prefs
