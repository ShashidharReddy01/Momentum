"""Phase 7.6 S76-05 (spec §7.2): skills, what an agent learned and may use.

Lifecycle: **propose** (a pack's ``learn`` job, or a person authoring one) → **try out** (the pack's
``tryout`` child job compares before/after on approved records) → **decide** (stewards and
workspace admins approve, edit-and-approve, or reject) → **use** (``active_for``, most specific
first; uses, helped and hurt are counted) → **retire** (by a person; suggested, never automatic,
when ``hurt > helped`` after 5 uses).

Every proposed text goes through the scrubber first: a skill that carries a value from the record
it was learned from, an email, an IBAN, a card number… is **refused**, kept as ``rejected`` with
the reason and only its redacted text, so nothing leaks into later prompts.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import record_activity
from momentum.core.context import Ctx
from momentum.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from momentum.core.events import emit
from momentum.core.scrub import scrub
from momentum.core.settings import Settings
from momentum.core.undo import UndoConflict, undo_handler, undo_op
from momentum.domain.skills.models import SKILL_KINDS, SKILL_SCOPES, Skill

HURTING_AFTER = 5
SPECIFICITY = {"entity": 0, "project": 1, "workspace": 2}
MAX_TEXT = 500


class SkillOut(BaseModel):
    id: uuid.UUID
    pack_key: str
    scope_type: str
    scope_id: uuid.UUID | None
    kind: str
    field: str | None
    content: dict[str, Any]
    status: str
    version: int
    supersedes_id: uuid.UUID | None
    source: str
    provenance: dict[str, Any]
    tryout: dict[str, Any] | None
    metrics: dict[str, Any]
    may_be_hurting: bool
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    decision_note: str | None
    created_at: datetime


def may_be_hurting(s: Skill) -> bool:
    m = s.metrics or {}
    return (
        s.status == "active"
        and int(m.get("uses", 0)) >= HURTING_AFTER
        and int(m.get("hurt", 0)) > int(m.get("helped", 0))
    )


def skill_out(s: Skill) -> SkillOut:
    return SkillOut(
        id=s.id,
        pack_key=s.pack_key,
        scope_type=s.scope_type,
        scope_id=s.scope_id,
        kind=s.kind,
        field=s.field,
        content=s.content,
        status=s.status,
        version=s.version,
        supersedes_id=s.supersedes_id,
        source=s.source,
        provenance=s.provenance or {},
        tryout=s.tryout,
        metrics=s.metrics or {},
        may_be_hurting=may_be_hurting(s),
        decided_by=s.decided_by,
        decided_at=s.decided_at,
        decision_note=s.decision_note,
        created_at=s.created_at,
    )


# ---------------------------------------------------------------- content


def check_content(kind: str, content: dict[str, Any]) -> dict[str, Any]:
    """The platform's shape per kind; a pack may validate more (its skill model)."""
    if kind not in SKILL_KINDS:
        raise ValidationFailed(f"Unknown skill kind {kind!r}")
    if not isinstance(content, dict) or not content:
        raise ValidationFailed("A skill needs content")
    if kind == "hint":
        text = content.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
            raise ValidationFailed(f"A hint is one or two sentences (1-{MAX_TEXT} characters)")
        return {"text": " ".join(text.split())}
    if kind == "rule":
        if any(isinstance(v, dict | list) for v in content.values()):
            raise ValidationFailed("A rule is a flat set of settings")
        return content
    if kind == "field_map":
        if not isinstance(content.get("label"), str) or not isinstance(content.get("field"), str):
            raise ValidationFailed("A field map is a label and the field it fills")
        return {"label": content["label"], "field": content["field"]}
    if "input" not in content or "output" not in content:
        raise ValidationFailed("An example is an input and the output it should give")
    return content


def _texts(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [t for v in value.values() for t in _texts(v)]
    if isinstance(value, list):
        return [t for v in value for t in _texts(v)]
    return []


def _redact(value: Any, record_values: Any) -> Any:
    if isinstance(value, str):
        return scrub(value, record_values=record_values).redacted
    if isinstance(value, dict):
        return {k: _redact(v, record_values) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, record_values) for v in value]
    return value


