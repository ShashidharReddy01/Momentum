"""Phase 7.6 S76-05 (spec §7.1): entities (vendors now; customers, contracts and merchants later).

- **Writes:** create, update, add alias, set bank details, merge (moves records' ``entity_ids``,
  aliases and skills to the survivor) and archive, each with activity, an outbox event and undo.
  Members (never guests) create and update; merging and archiving are for workspace admins and the
  pack's stewards.
- **Matching** (``match``): an exact tax id, then an exact alias or name, then trigram similarity
  ≥ 0.6 on name and aliases, otherwise candidates for the pack to choose from (or ask about).
- **Bank details** are only ever a fingerprint (HMAC-SHA256 keyed by the workspace's secret) and
  the last four digits. The fingerprint never leaves the server: ``entity_out`` drops every
  ``fingerprint`` key before anything is returned.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import record_activity
from momentum.core.context import Ctx
from momentum.core.errors import Conflict, Forbidden, NotFound, ValidationFailed, VersionConflict
from momentum.core.events import emit
from momentum.core.settings import Settings
from momentum.core.undo import UndoConflict, undo_handler, undo_op
from momentum.domain.entities.models import Entity
from momentum.domain.records.models import Record
from momentum.domain.skills.models import Skill

MATCH_THRESHOLD = 0.6
MAX_SCAN = 5000  # entities of one type compared exactly (vendors: hundreds)
_SLUG = re.compile(r"[^a-z0-9]+")


class EntityTypeImpl(Protocol):
    """What the domain asks of a pack's entity type (``momentum.sdk.EntityType``)."""

    @property
    def key(self) -> str: ...

    @property
    def label(self) -> str: ...

    def validate(self, attributes: dict[str, Any]) -> dict[str, Any]: ...


class EntityOut(BaseModel):
    id: uuid.UUID
    type: str
    key: str
    name: str
    aliases: list[str]
    attributes: dict[str, Any]
    profile: dict[str, Any]
    status: str
    merged_into: uuid.UUID | None
    created_via: str
    version: int
    created_at: datetime
    updated_at: datetime


def _hide(value: Any) -> Any:
    """Every ``fingerprint`` removed, anywhere; a bank becomes "•••• 4821, first seen …"."""
    if isinstance(value, dict):
        out = {k: _hide(v) for k, v in value.items() if k != "fingerprint"}
        if "last4" in value and "fingerprint" in value:
            seen = str(value.get("seen_first") or "")[:7]
            out["display"] = f"•••• {value['last4']}" + (f", first seen {seen}" if seen else "")
        return out
    if isinstance(value, list):
        return [_hide(v) for v in value]
    return value


def entity_out(e: Entity) -> EntityOut:
    return EntityOut(
        id=e.id,
        type=e.type,
        key=e.key,
        name=e.name,
        aliases=list(e.aliases or []),
        attributes=_hide(e.attributes or {}),
        profile=e.profile or {},
        status=e.status,
        merged_into=e.merged_into,
        created_via=e.created_via,
        version=e.version,
        created_at=e.created_at,
        updated_at=e.updated_at,
    )


def slug(name: str) -> str:
    return _SLUG.sub("-", name.casefold()).strip("-")[:100] or "entity"


def _match_text(name: str, aliases: list[str]) -> str:
    return " | ".join([name, *aliases])[:4000]


def bank_fingerprint(settings: Settings, workspace_id: uuid.UUID, account: str) -> tuple[str, str]:
    """``(fingerprint, last4)`` of an account number or IBAN. Spaces and case don't matter."""
    normal = re.sub(r"[\s-]", "", account).upper()
    if len(normal) < 4:
        raise ValidationFailed("That isn't an account number")
    key = hmac.new(
        settings.secret_key.encode(), str(workspace_id).encode(), hashlib.sha256
    ).digest()
    return hmac.new(key, normal.encode(), hashlib.sha256).hexdigest(), normal[-4:]


def _member(ctx: Ctx) -> None:
    if ctx.actor.role == "guest":
        raise Forbidden("Guests can't see agents' vendors and other entities")


