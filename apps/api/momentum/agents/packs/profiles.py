"""Phase 7.6 S76-05 (spec §7.1): entity profiles. For each pack entity type with a ``profile``
hook, the hook gets the entity (bank details hidden) and the data of its approved records, and
returns statistics that are stored on the entity (computed data: no activity)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.telemetry import get_logger
from momentum.domain.entities.models import Entity
from momentum.domain.entities.service import entity_out, set_profile
from momentum.domain.records.models import Record

log = get_logger("packs.profiles")


async def compute_profiles(session: AsyncSession, packs: Any) -> int:
    done = 0
    for pack in getattr(packs, "packs", {}).values():
        for et in pack.entity_types:
            if et.profile_fn is None:
                continue
            rows = (
                await session.execute(
                    select(Entity).where(Entity.type == et.key, Entity.status == "active")
                )
            ).scalars()
            for e in list(rows):
                records = (
                    await session.execute(
                        select(Record.data).where(
                            Record.workspace_id == e.workspace_id,
                            Record.entity_ids.contains([e.id]),
                            Record.status == "approved",
                            Record.deleted_at.is_(None),
                        )
                    )
                ).scalars()
                view = entity_out(e).model_dump(mode="json")
                try:
                    profile = et.profile_fn(view, list(records))
                except Exception:  # one bad profile never stops the others
                    log.exception("entity_profile_failed", pack=pack.key, entity=str(e.id))
                    continue
                await set_profile(session, e.id, profile)
                done += 1
    return done