def screen(content: dict[str, Any], record_values: Any = None) -> list[str]:
    """Why a skill's text can't be kept (empty when it's clean)."""
    reasons: set[str] = set()
    for text in _texts(content):
        result = scrub(text, record_values=record_values)
        if not result.clean:
            reasons.update(result.reasons)
    return sorted(reasons)


REASON_WORDS = {
    "record_value": "a value from the record",
    "email": "an email address",
    "phone": "a phone number",
    "iban": "a bank account (IBAN)",
    "card": "a card number",
    "us_ssn": "a social security number",
    "uk_ni": "a national insurance number",
    "long_digits": "a long number",
    "scrubber_error": "text the scrubber couldn't check",
}


# ---------------------------------------------------------------- who decides


async def _deciders(session: AsyncSession, ctx: Ctx, pack_key: str) -> None:
    from momentum.domain.pack_settings.service import is_steward

    if ctx.actor.is_admin or await is_steward(session, ctx.workspace_id, pack_key, ctx.actor.id):
        return
    raise Forbidden("Only workspace admins and the agent's stewards decide its skills")


def _member(ctx: Ctx) -> None:
    if ctx.actor.role == "guest":
        raise Forbidden("Guests can't see agents' skills")


async def get_skill(
    session: AsyncSession, ctx: Ctx, skill_id: uuid.UUID, *, lock: bool = False
) -> Skill:
    _member(ctx)
    s = await session.get(Skill, skill_id, with_for_update=lock or None)
    if s is None or s.workspace_id != ctx.workspace_id:
        raise NotFound("Skill not found")
    return s


async def list_skills(
    session: AsyncSession,
    ctx: Ctx,
    *,
    pack_key: str | None = None,
    status: str | None = None,
    scope_type: str | None = None,
    scope_id: uuid.UUID | None = None,
    limit: int = 200,
) -> list[Skill]:
    _member(ctx)
    stmt = select(Skill).where(Skill.workspace_id == ctx.workspace_id)
    if pack_key:
        stmt = stmt.where(Skill.pack_key == pack_key)
    if status:
        stmt = stmt.where(Skill.status == status)
    if scope_type:
        stmt = stmt.where(Skill.scope_type == scope_type)
    if scope_id:
        stmt = stmt.where(Skill.scope_id == scope_id)
    return list(
        (await session.execute(stmt.order_by(Skill.created_at.desc()).limit(limit))).scalars()
    )


# ---------------------------------------------------------------- propose / author


async def _new(
    session: AsyncSession,
    ctx: Ctx,
    *,
    pack_key: str,
    scope_type: str,
    scope_id: uuid.UUID | None,
    kind: str,
    field: str | None,
    content: dict[str, Any],
    status: str,
    source: str,
    provenance: dict[str, Any] | None = None,
    note: str | None = None,
    supersedes: Skill | None = None,
    starter_key: str | None = None,
) -> Skill:
    if scope_type not in SKILL_SCOPES:
        raise ValidationFailed(f"Unknown scope {scope_type!r}")
    if (scope_type == "workspace") != (scope_id is None):
        raise ValidationFailed("A workspace skill has no scope id; others need one")
    s = Skill(
        workspace_id=ctx.workspace_id,
        pack_key=pack_key,
        scope_type=scope_type,
        scope_id=scope_id,
        kind=kind,
        field=field,
        content=content,
        status=status,
        version=(supersedes.version + 1) if supersedes else 1,
        supersedes_id=supersedes.id if supersedes else None,
        source=source,
        starter_key=starter_key,
        provenance=provenance or {},
        metrics={"uses": 0, "helped": 0, "hurt": 0},
        proposed_by=None if ctx.actor.is_agent else ctx.actor.id,
        decided_by=ctx.actor.id
        if status in ("active", "rejected") and not ctx.actor.is_agent
        else None,
        decided_at=datetime.now(UTC) if status in ("active", "rejected") else None,
        decision_note=note,
    )
    session.add(s)
    await session.flush()
    await session.refresh(s, attribute_names=["created_at", "updated_at"])
    return s