async def _steward_or_admin(session: AsyncSession, ctx: Ctx, e: Entity) -> None:
    from momentum.domain.pack_settings.service import is_steward

    if ctx.actor.is_admin or await is_steward(session, ctx.workspace_id, e.pack_key, ctx.actor.id):
        return
    raise Forbidden("Only workspace admins and the agent's stewards can do this")


def _validate(impl: EntityTypeImpl, attributes: dict[str, Any]) -> dict[str, Any]:
    try:
        return impl.validate(attributes)
    except ValidationError as e:
        problems = "; ".join(
            f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()[:6]
        )
        raise ValidationFailed(f"The {impl.label} isn't valid: {problems}") from e


async def get_entity(
    session: AsyncSession, ctx: Ctx, entity_id: uuid.UUID, *, lock: bool = False
) -> Entity:
    _member(ctx)
    e = await session.get(Entity, entity_id, with_for_update=lock or None)
    if e is None or e.workspace_id != ctx.workspace_id:
        raise NotFound("Not found")
    return e


async def list_entities(
    session: AsyncSession,
    ctx: Ctx,
    *,
    type: str | None = None,
    q: str | None = None,
    status: str | None = "active",
    limit: int = 50,
) -> list[Entity]:
    _member(ctx)
    stmt = select(Entity).where(Entity.workspace_id == ctx.workspace_id)
    if type:
        stmt = stmt.where(Entity.type == type)
    if status:
        stmt = stmt.where(Entity.status == status)
    if q:
        stmt = stmt.where(func.lower(Entity.match_text).contains(q.lower(), autoescape=True))
    return list((await session.execute(stmt.order_by(Entity.name).limit(limit))).scalars())


def _event(e: Entity) -> dict[str, Any]:
    return {"type": e.type, "version": e.version}


# ---------------------------------------------------------------- create / update / alias


async def create_entity(
    session: AsyncSession,
    ctx: Ctx,
    impl: EntityTypeImpl,
    *,
    pack_key: str,
    name: str,
    aliases: list[str] | None = None,
    attributes: dict[str, Any] | None = None,
) -> Entity:
    _member(ctx)
    name = " ".join(name.split())[:300]
    if not name:
        raise ValidationFailed("An entity needs a name")
    clean = _validate(impl, attributes or {})
    base = slug(name)
    key, n = base, 1
    while await session.scalar(
        select(Entity.id).where(
            Entity.workspace_id == ctx.workspace_id, Entity.type == impl.key, Entity.key == key
        )
    ):
        n += 1
        key = f"{base}-{n}"
    names = [
        a for a in dict.fromkeys(" ".join(x.split()) for x in aliases or []) if a and a != name
    ]
    e = Entity(
        workspace_id=ctx.workspace_id,
        pack_key=pack_key,
        type=impl.key,
        key=key,
        name=name,
        aliases=names,
        match_text=_match_text(name, names),
        attributes=clean,
        profile={},
        status="active",
        created_by=ctx.actor.id,
        created_via=ctx.via,
        version=1,
    )
    session.add(e)
    await session.flush()
    act = await record_activity(
        session,
        ctx,
        entity_type="entity",
        entity_id=e.id,
        verb="entity.created",
        changes={"name": (None, name)},
        undo=undo_op("entities.archive_new", entity_id=e.id, version=1),
    )
    await emit(
        session,
        ctx,
        type="entity.created",
        entity_type="entity",
        entity_id=e.id,
        data=_event(e),
        channels=[f"workspace:{ctx.workspace_id}"],
        activity_id=act.id,
    )
    await session.refresh(e, attribute_names=["created_at", "updated_at"])
    return e


async def _changed(session: AsyncSession, ctx: Ctx, e: Entity, before: dict[str, Any]) -> None:
    e.version += 1
    e.match_text = _match_text(e.name, list(e.aliases or []))
    act = await record_activity(
        session,
        ctx,
        entity_type="entity",
        entity_id=e.id,
        verb="entity.updated",
        # what people see in history: never the bank fingerprint (the undo keeps it, server-side)
        changes={
            k: (_hide(v), _hide(getattr(e, k))) for k, v in before.items() if v != getattr(e, k)
        },
        undo=undo_op("entities.restore", entity_id=e.id, before=before, expect=e.version),
    )
    await emit(
        session,
        ctx,
        type="entity.updated",
        entity_type="entity",
        entity_id=e.id,
        data=_event(e),
        channels=[f"workspace:{ctx.workspace_id}"],
        activity_id=act.id,
    )
    await session.flush()
    await session.refresh(e, attribute_names=["updated_at"])


