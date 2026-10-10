"""Phase 7.6 S76-04 (spec §6): records.

- **Types** are registered from packs at install (``sync_types``): the JSON Schema snapshot,
  display spec and classification per key and version.
- **Create** (a job's ``records.create`` effect, or the API): validated against the type's model
  on every write; title, identity key, promoted amount/currency/date, entity ids and search text
  are derived from the type's display spec. Version 1 is written with it.
- **Update** only through correction operations (spec §6.4) with ``expected_version`` (stale →
  409): validate, re-run the type's deterministic checks, write a version, activity with undo
  (restores the previous version) and the outbox event, in one transaction.
- **Visibility** (spec §6.7): exactly the task's (or the project's, without a task); guests never
  see ``financial`` or ``personal`` records; editing needs editor; approving or rejecting needs a
  project admin, and never on a record you created yourself.
"""

from __future__ import annotations

import contextlib
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import ValidationError
from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import record_activity
from momentum.core.context import Ctx
from momentum.core.errors import Conflict, Forbidden, NotFound, ValidationFailed, VersionConflict
from momentum.core.events import emit
from momentum.core.undo import UndoConflict, undo_handler, undo_op
from momentum.domain.access import (
    get_visible_project,
    get_visible_task,
    require_project_role,
    visible_projects_clause,
)
from momentum.domain.projects.models import Project
from momentum.domain.records import paths
from momentum.domain.records.models import Record, RecordType, RecordVersion
from momentum.domain.records.schemas import (
    AddItemOp,
    DistributeOp,
    LinkEntityOp,
    MoveItemOp,
    RecordTypeImpl,
    RemoveItemOp,
    SetOp,
    SetStatusOp,
)

CLASSIFIED = ("financial", "personal")
CREATE_STATUSES = ("draft", "needs_review", "ready")
SENSITIVITY = {"public": 0, "internal": 1, "financial": 2, "personal": 3}
_ID_STRIP = re.compile(r"[^\w]+")
_LEADING_ZEROS = re.compile(r"(?<!\d)0+(?=\d)")


# ---------------------------------------------------------------- types


async def sync_types(
    session: AsyncSession, workspace_id: uuid.UUID, pack_key: str, impls: list[RecordTypeImpl]
) -> int:
    """Register (or refresh) a pack's record types for a workspace; returns how many changed."""
    changed = 0
    for impl in impls:
        row = await session.scalar(
            select(RecordType).where(
                RecordType.workspace_id == workspace_id,
                RecordType.key == impl.key,
                RecordType.version == impl.version,
            )
        )
        if row is not None and row.pack_key != pack_key:
            raise Conflict(f"Record type {impl.key} belongs to the {row.pack_key} pack")
        values = {
            "label": impl.label,
            "schema": impl.json_schema(),
            "display": impl.display(),
            "classification": impl.classification,
        }
        if row is None:
            session.add(
                RecordType(
                    workspace_id=workspace_id,
                    pack_key=pack_key,
                    key=impl.key,
                    version=impl.version,
                    **values,
                )
            )
            changed += 1
        elif any(getattr(row, k) != v for k, v in values.items()):
            for k, v in values.items():
                setattr(row, k, v)
            changed += 1
    await session.flush()
    return changed


async def type_row(
    session: AsyncSession, workspace_id: uuid.UUID, key: str, version: int | None = None
) -> RecordType | None:
    stmt = select(RecordType).where(RecordType.workspace_id == workspace_id, RecordType.key == key)
    if version is not None:
        stmt = stmt.where(RecordType.version == version)
    row: RecordType | None = await session.scalar(stmt.order_by(RecordType.version.desc()).limit(1))
    return row


async def classifications(session: AsyncSession, workspace_id: uuid.UUID) -> dict[str, str]:
    """Each type key's classification (the most sensitive of its versions)."""
    out: dict[str, str] = {}
    rows = await session.execute(
        select(RecordType.key, RecordType.classification).where(
            RecordType.workspace_id == workspace_id
        )
    )
    for key, cls in rows.tuples():
        if SENSITIVITY.get(cls, 1) >= SENSITIVITY.get(out.get(key, "public"), 0):
            out[key] = cls
    return out