async def _log(
    session: AsyncSession,
    ctx: Ctx,
    s: Skill,
    verb: str,
    undo: dict[str, Any] | None,
    changes: dict[str, tuple[Any, Any]] | None = None,
) -> None:
    act = await record_activity(
        session,
        ctx,
        entity_type="skill",
        entity_id=s.id,
        verb=verb,
        changes=changes or {"status": (None, s.status)},
        undo=undo,
    )
    await emit(
        session,
        ctx,
        type=verb,
        entity_type="skill",
        entity_id=s.id,
        data={"pack_key": s.pack_key, "status": s.status, "kind": s.kind},
        channels=[f"workspace:{ctx.workspace_id}"],
        activity_id=act.id,
    )


async def propose(
    session: AsyncSession,
    ctx: Ctx,
    *,
    pack_key: str,
    scope_type: str,
    scope_id: uuid.UUID | None,
    kind: str,
    content: dict[str, Any],
    field: str | None = None,
    provenance: dict[str, Any] | None = None,
    record_values: Any = None,
) -> Skill:
    """A learned skill, for review. Text with personal or record-specific values is refused:
    kept as ``rejected`` with the reason and only its redacted text."""
    clean = check_content(kind, content)
    reasons = screen(clean, record_values)
    if reasons:
        words = ", ".join(REASON_WORDS.get(r, r) for r in reasons)
        s = await _new(
            session,
            ctx,
            pack_key=pack_key,
            scope_type=scope_type,
            scope_id=scope_id,
            kind=kind,
            field=field,
            content=_redact(clean, record_values),
            status="rejected",
            source="learned",
            provenance=provenance,
            note=f"Refused automatically: it contains {words}",
        )
        await _log(session, ctx, s, "skill.rejected", None)
        return s
    s = await _new(
        session,
        ctx,
        pack_key=pack_key,
        scope_type=scope_type,
        scope_id=scope_id,
        kind=kind,
        field=field,
        content=clean,
        status="proposed",
        source="learned",
        provenance=provenance,
    )
    await _log(session, ctx, s, "skill.proposed", undo_op("skills.withdraw", skill_id=s.id))
    return s


async def author(
    session: AsyncSession,
    ctx: Ctx,
    *,
    pack_key: str,
    scope_type: str,
    scope_id: uuid.UUID | None,
    kind: str,
    content: dict[str, Any],
    field: str | None = None,
    note: str | None = None,
) -> Skill:
    """A skill a steward or admin writes: active at once (still scrubbed)."""
    await _deciders(session, ctx, pack_key)
    clean = check_content(kind, content)
    reasons = screen(clean)
    if reasons:
        raise ValidationFailed(
            "A skill can't contain "
            + ", ".join(REASON_WORDS.get(r, r) for r in reasons)
            + ": describe how to read the field, not the value",
            code="skill_unclean",
        )
    s = await _new(
        session,
        ctx,
        pack_key=pack_key,
        scope_type=scope_type,
        scope_id=scope_id,
        kind=kind,
        field=field,
        content=clean,
        status="active",
        source="authored",
        note=note,
    )
    await _log(session, ctx, s, "skill.approved", undo_op("skills.withdraw", skill_id=s.id))
    return s


# ---------------------------------------------------------------- decide


Decision = Literal["approve", "reject", "retire"]
_VERB = {"approve": "skill.approved", "reject": "skill.rejected", "retire": "skill.retired"}
_STATUS = {"approve": "active", "reject": "rejected", "retire": "retired"}
_FROM = {"approve": ("proposed",), "reject": ("proposed",), "retire": ("active",)}