def _snapshot(e: Entity) -> dict[str, Any]:
    return {
        "name": e.name,
        "aliases": list(e.aliases or []),
        "attributes": dict(e.attributes or {}),
        "status": e.status,
    }


async def update_entity(
    session: AsyncSession,
    ctx: Ctx,
    impl: EntityTypeImpl,
    entity_id: uuid.UUID,
    *,
    name: str | None = None,
    attributes: dict[str, Any] | None = None,
    expected_version: int | None = None,
) -> Entity:
    """A new name and/or attributes merged over the current ones (a key set to ``None`` is
    removed); validated against the type's model."""
    e = await get_entity(session, ctx, entity_id, lock=True)
    if e.status != "active":
        raise Conflict(f"This {impl.label} is {e.status}")
    if expected_version is not None and expected_version != e.version:
        raise VersionConflict("This was changed by someone else", version=e.version)
    before = _snapshot(e)
    if name is not None:
        new = " ".join(name.split())[:300]
        if not new:
            raise ValidationFailed("An entity needs a name")
        if new != e.name and e.name not in (e.aliases or []):
            e.aliases = [*(e.aliases or []), e.name]  # the old name stays findable
        e.name = new
    if attributes is not None:
        merged = {**(e.attributes or {}), **attributes}
        e.attributes = _validate(impl, {k: v for k, v in merged.items() if v is not None})
    await _changed(session, ctx, e, before)
    return e


async def add_alias(session: AsyncSession, ctx: Ctx, entity_id: uuid.UUID, alias: str) -> Entity:
    e = await get_entity(session, ctx, entity_id, lock=True)
    alias = " ".join(alias.split())[:300]
    if not alias:
        raise ValidationFailed("An alias needs some text")
    if alias == e.name or alias in (e.aliases or []):
        return e
    before = _snapshot(e)
    e.aliases = [*(e.aliases or []), alias]
    await _changed(session, ctx, e, before)
    return e


async def set_bank(
    session: AsyncSession, ctx: Ctx, entity_id: uuid.UUID, account: str, *, seen: date | None = None
) -> tuple[bool, str]:
    """Record the bank account an entity was seen with. Returns ``(changed, last4)``: whether it
    differs from the one on file, and its last four digits.

    The first account becomes the one on file. A **different** one never replaces it here (S76-10:
    an invoice must not be able to vouch for its own bank details): it's kept as ``pending``
    until a person confirms it with the vendor (``confirm_bank``)."""
    e = await get_entity(session, ctx, entity_id, lock=True)
    fp, last4 = bank_fingerprint(ctx.settings, ctx.workspace_id, account)
    on_file = (e.attributes or {}).get("bank") or {}
    day = (seen or datetime.now(UTC).date()).isoformat()
    changed = bool(on_file.get("fingerprint")) and on_file.get("fingerprint") != fp
    if on_file.get("fingerprint") == fp:
        bank = {**on_file, "seen_last": day}
    elif changed:
        bank = {**on_file, "pending": {"fingerprint": fp, "last4": last4, "seen": day}}
    else:
        bank = {"fingerprint": fp, "last4": last4, "seen_first": day, "seen_last": day}
    before = _snapshot(e)
    e.attributes = {**(e.attributes or {}), "bank": bank}
    await _changed(session, ctx, e, before)
    return changed, last4


async def confirm_bank(session: AsyncSession, ctx: Ctx, entity_id: uuid.UUID, last4: str) -> bool:
    """A person confirmed the pending account (the one ending ``last4``) with the vendor: it
    becomes the one on file. False when there's no such pending account."""
    e = await get_entity(session, ctx, entity_id, lock=True)
    on_file = (e.attributes or {}).get("bank") or {}
    pending = on_file.get("pending") or {}
    if not pending.get("fingerprint") or pending.get("last4") != last4:
        return False
    before = _snapshot(e)
    e.attributes = {
        **(e.attributes or {}),
        "bank": {
            "fingerprint": pending["fingerprint"],
            "last4": pending["last4"],
            "seen_first": pending.get("seen"),
            "seen_last": pending.get("seen"),
            "previous_last4": on_file.get("last4"),
        },
    }
    await _changed(session, ctx, e, before)
    return True


