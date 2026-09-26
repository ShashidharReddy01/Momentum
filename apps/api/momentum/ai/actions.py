"""AI actions: the preview → confirm → apply → undo lifecycle (ai-architecture §4, S3.1.3).

``propose`` dry-runs a list of write-tool calls through the tool registry and stores what each
would change (``ai_actions`` row, state ``proposed``). Nothing else is written. ``apply`` runs
them for real, all under one activity batch, after checking that:

- the action is still ``proposed``, belongs to the caller, and hasn't expired (24 h);
- a ``high``-risk action was explicitly confirmed (the confirm dialog);
- nothing it touches changed since the preview (**stale check**: every existing entity's
  ``version`` must match). If something did change, the operations are **re-previewed** against
  the current data and returned for a fresh decision instead of being applied blind.

If any operation fails while applying, all of them are rolled back and the action becomes
``failed`` with the error. Undo reverses the whole batch (``core.undo``) and marks it ``undone``.

Permissions are the approver's: operations run as ``ctx.actor`` (who must be ``proposed_for``),
through the same services the UI uses. An action is bookkeeping about a change, not a change,
so proposing/rejecting/expiring one records no ``activity`` row; the applied operations do,
each tagged with ``ai_action_id``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai.models import AiAction
from momentum.ai.tools.base import RISK_RANK
from momentum.ai.tools.registry import ToolOutcome, ToolRegistry, rollback_savepoint
from momentum.core.activity import Activity
from momentum.core.context import Ctx
from momentum.core.errors import Conflict, NotFound, ValidationFailed
from momentum.core.undo import undo
from momentum.domain.projects.models import Project
from momentum.domain.tasks.models import Task

ACTION_TTL = timedelta(hours=24)
MAX_OPERATIONS = 20
Source = Literal["chat", "command", "inline", "agent", "rule"]
ApplyOutcome = Literal["applied", "repreviewed", "failed"]
_VERSIONED: dict[str, Any] = {"task": Task, "project": Project}


@dataclass(frozen=True)
class ProposedCall:
    tool: str
    args: dict[str, Any]


@dataclass
class Proposal:
    """``action`` when every call previewed cleanly; otherwise ``failures`` (tool name + outcome)
    for the caller to show or feed back to the model, and no action is stored."""

    action: AiAction | None
    failures: list[tuple[str, ToolOutcome]]


@dataclass
class ApplyResult:
    action: AiAction
    outcome: ApplyOutcome


# ---------------- propose ----------------


async def _preview(
    session: AsyncSession, ctx: Ctx, registry: ToolRegistry, calls: list[ProposedCall]
) -> tuple[list[dict[str, Any]], list[tuple[str, ToolOutcome]]]:
    ops: list[dict[str, Any]] = []
    failures: list[tuple[str, ToolOutcome]] = []
    for call in calls:
        tool = registry.get(call.tool)
        if tool is not None and not tool.spec.writes:
            raise ValidationFailed(f"{call.tool} is a read tool; only changes are proposed")
        out = await registry.invoke(session, ctx, call.tool, call.args, mode="dry_run")
        if not out.ok:
            failures.append((call.tool, out))
            continue
        ops.append(
            {
                "tool": call.tool,
                "args": call.args,
                "summary": out.result.summary,
                "risk": out.risk,
                "diff": [d.to_json() for d in out.diff],
                "watch": await _watch(session, out),
            }
        )
    return ops, failures


async def _watch(session: AsyncSession, out: ToolOutcome) -> list[dict[str, Any]]:
    """Existing entities the operation changes, with their version now (the preview is rolled
    back, so this is the version the user is looking at)."""
    ids: dict[str, set[uuid.UUID]] = {k: set() for k in _VERSIONED}
    for t in out.result.targets:
        if t.get("type") in ids and t.get("id"):
            ids[t["type"]].add(uuid.UUID(t["id"]))
    for d in out.diff:
        if d.entity_type in ids and not d.verb.endswith(".created"):
            ids[d.entity_type].add(uuid.UUID(d.entity_id))
    return [
        {"type": kind, "id": str(i), "version": v}
        for kind, model in _VERSIONED.items()
        if ids[kind]
        for i, v in (
            await session.execute(select(model.id, model.version).where(model.id.in_(ids[kind])))
        ).all()
    ]


def _max_risk(ops: list[dict[str, Any]]) -> str:
    return max((op["risk"] for op in ops), key=lambda r: RISK_RANK[r], default="low")


def _summary(ops: list[dict[str, Any]]) -> str:
    if len(ops) == 1:
        return str(ops[0]["summary"])
    return (
        f"{len(ops)} changes: "
        + "; ".join(str(op["summary"]) for op in ops[:3])
        + ("; …" if len(ops) > 3 else "")
    )


async def propose(
    session: AsyncSession,
    ctx: Ctx,
    registry: ToolRegistry,
    calls: list[ProposedCall],
    *,
    source: Source,
    source_id: uuid.UUID | None = None,
    summary: str | None = None,
) -> Proposal:
    """Preview ``calls`` for ``ctx.actor`` and store them as one proposed action.

    Each call is previewed on its own against the current data: a later call can't see what an
    earlier one would create (a model refers to existing things by key; it creates new ones in
    one call, e.g. ``create_subtasks``)."""
    if not calls:
        raise ValidationFailed("Nothing to propose")
    if len(calls) > MAX_OPERATIONS:
        raise ValidationFailed(f"At most {MAX_OPERATIONS} operations in one action")
    if ctx.actor.id is None:
        raise ValidationFailed("AI actions are proposed for a person")
    ops, failures = await _preview(session, ctx, registry, calls)
    if failures:
        return Proposal(None, failures)
    action = AiAction(
        workspace_id=ctx.workspace_id,
        source=source,
        source_id=source_id,
        proposed_for=ctx.actor.id,
        summary=(summary or _summary(ops))[:500],
        operations=ops,
        risk=_max_risk(ops),
        state="proposed",
        expires_at=datetime.now(UTC) + ACTION_TTL,
    )
    session.add(action)
    await session.flush()
    return Proposal(action, [])


# ---------------- read / decide ----------------


async def get_action(
    session: AsyncSession, ctx: Ctx, action_id: uuid.UUID, *, for_update: bool = False
) -> AiAction:
    """An action proposed for the caller. Anyone else's reads as not found."""
    stmt = select(AiAction).where(
        AiAction.id == action_id,
        AiAction.workspace_id == ctx.workspace_id,
        AiAction.proposed_for == ctx.actor.id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    action = (await session.execute(stmt)).scalar_one_or_none()
    if action is None:
        raise NotFound("Action not found")
    if action.state == "proposed" and action.expires_at <= datetime.now(UTC):
        action.state = "expired"
        await session.flush()
    return action


def _require_proposed(action: AiAction) -> None:
    if action.state == "expired":
        raise Conflict("This suggestion expired; ask again", code="action_expired")
    if action.state != "proposed":
        raise Conflict(f"This suggestion was already {action.state}", code="action_not_pending")


async def _stale(session: AsyncSession, action: AiAction) -> bool:
    for op in action.operations:
        for w in op.get("watch") or []:
            model = _VERSIONED.get(w["type"])
            if model is None:
                continue
            row = (
                await session.execute(
                    select(model.version, model.deleted_at).where(model.id == uuid.UUID(w["id"]))
                )
            ).first()
            if row is None or row[1] is not None or int(row[0]) != int(w["version"]):
                return True
    return False


async def apply_action(
    session: AsyncSession,
    ctx: Ctx,
    registry: ToolRegistry,
    action_id: uuid.UUID,
    *,
    confirmed: bool = False,
) -> ApplyResult:
    action = await get_action(session, ctx, action_id, for_update=True)
    _require_proposed(action)
    if action.risk == "high" and not confirmed:
        raise Conflict(
            "This change is high risk and needs explicit confirmation",
            code="confirmation_required",
        )
    calls = [ProposedCall(op["tool"], op["args"]) for op in action.operations]
    if await _stale(session, action):
        ops, failures = await _preview(session, ctx, registry, calls)
        if failures:
            action.state = "failed"
            action.error = "; ".join(f"{name}: {out.result.summary}" for name, out in failures)[
                :2000
            ]
        else:
            action.operations = ops
            action.risk = _max_risk(ops)
            action.summary = _summary(ops)[:500]
        await session.flush()
        return ApplyResult(action, "repreviewed" if not failures else "failed")

    batch_id = uuid.uuid4()
    held = list(session.identity_map.values())
    savepoint = await session.begin_nested()
    error: str | None = None
    for call in calls:
        out = await registry.invoke(
            session, ctx, call.tool, call.args, mode="apply", batch_id=batch_id
        )
        if not out.ok:
            error = f"{call.tool}: {out.result.summary}"
            break
    now = datetime.now(UTC)
    if error is not None:
        await rollback_savepoint(session, savepoint, held)
        action.state, action.error = "failed", error[:2000]
    else:
        await session.execute(
            update(Activity).where(Activity.batch_id == batch_id).values(ai_action_id=action.id)
        )
        await savepoint.commit()
        action.state, action.applied_batch_id = "applied", batch_id
    action.decided_by, action.decided_at = ctx.actor.id, now
    await session.flush()
    return ApplyResult(action, "failed" if error else "applied")


async def reject_action(session: AsyncSession, ctx: Ctx, action_id: uuid.UUID) -> AiAction:
    action = await get_action(session, ctx, action_id, for_update=True)
    _require_proposed(action)
    action.state = "rejected"
    action.decided_by, action.decided_at = ctx.actor.id, datetime.now(UTC)
    await session.flush()
    return action


async def undo_action(session: AsyncSession, ctx: Ctx, action_id: uuid.UUID) -> AiAction:
    """Reverse an applied action (the whole batch, newest first) within the undo window."""
    action = await get_action(session, ctx, action_id, for_update=True)
    if action.state != "applied" or action.applied_batch_id is None:
        raise Conflict("Only an applied suggestion can be undone", code="action_not_applied")
    await undo(session, ctx, batch_id=action.applied_batch_id)
    action.state = "undone"
    await session.flush()
    return action


async def expire_actions(session: AsyncSession, now: datetime | None = None) -> int:
    """Mark overdue proposals expired (the periodic job; reads also expire lazily)."""
    result = await session.execute(
        update(AiAction)
        .where(AiAction.state == "proposed", AiAction.expires_at <= (now or datetime.now(UTC)))
        .values(state="expired")
        .returning(AiAction.id)
    )
    return len(result.all())