async def decide(
    session: AsyncSession,
    ctx: Ctx,
    skill_id: uuid.UUID,
    decision: Decision,
    *,
    note: str | None = None,
    content: dict[str, Any] | None = None,
) -> Skill:
    """Approve (optionally with edited content: a new version supersedes the proposal), reject or
    retire a skill. Undoable."""
    s = await get_skill(session, ctx, skill_id, lock=True)
    await _deciders(session, ctx, s.pack_key)
    if s.status not in _FROM[decision]:
        raise Conflict(f"A {s.status} skill can't be {_STATUS[decision]}")
    now = datetime.now(UTC)
    if decision == "approve" and content is not None:
        clean = check_content(s.kind, content)
        reasons = screen(clean)
        if reasons:
            raise ValidationFailed(
                "A skill can't contain " + ", ".join(REASON_WORDS.get(r, r) for r in reasons),
                code="skill_unclean",
            )
        s.status, s.decided_by, s.decided_at = "retired", ctx.actor.id, now
        s.decision_note = "Edited before approval"
        new = await _new(
            session,
            ctx,
            pack_key=s.pack_key,
            scope_type=s.scope_type,
            scope_id=s.scope_id,
            kind=s.kind,
            field=s.field,
            content=clean,
            status="active",
            source=s.source,
            provenance=s.provenance,
            note=note,
            supersedes=s,
        )
        new.tryout = s.tryout
        await _log(
            session,
            ctx,
            new,
            "skill.approved",
            undo_op("skills.unedit", new_id=new.id, old_id=s.id),
        )
        return new
    before = s.status
    s.status = _STATUS[decision]
    s.decided_by, s.decided_at, s.decision_note = ctx.actor.id, now, note
    await _log(
        session,
        ctx,
        s,
        _VERB[decision],
        undo_op("skills.set_status", skill_id=s.id, status=before, expect=s.status),
        {"status": (before, s.status)},
    )
    return s