async def bank_matches(
    session: AsyncSession, ctx: Ctx, entity_id: uuid.UUID, account: str
) -> bool | None:
    """Whether ``account`` is the one on file (``None`` when none is)."""
    e = await get_entity(session, ctx, entity_id)
    on_file = (e.attributes or {}).get("bank") or {}
    if not on_file.get("fingerprint"):
        return None
    fp, _ = bank_fingerprint(ctx.settings, ctx.workspace_id, account)
    return hmac.compare_digest(on_file["fingerprint"], fp)


# ---------------------------------------------------------------- merge / archive


async def merge(
    session: AsyncSession, ctx: Ctx, source_id: uuid.UUID, into_id: uuid.UUID
) -> Entity:
    """Merge ``source`` into ``into``: its records, aliases (and name) and skills move to the
    survivor; the source is kept as ``merged``. Undo moves them back."""
    if source_id == into_id:
        raise ValidationFailed("Pick two different entities")
    source = await get_entity(session, ctx, source_id, lock=True)
    into = await get_entity(session, ctx, into_id, lock=True)
    await _steward_or_admin(session, ctx, into)
    if source.type != into.type:
        raise ValidationFailed("Only entities of the same type can be merged")
    if source.status != "active" or into.status != "active":
        raise Conflict("Only active entities can be merged")
    record_ids = list(
        (
            await session.execute(
                select(Record.id).where(
                    Record.workspace_id == ctx.workspace_id,
                    Record.entity_ids.contains([source.id]),
                )
            )
        ).scalars()
    )
    if record_ids:
        await session.execute(
            update(Record)
            .where(Record.id.in_(record_ids))
            .values(entity_ids=func.array_replace(Record.entity_ids, source.id, into.id))
        )
    skill_ids = list(
        (
            await session.execute(
                select(Skill.id).where(
                    Skill.workspace_id == ctx.workspace_id,
                    Skill.scope_type == "entity",
                    Skill.scope_id == source.id,
                )
            )
        ).scalars()
    )
    if skill_ids:
        await session.execute(update(Skill).where(Skill.id.in_(skill_ids)).values(scope_id=into.id))
    added = [
        a
        for a in dict.fromkeys([source.name, *(source.aliases or [])])
        if a != into.name and a not in (into.aliases or [])
    ]
    into_before = _snapshot(into)
    into.aliases = [*(into.aliases or []), *added]
    into.version += 1
    into.match_text = _match_text(into.name, list(into.aliases))
    source.status, source.merged_into = "merged", into.id
    source.version += 1
    act = await record_activity(
        session,
        ctx,
        entity_type="entity",
        entity_id=into.id,
        verb="entity.merged",
        changes={"merged": (None, str(source.id)), "records": (None, len(record_ids))},
        undo=undo_op(
            "entities.unmerge",
            source_id=source.id,
            into_id=into.id,
            record_ids=record_ids,
            skill_ids=skill_ids,
            into_before=into_before,
            into_version=into.version,
        ),
    )
    await emit(
        session,
        ctx,
        type="entity.merged",
        entity_type="entity",
        entity_id=into.id,
        data={"type": into.type, "merged": str(source.id), "records": len(record_ids)},
        channels=[f"workspace:{ctx.workspace_id}"],
        activity_id=act.id,
    )
    await session.flush()
    await session.refresh(into, attribute_names=["updated_at"])
    return into


async def archive(session: AsyncSession, ctx: Ctx, entity_id: uuid.UUID) -> Entity:
    e = await get_entity(session, ctx, entity_id, lock=True)
    await _steward_or_admin(session, ctx, e)
    if e.status != "active":
        raise Conflict(f"This is already {e.status}")
    before = _snapshot(e)
    e.status = "archived"
    await _changed(session, ctx, e, before)
    return e