# ---------------------------------------------------------------- derived values


def normalize_identity(value: Any) -> str:
    """``INV-0041`` → ``inv41``: case-folded, punctuation and leading zeros of numbers removed.
    Ids (entity ids) are kept as they are."""
    text = str(value).strip()
    try:
        return str(uuid.UUID(text))
    except ValueError:
        pass
    text = _ID_STRIP.sub("", text.casefold())
    return _LEADING_ZEROS.sub("", text)


def _money(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except InvalidOperation:
        return None


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def render_title(template: str, data: dict[str, Any], fallback: str) -> str:
    def one(m: re.Match[str]) -> str:
        try:
            v = paths.get(data, m.group(1))
        except ValidationFailed:
            v = None
        return "" if v is None else str(v)

    title = " ".join(re.sub(r"\{([a-z0-9_.\[\]]+)\}", one, template or "").split())
    return (title or fallback)[:300]


def _entity_ids(data: Any) -> list[uuid.UUID]:
    found: list[uuid.UUID] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "entity_id" and v:
                    with contextlib.suppress(ValueError):
                        found.append(uuid.UUID(str(v)))
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return list(dict.fromkeys(found))


def identity_of(display: dict[str, Any], data: dict[str, Any]) -> str | None:
    """The normalised identity key of some data under a type's display spec (spec §6.5)."""
    parts: list[str] = []
    for p in display.get("identity") or []:
        v = paths.get(data, p)
        if v in (None, ""):
            return None
        parts.append(normalize_identity(v))
    return "|".join(parts)[:300] or None


def derive(record: Record, display: dict[str, Any], label: str) -> None:
    """Title, identity key, promoted amount/currency/date, entity ids and search text, from the
    type's display spec."""
    data = record.data
    record.title = render_title(display.get("title") or "", data, label)
    record.identity_key = identity_of(display, data)
    amount_path = display.get("amount")
    record.amount = _money(paths.get(data, amount_path)) if amount_path else None
    cur = display.get("currency_field")
    currency = paths.get(data, cur) if cur else None
    record.currency = str(currency).upper()[:3] if currency else None
    date_path = display.get("occurred_on")
    record.occurred_on = _date(paths.get(data, date_path)) if date_path else None
    record.entity_ids = _entity_ids(data)
    words: list[str] = [record.title]
    for p in display.get("search") or []:
        words += [str(v) for v in paths.get_all(data, p) if isinstance(v, str | int | float)]
    record.search_text = " ".join(words)[:20_000]


def _validate(impl: RecordTypeImpl, data: dict[str, Any]) -> dict[str, Any]:
    try:
        return impl.validate(data)
    except ValidationError as e:
        problems = "; ".join(
            f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()[:8]
        )
        raise ValidationFailed(f"The {impl.label} isn't valid: {problems}") from e
    except (ValueError, TypeError) as e:
        raise ValidationFailed(f"The {impl.label} isn't valid: {e}") from e


# ---------------------------------------------------------------- visibility


async def _require_visible(
    session: AsyncSession, ctx: Ctx, record: Record, cls: str | None = None
) -> str:
    """The viewer's role on the record (its task's, or its project's); ``NotFound`` otherwise."""
    if ctx.actor.role == "guest":
        cls = cls or (await classifications(session, record.workspace_id)).get(record.type)
        if cls in CLASSIFIED:
            raise NotFound("Record not found")
    if record.task_id is not None:
        _task, _placement, role = await get_visible_task(session, ctx, record.task_id)
        return role
    _project, role = await get_visible_project(session, ctx, record.project_id)
    return role


async def viewer_role(session: AsyncSession, ctx: Ctx, record: Record) -> str:
    """S76-07/08: the viewer's role on a record they can see (``NotFound`` otherwise)."""
    return await _require_visible(session, ctx, record)


def can_decide(ctx: Ctx, record: Record, role: str) -> tuple[bool, str | None]:
    """Whether this viewer may approve or reject the record (spec §6.7), and why not."""
    if record.status in ("void", "superseded", "approved", "rejected"):
        return False, f"This record is {record.status}"
    if role != "admin" and not ctx.actor.is_admin:
        return False, "Approving or rejecting a record needs a project admin"
    if record.created_by == ctx.actor.id and record.created_via != "agent":
        return False, "You can't approve a record you made yourself"
    return True, None


async def type_counts(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID | None
) -> dict[str, int]:
    """How many records of each type the viewer can see (in one project, or anywhere)."""
    stmt = select(Record.type, func.count()).where(await visible(session, ctx))
    if project_id is not None:
        stmt = stmt.where(Record.project_id == project_id)
    rows = await session.execute(stmt.group_by(Record.type))
    return {t: int(n) for t, n in rows.all()}


def visible_clause(ctx: Ctx, classified_types: list[str]) -> ColumnElement[bool]:
    """Records in projects the viewer can see; a guest never gets classified types."""
    clause = and_(
        Record.workspace_id == ctx.workspace_id,
        Record.deleted_at.is_(None),
        Record.project_id.in_(select(Project.id).where(visible_projects_clause(ctx))),
    )
    if ctx.actor.role == "guest" and classified_types:
        clause = and_(clause, Record.type.not_in(classified_types))
    return clause


async def visible(session: AsyncSession, ctx: Ctx) -> ColumnElement[bool]:
    cls = await classifications(session, ctx.workspace_id)
    return visible_clause(ctx, [k for k, v in cls.items() if v in CLASSIFIED])


async def get_record(session: AsyncSession, ctx: Ctx, record_id: uuid.UUID) -> Record:
    record = await session.get(Record, record_id)
    if record is None or record.workspace_id != ctx.workspace_id or record.deleted_at is not None:
        raise NotFound("Record not found")
    await _require_visible(session, ctx, record)
    return record


async def list_records(
    session: AsyncSession,
    ctx: Ctx,
    *,
    type: str | None = None,
    project_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    status: list[str] | None = None,
    entity_id: uuid.UUID | None = None,
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Record], int]:
    stmt = select(Record).where(await visible(session, ctx))
    if type:
        stmt = stmt.where(Record.type == type)
    if project_id:
        stmt = stmt.where(Record.project_id == project_id)
    if task_id:
        stmt = stmt.where(Record.task_id == task_id)
    if status:
        stmt = stmt.where(Record.status.in_(status))
    if entity_id:
        stmt = stmt.where(Record.entity_ids.contains([entity_id]))
    if q:
        stmt = stmt.where(
            or_(
                Record.search.op("@@")(func.plainto_tsquery("simple", q)),
                func.lower(Record.title).contains(q.lower(), autoescape=True),
            )
        )
    if date_from:
        stmt = stmt.where(Record.occurred_on >= date_from)
    if date_to:
        stmt = stmt.where(Record.occurred_on <= date_to)
    total = int(await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = await session.execute(
        stmt.order_by(Record.created_at.desc(), Record.id.desc()).offset(offset).limit(limit)
    )
    return list(rows.scalars()), total


# ---------------------------------------------------------------- create


def _event_channels(record: Record) -> list[str]:
    out = [f"project:{record.project_id}"]
    if record.task_id:
        out.append(f"task:{record.task_id}")
    return out


async def create_record(
    session: AsyncSession,
    ctx: Ctx,
    impl: RecordTypeImpl,
    *,
    project_id: uuid.UUID,
    data: dict[str, Any],
    task_id: uuid.UUID | None = None,
    provenance: dict[str, Any] | None = None,
    checks: list[dict[str, Any]] | None = None,
    decision: dict[str, Any] | None = None,
    confidence: float | Decimal | None = None,
    status: str = "draft",
    source_attachment_id: uuid.UUID | None = None,
    source_sha256: str | None = None,
    source_locator: str | None = None,
    run_id: uuid.UUID | None = None,
) -> Record:
    _project, role = await get_visible_project(session, ctx, project_id)
    if task_id is not None:
        _task, _placement, role = await get_visible_task(session, ctx, task_id)
    require_project_role(role, "editor", "create records")
    if status not in CREATE_STATUSES:
        raise ValidationFailed(f"A new record starts as {', '.join(CREATE_STATUSES)}")
    row = await type_row(session, ctx.workspace_id, impl.key, impl.version)
    if row is None:
        raise ValidationFailed(f"Record type {impl.key} v{impl.version} isn't installed")
    clean = _validate(impl, data)
    if checks is None:
        checks = impl.recheck(clean) or []
    record = Record(
        workspace_id=ctx.workspace_id,
        type=impl.key,
        type_version=impl.version,
        project_id=project_id,
        task_id=task_id,
        source_attachment_id=source_attachment_id,
        source_sha256=source_sha256,
        source_locator=source_locator,
        run_id=run_id,
        created_by=ctx.actor.id,
        created_via=ctx.via,
        status=status,
        data=clean,
        provenance=provenance or {},
        checks=checks,
        decision=decision,
        confidence=Decimal(str(confidence)) if confidence is not None else None,
        version=1,
    )
    derive(record, row.display, row.label)
    session.add(record)
    await session.flush()
    await _write_version(session, ctx, record, via=_via(ctx), change={"created": True})
    act = await record_activity(
        session,
        ctx,
        entity_type="record",
        entity_id=record.id,
        verb="record.created",
        changes={"title": (None, record.title), "status": (None, status)},
        undo=undo_op("records.remove", record_id=record.id, version=1),
    )
    await emit(
        session,
        ctx,
        type="record.created",
        entity_type="record",
        entity_id=record.id,
        data={"type": record.type, "task_id": str(task_id) if task_id else None, "version": 1},
        channels=_event_channels(record),
        activity_id=act.id,
    )
    await session.refresh(record, attribute_names=["created_at", "updated_at"])
    return record


def _via(ctx: Ctx) -> str:
    return "agent" if ctx.actor.is_agent else "api" if ctx.via == "api" else "review"


async def _write_version(
    session: AsyncSession,
    ctx: Ctx,
    record: Record,
    *,
    via: str,
    change: dict[str, Any],
    reason: str | None = None,
) -> None:
    session.add(
        RecordVersion(
            workspace_id=record.workspace_id,
            record_id=record.id,
            version=record.version,
            data=record.data,
            provenance=record.provenance,
            checks=record.checks,
            status=record.status,
            changed_by=ctx.actor.id,
            via=via,
            change=change,
            reason=reason,
        )
    )
    await session.flush()


@undo_handler("records.remove")
async def _undo_create(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    record = await session.get(Record, uuid.UUID(str(args["record_id"])), with_for_update=True)
    if record is None or record.deleted_at is not None:
        raise UndoConflict("This record is already gone")
    if record.version != int(args["version"]):
        raise UndoConflict("This record changed after it was made; undo those changes first")
    record.deleted_at = datetime.now(UTC)
    await emit(
        session,
        ctx,
        type="record.deleted",
        entity_type="record",
        entity_id=record.id,
        data={"type": record.type},
        channels=_event_channels(record),
    )


# ---------------------------------------------------------------- correction operations


def _decimal(value: Any, what: str) -> Decimal:
    d = _money(value)
    if d is None:
        raise ValidationFailed(f"{what}: expected a number")
    return d


def distribute(total: Decimal, n: int, places: int = 2) -> list[Decimal]:
    """``total`` split evenly over ``n`` items, rounded half-up; the remainder lands on the last."""
    if n < 1:
        raise ValidationFailed("There are no items to distribute over")
    quantum = Decimal(1).scaleb(-places)
    each = (total / n).quantize(quantum, rounding=ROUND_HALF_UP)
    parts = [each] * (n - 1)
    return [*parts, (total - sum(parts, Decimal(0))).quantize(quantum, rounding=ROUND_HALF_UP)]


def apply_ops(
    data: dict[str, Any],
    provenance: dict[str, Any],
    ops: list[Any],
    *,
    actor_id: uuid.UUID | None,
) -> tuple[dict[str, Any], dict[str, Any], SetStatusOp | None, list[str]]:
    """Apply correction operations to copies of the data and provenance. Returns them, the last
    status change (checked by the caller) and the top-level fields touched."""
    data, provenance = paths.clone(data), paths.clone(provenance)
    status: SetStatusOp | None = None
    touched: list[str] = []
    human = {"method": "human", "by": str(actor_id) if actor_id else None}
    for op in ops:
        if isinstance(op, SetOp):
            paths.set_(data, op.path, op.value)
            provenance[op.path] = human
            touched.append(op.path)
        elif isinstance(op, AddItemOp):
            items = paths.array(data, op.array)
            at = len(items) if op.at is None else min(op.at, len(items))
            items.insert(at, op.item)
            touched.append(op.array)
        elif isinstance(op, RemoveItemOp):
            items = paths.array(data, op.array)
            if op.index >= len(items):
                raise ValidationFailed(f"{op.array} has no item {op.index}")
            items.pop(op.index)
            touched.append(op.array)
        elif isinstance(op, MoveItemOp):
            items = paths.array(data, op.array)
            if op.from_ >= len(items) or op.to >= len(items):
                raise ValidationFailed(f"{op.array} has {len(items)} items")
            items.insert(op.to, items.pop(op.from_))
            touched.append(op.array)
        elif isinstance(op, DistributeOp):
            items = paths.array(data, op.array)
            for i, value in enumerate(distribute(_decimal(op.total, "total"), len(items))):
                if not isinstance(items[i], dict):
                    raise ValidationFailed(f"{op.array} items aren't objects")
                items[i][op.field] = str(value)
                provenance[f"{op.array}[{i}].{op.field}"] = {
                    "method": "rule",
                    "rule": "distribute",
                    "by": human["by"],
                }
            touched.append(op.array)
        elif isinstance(op, LinkEntityOp):
            current = data.get(op.role)
            data[op.role] = {
                **(current if isinstance(current, dict) else {}),
                "entity_id": str(op.entity_id),
            }
            provenance[f"{op.role}.entity_id"] = human
            touched.append(op.role)
        elif isinstance(op, SetStatusOp):
            status = op
    return data, provenance, status, [t.split(".")[0].split("[")[0] for t in touched]


async def _check_authority(
    session: AsyncSession,
    ctx: Ctx,
    record: Record,
    status: str,
    authority: str,
    approval_task_id: uuid.UUID | None,
    decision: dict[str, Any] | None,
    *,
    ask_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
) -> None:
    from momentum.domain.asks.models import Ask
    from momentum.domain.tasks.models import Task
    from momentum.domain.users.models import User

    if not ctx.actor.is_agent:
        raise Forbidden("Only an agent acts on an approval or a policy decision")
    if authority == "ask":
        ask = await session.get(Ask, ask_id) if ask_id else None
        who = await session.get(User, ask.answered_by) if ask and ask.answered_by else None
        if (
            status != "rejected"
            or ask is None
            or ask.workspace_id != ctx.workspace_id
            or ask.run_id != run_id
            or ask.task_id != record.task_id
            or ask.status != "answered"
            or who is None
            or who.is_agent
        ):
            raise Forbidden("No person's answer lets this record be rejected")
        return
    if authority == "policy":
        current = decision if decision is not None else record.decision or {}
        if status != "approved" or current.get("decision") != "allow":
            raise Forbidden("The policy didn't allow approving this record")
        return
    task = await session.get(Task, approval_task_id) if approval_task_id else None
    if (
        task is None
        or task.workspace_id != ctx.workspace_id
        or task.type != "approval"
        or task.parent_id is None
        or task.parent_id != record.task_id
        or task.approval_state in (None, "pending")
    ):
        raise Forbidden("No decided approval for this record")
    if status != ("approved" if task.approval_state == "approved" else "rejected"):
        raise Forbidden("The status doesn't match the approval's decision")


async def update_record(
    session: AsyncSession,
    ctx: Ctx,
    impl: RecordTypeImpl,
    record_id: uuid.UUID,
    ops: list[Any],
    *,
    expected_version: int,
    reason: str | None = None,
    checks: list[dict[str, Any]] | None = None,
    decision: dict[str, Any] | None = None,
    confidence: float | Decimal | None = None,
    batch_id: uuid.UUID | None = None,
    authority: Literal["policy", "approval", "ask"] | None = None,
    approval_task_id: uuid.UUID | None = None,
    ask_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
) -> Record:
    """Correction operations (people and agents); an agent may also replace the checks, the
    decision and the confidence in the same version (``ops`` may then be empty).

    An agent sets ``approved`` / ``rejected`` only with an ``authority`` (S76-10): ``approval``,
    when a person decided the approval subtask of the record's task (``approved`` → approved,
    anything else → rejected), ``policy``, when the record's policy decision is ``allow``
    (approve only), or ``ask``, when a person answered this agent run's ask on the record's task
    (reject only). Without one, approving still needs a project admin."""
    record = await session.get(Record, record_id, with_for_update=True)
    if record is None or record.workspace_id != ctx.workspace_id or record.deleted_at is not None:
        raise NotFound("Record not found")
    role = await _require_visible(session, ctx, record)
    require_project_role(role, "editor", "change records")
    if record.version != expected_version:
        raise VersionConflict("This record was changed by someone else", version=record.version)
    if record.status in ("void", "superseded"):
        raise Conflict(f"This record is {record.status}; it can't be changed")
    if (impl.key, impl.version) != (record.type, record.type_version):
        raise ValidationFailed("The record's type doesn't match")
    data, provenance, status_op, touched = apply_ops(
        record.data, record.provenance, ops, actor_id=ctx.actor.id
    )
    new_status = record.status
    if status_op is not None:
        if status_op.status in ("approved", "rejected") and authority is not None:
            await _check_authority(
                session,
                ctx,
                record,
                status_op.status,
                authority,
                approval_task_id,
                decision,
                ask_id=ask_id,
                run_id=run_id,
            )
        elif status_op.status in ("approved", "rejected"):
            if role != "admin" and not ctx.actor.is_admin:
                raise Forbidden("Approving or rejecting a record needs a project admin")
            if record.created_by == ctx.actor.id and record.created_via not in ("agent",):
                raise Forbidden("You can't approve a record you made yourself")
        new_status = status_op.status
    clean = _validate(impl, data)
    before = {"version": record.version, "status": record.status}
    record.data, record.provenance = clean, provenance
    record.checks = checks if checks is not None else impl.recheck(clean) or record.checks
    if decision is not None:
        record.decision = decision
    if confidence is not None:
        record.confidence = Decimal(str(confidence))
    record.status = new_status
    record.version += 1
    row = await type_row(session, ctx.workspace_id, record.type, record.type_version)
    derive(record, row.display if row else {}, row.label if row else record.type)
    change = {
        "ops": [op.model_dump(mode="json", by_alias=True) for op in ops],
        "fields": sorted(set(touched)),
    }
    await _write_version(session, ctx, record, via=_via(ctx), change=change, reason=reason)
    if new_status == "approved" and before["status"] != "approved":
        await _score_skills(session, record)
    act = await record_activity(
        session,
        ctx,
        entity_type="record",
        entity_id=record.id,
        verb="record.updated",
        changes={
            "version": (before["version"], record.version),
            **({"status": (before["status"], record.status)} if status_op else {}),
        },
        undo=undo_op(
            "records.restore_version",
            record_id=record.id,
            version=before["version"],
            expect=record.version,
        ),
        batch_id=batch_id,
    )
    await emit(
        session,
        ctx,
        type="record.updated",
        entity_type="record",
        entity_id=record.id,
        data={"type": record.type, "version": record.version, "status": record.status},
        channels=_event_channels(record),
        activity_id=act.id,
    )
    await session.refresh(record, attribute_names=["created_at", "updated_at"])
    return record


async def _score_skills(session: AsyncSession, record: Record) -> None:
    """S76-05 (spec §7.2): approved, so the skills it used are scored once: helped when a person
    didn't correct their field, hurt when they did. A pack lists what it used under
    ``provenance["skills_used"]`` (skill id → fields)."""
    from momentum.domain.skills.service import score_outcome

    used = (record.provenance or {}).get("skills_used") or {}
    if not used or (record.provenance or {}).get("skills_scored"):
        return
    rows = await session.execute(
        select(RecordVersion.change).where(
            RecordVersion.record_id == record.id, RecordVersion.via.in_(("review", "api"))
        )
    )
    corrected = {f for change in rows.scalars() for f in (change or {}).get("fields") or []}
    await score_outcome(session, used, corrected)
    record.provenance = {**(record.provenance or {}), "skills_scored": True}


@undo_handler("records.restore_version")
async def _undo_update(session: AsyncSession, ctx: Ctx, args: dict[str, Any]) -> None:
    record = await session.get(Record, uuid.UUID(str(args["record_id"])), with_for_update=True)
    if record is None or record.deleted_at is not None:
        raise UndoConflict("This record is gone")
    if record.version != int(args["expect"]):
        raise UndoConflict("This record changed after your edit")
    old = await session.scalar(
        select(RecordVersion).where(
            RecordVersion.record_id == record.id, RecordVersion.version == int(args["version"])
        )
    )
    if old is None:
        raise UndoConflict("That version is no longer kept")
    record.data, record.provenance, record.checks = old.data, old.provenance, old.checks
    record.status = old.status
    record.version += 1
    row = await type_row(session, record.workspace_id, record.type, record.type_version)
    derive(record, row.display if row else {}, row.label if row else record.type)
    await _write_version(
        session, ctx, record, via="undo", change={"restored": int(args["version"])}
    )
    await emit(
        session,
        ctx,
        type="record.updated",
        entity_type="record",
        entity_id=record.id,
        data={"type": record.type, "version": record.version, "status": record.status},
        channels=_event_channels(record),
    )


# ---------------------------------------------------------------- duplicates


async def find_duplicates(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    type: str,
    identity_key: str | None,
    *,
    exclude: uuid.UUID | None = None,
) -> list[Record]:
    """Live records of the type with the same identity key (spec §6.5)."""
    if not identity_key:
        return []
    stmt = select(Record).where(
        Record.workspace_id == workspace_id,
        Record.type == type,
        Record.identity_key == identity_key,
        Record.deleted_at.is_(None),
        Record.status.not_in(("void", "superseded")),
    )
    if exclude is not None:
        stmt = stmt.where(Record.id != exclude)
    return list((await session.execute(stmt.order_by(Record.created_at))).scalars())


async def find_similar(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    type: str,
    identity_key: str | None,
    *,
    amount: Decimal | None = None,
    occurred_on: date | None = None,
    window_days: int = 30,
    min_similarity: float = 0.5,
    exclude: uuid.UUID | None = None,
    limit: int = 10,
) -> list[tuple[Record, float]]:
    """Near-duplicates: a similar identity key (trigram) and, when given, the same amount within
    ``window_days`` of the date."""
    if not identity_key:
        return []
    score = func.similarity(Record.identity_key, identity_key)
    stmt = select(Record, score).where(
        Record.workspace_id == workspace_id,
        Record.type == type,
        Record.identity_key.is_not(None),
        Record.deleted_at.is_(None),
        Record.status.not_in(("void", "superseded")),
        score >= min_similarity,
    )
    if exclude is not None:
        stmt = stmt.where(Record.id != exclude)
    if amount is not None:
        stmt = stmt.where(Record.amount == amount)
    if occurred_on is not None:
        stmt = stmt.where(
            Record.occurred_on.between(
                occurred_on - timedelta(days=window_days), occurred_on + timedelta(days=window_days)
            )
        )
    rows = await session.execute(stmt.order_by(score.desc()).limit(limit))
    return [(r, float(s)) for r, s in rows.tuples()]