@undo_handler("skills.withdraw")
async def _undo_propose(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    s = await session.get(Skill, uuid.UUID(str(args["skill_id"])), with_for_update=True)
    if s is None or s.status not in ("proposed", "active") or (s.metrics or {}).get("uses"):
        raise UndoConflict("This skill was already decided or used")
    s.status, s.decision_note = "rejected", "Withdrawn"


@undo_handler("skills.set_status")
async def _undo_status(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    s = await session.get(Skill, uuid.UUID(str(args["skill_id"])), with_for_update=True)
    if s is None or s.status != args["expect"]:
        raise UndoConflict("This skill changed again since")
    s.status = str(args["status"])
    s.decided_by = s.decided_at = s.decision_note = None


@undo_handler("skills.unedit")
async def _undo_edit(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    new = await session.get(Skill, uuid.UUID(str(args["new_id"])), with_for_update=True)
    old = await session.get(Skill, uuid.UUID(str(args["old_id"])), with_for_update=True)
    if new is None or old is None or new.status != "active" or (new.metrics or {}).get("uses"):
        raise UndoConflict("The edited skill was already used or changed")
    new.status, new.decision_note = "rejected", "Undone"
    old.status, old.decided_by, old.decided_at, old.decision_note = "proposed", None, None, None


# ---------------------------------------------------------------- use and metrics


async def active_for(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    pack_key: str,
    *,
    entity_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    kinds: list[str] | None = None,
    field: str | None = None,
) -> list[Skill]:
    """Active skills for a job, most specific first: the entity's, the project's, the
    workspace's."""
    from sqlalchemy import and_, or_

    scopes = [Skill.scope_type == "workspace"]
    if entity_id is not None:
        scopes.append(and_(Skill.scope_type == "entity", Skill.scope_id == entity_id))
    if project_id is not None:
        scopes.append(and_(Skill.scope_type == "project", Skill.scope_id == project_id))
    stmt = select(Skill).where(
        Skill.workspace_id == workspace_id,
        Skill.pack_key == pack_key,
        Skill.status == "active",
        or_(*scopes),
    )
    if kinds:
        stmt = stmt.where(Skill.kind.in_(kinds))
    if field is not None:
        stmt = stmt.where(or_(Skill.field == field, Skill.field.is_(None)))
    rows = list((await session.execute(stmt)).scalars())
    return sorted(rows, key=lambda s: (SPECIFICITY[s.scope_type], s.created_at))


async def record_use(session: AsyncSession, skill_ids: list[uuid.UUID]) -> None:
    now = datetime.now(UTC).isoformat()
    for s in (await session.execute(select(Skill).where(Skill.id.in_(skill_ids)))).scalars():
        m = dict(s.metrics or {})
        m["uses"] = int(m.get("uses", 0)) + 1
        m["last_used_at"] = now
        s.metrics = m


async def score_outcome(
    session: AsyncSession, used: dict[str, list[str]], corrected: set[str]
) -> None:
    """A record that used skills was approved: a skill helped when its field wasn't corrected
    by a person, hurt when it was (``used``: skill id → the fields it was used for)."""
    for sid, fields in used.items():
        s = await session.get(Skill, uuid.UUID(sid))
        if s is None:
            continue
        m = dict(s.metrics or {})
        hurt = any(f.split(".")[0].split("[")[0] in corrected for f in fields or [s.field or ""])
        key = "hurt" if hurt else "helped"
        m[key] = int(m.get(key, 0)) + 1
        s.metrics = m


async def set_tryout(session: AsyncSession, skill_id: uuid.UUID, result: dict[str, Any]) -> None:
    s = await session.get(Skill, skill_id)
    if s is not None:
        s.tryout = {**result, "ran_at": datetime.now(UTC).isoformat()}


# ---------------------------------------------------------------- starters and the digest


async def install_starters(
    session: AsyncSession, ctx: Ctx, pack_key: str, starters: list[dict[str, Any]]
) -> int:
    """A pack's starter skills (``skills/*.yaml``) as active ``starter`` skills, once each."""
    n = 0
    for st in starters:
        key = str(st["key"])
        exists = await session.scalar(
            select(Skill.id).where(
                Skill.workspace_id == ctx.workspace_id,
                Skill.pack_key == pack_key,
                Skill.starter_key == key,
            )
        )
        if exists is not None:
            continue
        clean = check_content(str(st["kind"]), dict(st["content"]))
        if screen(clean):
            raise ValidationFailed(f"Starter skill {key} carries a personal or specific value")
        await _new(
            session,
            ctx,
            pack_key=pack_key,
            scope_type="workspace",
            scope_id=None,
            kind=str(st["kind"]),
            field=st.get("field"),
            content=clean,
            status="active",
            source="starter",
            starter_key=key,
        )
        n += 1
    return n


async def digest(session: AsyncSession, settings: Settings, now: datetime | None = None) -> int:
    """Once a day: per workspace and pack, one ``skill_proposed`` notification to each steward
    (or, without stewards, each admin) saying how many skills wait for review."""
    from momentum.core.context import Actor
    from momentum.domain.notifications.service import notify
    from momentum.domain.pack_settings.service import people
    from momentum.domain.users.models import User

    now = now or datetime.now(UTC)
    rows = (
        await session.execute(
            select(Skill.workspace_id, Skill.pack_key, Skill.id).where(
                Skill.status == "proposed", Skill.created_at >= now - timedelta(days=1)
            )
        )
    ).tuples()
    groups: dict[tuple[uuid.UUID, str], int] = {}
    for ws, pack, _id in rows:
        groups[(ws, pack)] = groups.get((ws, pack), 0) + 1
    sent = 0
    for (ws, pack), count in groups.items():
        to = await people(session, ws, pack, "stewards")
        if not to:
            to = list(
                (
                    await session.execute(
                        select(User.id).where(
                            User.workspace_id == ws, User.role == "admin", User.status == "active"
                        )
                    )
                ).scalars()
            )
        system = Ctx(actor=Actor(id=None, workspace_id=ws), settings=settings, via="system")
        for uid in to:
            await notify(
                session,
                system,
                user_id=uid,
                kind="skill_proposed",
                entity_type="pack",
                entity_id=uuid.uuid5(uuid.NAMESPACE_URL, f"momentum:pack:{pack}"),
                title=f"{count} skill(s) from {pack} to review"[:300],
            )
            sent += 1
    return sent