@undo_handler("entities.archive_new")
async def _undo_create(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    e = await session.get(Entity, uuid.UUID(str(args["entity_id"])), with_for_update=True)
    if e is None or e.version != int(args["version"]) or e.status != "active":
        raise UndoConflict("This changed after it was made")
    e.status = "archived"
    e.version += 1


@undo_handler("entities.restore")
async def _undo_update(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    e = await session.get(Entity, uuid.UUID(str(args["entity_id"])), with_for_update=True)
    if e is None or e.version != int(args["expect"]):
        raise UndoConflict("This changed again since")
    before = args["before"]
    e.name, e.aliases, e.attributes, e.status = (
        before["name"],
        list(before["aliases"]),
        dict(before["attributes"]),
        before["status"],
    )
    e.version += 1
    e.match_text = _match_text(e.name, list(e.aliases))


@undo_handler("entities.unmerge")
async def _undo_merge(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    source = await session.get(Entity, uuid.UUID(str(args["source_id"])), with_for_update=True)
    into = await session.get(Entity, uuid.UUID(str(args["into_id"])), with_for_update=True)
    if source is None or into is None or into.version != int(args["into_version"]):
        raise UndoConflict("The merged entity changed since")
    record_ids = [uuid.UUID(x) for x in args.get("record_ids") or []]
    if record_ids:
        await session.execute(
            update(Record)
            .where(Record.id.in_(record_ids))
            .values(entity_ids=func.array_replace(Record.entity_ids, into.id, source.id))
        )
    skill_ids = [uuid.UUID(x) for x in args.get("skill_ids") or []]
    if skill_ids:
        await session.execute(
            update(Skill).where(Skill.id.in_(skill_ids)).values(scope_id=source.id)
        )
    before = args["into_before"]
    into.aliases = list(before["aliases"])
    into.match_text = _match_text(into.name, list(into.aliases))
    into.version += 1
    source.status, source.merged_into = "active", None
    source.version += 1


# ---------------------------------------------------------------- matching


@dataclass
class Candidate:
    id: uuid.UUID
    name: str
    score: float


@dataclass
class MatchResult:
    """``entity_id`` when one entity matched with certainty (``method``: tax_id, alias, name,
    similar); otherwise ``candidates``, best first, for the pack to choose from or ask about."""

    entity_id: uuid.UUID | None = None
    method: str | None = None
    candidates: list[Candidate] = field(default_factory=list)


def _norm_tax(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


async def match(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    type: str,
    name: str,
    *,
    tax_id: str | None = None,
    limit: int = 5,
) -> MatchResult:
    active = list(
        (
            await session.execute(
                select(Entity)
                .where(
                    Entity.workspace_id == workspace_id,
                    Entity.type == type,
                    Entity.status == "active",
                )
                .limit(MAX_SCAN)
            )
        ).scalars()
    )
    if tax_id:
        wanted = _norm_tax(tax_id)
        for e in active:
            if any(_norm_tax(str(t)) == wanted for t in (e.attributes or {}).get("tax_ids") or []):
                return MatchResult(e.id, "tax_id")
    clean = " ".join(name.split())
    folded = clean.casefold()
    for e in active:
        if e.name.casefold() == folded:
            return MatchResult(e.id, "name")
    for e in active:
        if any(a.casefold() == folded for a in e.aliases or []):
            return MatchResult(e.id, "alias")
    score = func.word_similarity(clean, Entity.match_text)
    rows = (
        await session.execute(
            select(Entity, score)
            .where(
                Entity.workspace_id == workspace_id, Entity.type == type, Entity.status == "active"
            )
            .where(score >= 0.3)
            .order_by(score.desc())
            .limit(limit)
        )
    ).tuples()
    found = [Candidate(e.id, e.name, float(s)) for e, s in rows]
    if (
        found
        and found[0].score >= MATCH_THRESHOLD
        and (len(found) == 1 or found[0].score - found[1].score >= 0.1)
    ):
        return MatchResult(found[0].id, "similar", found)
    return MatchResult(None, None, found)


async def set_profile(session: AsyncSession, entity_id: uuid.UUID, profile: dict[str, Any]) -> None:
    """The nightly profile (computed data from approved records, like a forecast: no activity)."""
    e = await session.get(Entity, entity_id)
    if e is not None:
        e.profile = profile
        await session.flush()
