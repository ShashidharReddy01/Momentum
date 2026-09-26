"""The tool registry: schema export and invocation in dry-run or apply mode (ai-architecture §3).

**How a write tool is previewed.** The registry opens a SAVEPOINT, runs the tool (which calls the
real domain services with ``ctx.dry_run`` set, so no outbox event or NOTIFY leaves the savepoint),
reads back the activity rows those services recorded, turns them into diff rows, and rolls the
savepoint back. The preview is therefore produced by exactly the code that will apply the change:
same validation, same permission checks, same side effects on related rows, nothing re-derived.
Apply mode runs the same way and releases the savepoint instead; the caller's unit of work
commits. A tool that fails part-way is rolled back entirely in both modes (one tool call, one
all-or-nothing change), and the failure comes back as a ``ToolResult`` the model can act on.

**Batches.** Every invocation gets its own ``request_id``. After a write tool runs, every activity
row carrying that request id is stamped with the invocation's ``batch_id`` (services that take a
``batch_id`` argument already set it), so ``POST /undo {batch_id}`` reverses the whole tool call,
and S3.1.3 can share one batch across the operations of an AI action.

**Trust.** The model is never the security boundary (§8): services enforce permissions for
``ctx.actor``; the registry adds argument validation, optional scope checks (for MCP/agent tokens),
and risk escalation for bulk targets. Everything written through the registry is marked
``via="ai"`` unless the caller is already an agent or MCP client.
"""

from __future__ import annotations

import contextlib
import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, cast

from pydantic import ValidationError
from sqlalchemy import inspect, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstanceState

from momentum.ai.llm import LLM
from momentum.ai.tools.base import RISK_RANK, Mode, Risk, Tool, ToolContext, ToolError, ToolResult
from momentum.ai.tools.schema import tool_schema
from momentum.ai.types import ToolSchema
from momentum.core.activity import Activity
from momentum.core.context import Ctx
from momentum.core.errors import DomainError
from momentum.core.ids import task_key
from momentum.domain.comments.models import Comment
from momentum.domain.projects.models import Project
from momentum.domain.sections.models import Section
from momentum.domain.tasks.models import Task
from momentum.domain.teams.models import Team
from momentum.domain.users.models import User

AI_VIAS = ("ai", "agent", "mcp")
HIDDEN_FIELDS = {"position", "parent_position"}  # ordering keys: meaningless to a reader


@dataclass
class DiffRow:
    """One recorded change, as the preview card (S3.1.3) and the model see it.

    ``changes`` is the raw ``{field: [old, new]}`` from the activity row; ``display`` has the
    same fields with ids replaced by names and ordering keys left out."""

    entity_type: str
    entity_id: str
    label: str
    verb: str
    changes: dict[str, list[Any]]
    display: dict[str, list[Any]]

    def to_json(self) -> dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "label": self.label,
            "verb": self.verb,
            "changes": self.changes,
            "display": self.display,
        }


@dataclass
class ToolOutcome:
    tool: str
    mode: Mode
    risk: Risk  # effective risk (escalated for bulk targets)
    result: ToolResult
    diff: list[DiffRow] = field(default_factory=list)
    batch_id: uuid.UUID | None = None  # set when a write tool was applied

    @property
    def ok(self) -> bool:
        return self.result.ok

    def to_json(self) -> dict[str, Any]:
        out = self.result.to_json()
        if self.mode == "dry_run" and self.ok and self.diff:
            out["preview"] = True
        return out

    def message_content(self) -> str:
        """The tool message for the model. Results carry user-authored text (titles, comments),
        so they are wrapped as data (ai-architecture §8). ``<`` is escaped inside the JSON so no
        field can close the wrapper early; the JSON stays valid."""
        body = json.dumps(self.to_json(), ensure_ascii=False, default=str).replace("<", "\\u003c")
        return f'<data source="tool:{self.tool}">{body}</data>'


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool]) -> None:
        self._tools: dict[str, Tool] = {}
        for t in tools:
            if t.spec.name in self._tools:
                raise ValueError(f"duplicate tool name: {t.spec.name}")
            if t.spec.writes and not t.spec.scopes:
                raise ValueError(f"write tool {t.spec.name} needs a scope")
            self._tools[t.spec.name] = t

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(
        self, *, names: Iterable[str] | None = None, max_risk: Risk | None = None
    ) -> list[ToolSchema]:
        """OpenAI-style tool schemas, optionally limited to some tools or to a risk ceiling
        (``max_risk="read"`` gives a read-only tool set)."""
        wanted = list(names) if names is not None else self.names
        out: list[ToolSchema] = []
        for name in wanted:
            t = self._tools[name]
            if max_risk is not None and RISK_RANK[t.spec.risk] > RISK_RANK[max_risk]:
                continue
            out.append(tool_schema(t.spec))
        return out

    async def invoke(
        self,
        session: AsyncSession,
        ctx: Ctx,
        name: str,
        arguments: str | dict[str, Any] | None,
        *,
        mode: Mode = "dry_run",
        batch_id: uuid.UUID | None = None,
        allowed_scopes: Iterable[str] | None = None,
        llm: LLM | None = None,
    ) -> ToolOutcome:
        """Run one tool call. Must be called inside the caller's ``uow.transaction()``.

        Never raises for a failure the model could act on (unknown tool, invalid arguments,
        not found, ambiguous, permission denied, conflict): those come back as a failed
        ``ToolResult``. Unexpected errors propagate after the savepoint is rolled back."""
        t = self._tools.get(name)
        if t is None:
            return _failed(name, mode, "read", "unknown_tool", f"There is no tool named {name}")
        spec = t.spec
        if allowed_scopes is not None and not set(spec.scopes) <= set(allowed_scopes):
            return _failed(name, mode, spec.risk, "scope_denied", f"{name} is not allowed here")
        try:
            raw = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
            args = spec.args_model.model_validate(raw)
        except (ValueError, ValidationError) as e:
            return _failed(name, mode, spec.risk, "invalid_arguments", _describe(e))

        run_ctx = ctx.with_(
            request_id=f"{ctx.request_id}:{name}:{uuid.uuid4().hex[:12]}",
            dry_run=mode == "dry_run" and spec.writes,
            via=ctx.via if ctx.via in AI_VIAS else "ai",
        )
        batch = (batch_id or uuid.uuid4()) if spec.writes else None
        tc = ToolContext(session=session, ctx=run_ctx, mode=mode, batch_id=batch, llm=llm)
        held = list(session.identity_map.values())
        savepoint = await session.begin_nested()
        try:
            result = await t.fn(tc, args)
            diff: list[DiffRow] = []
            if spec.writes and result.ok:
                await session.flush()
                await session.execute(
                    update(Activity)
                    .where(Activity.request_id == run_ctx.request_id, Activity.batch_id.is_(None))
                    .values(batch_id=batch)
                )
                diff = await capture_diff(session, run_ctx.request_id)
        except ToolError as e:
            await rollback_savepoint(session, savepoint, held)
            return ToolOutcome(
                name,
                mode,
                spec.risk,
                ToolResult.failure(e.code, e.message, candidates=e.candidates),
            )
        except DomainError as e:
            await rollback_savepoint(session, savepoint, held)
            return _failed(name, mode, spec.risk, e.code, e.detail)
        except IntegrityError:
            await rollback_savepoint(session, savepoint, held)
            return _failed(
                name, mode, spec.risk, "conflict", "The change conflicts with existing data"
            )
        except BaseException:
            await savepoint.rollback()
            raise
        if mode == "dry_run" or not result.ok:
            await rollback_savepoint(session, savepoint, held)
        else:
            await savepoint.commit()
        risk = spec.risk
        if spec.bulk_limit is not None and len(result.targets) > spec.bulk_limit:
            risk = "high"
        applied = mode == "apply" and spec.writes and result.ok
        return ToolOutcome(name, mode, risk, result, diff, batch if applied else None)


async def rollback_savepoint(session: AsyncSession, savepoint: Any, held: list[object]) -> None:
    """Roll the savepoint back and re-load what it expired.

    SQLAlchemy expires every object the savepoint changed (and expunges the ones it created).
    Objects the caller already held would otherwise lazy-load on their next attribute access,
    which async sessions can't do implicitly (MissingGreenlet), so a preview would break
    whoever called it. Re-loading them now keeps previews invisible to the caller."""
    await savepoint.rollback()
    for obj in held:
        state = cast("InstanceState[Any]", inspect(obj))
        if state.session is session.sync_session and state.expired_attributes:
            await session.refresh(obj)


def _failed(name: str, mode: Mode, risk: Risk, code: str, message: str) -> ToolOutcome:
    return ToolOutcome(name, mode, risk, ToolResult.failure(code, message))


def _describe(e: Exception) -> str:
    if isinstance(e, ValidationError):
        parts = []
        for err in e.errors()[:8]:
            loc = ".".join(str(x) for x in err["loc"]) or "arguments"
            parts.append(f"{loc}: {err['msg']}")
        return "Invalid arguments: " + "; ".join(parts)
    return "Invalid arguments: not a JSON object"


# ---------------- diff capture ----------------


async def capture_diff(session: AsyncSession, request_id: str) -> list[DiffRow]:
    """Diff rows for everything recorded under ``request_id``, in the order it happened.
    Labels and display values are looked up now, while the (possibly previewed) rows exist."""
    rows = list(
        (
            await session.execute(
                select(Activity).where(Activity.request_id == request_id).order_by(Activity.id)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return []
    ids: dict[str, set[uuid.UUID]] = {k: set() for k in ("task", "project", "section", "user")}
    ids["comment"] = set()
    ids["team"] = set()
    for r in rows:
        if r.entity_type in ids:
            ids[r.entity_type].add(r.entity_id)
        for fld, pair in (r.diff or {}).items():
            kind = _ID_FIELDS.get(fld)
            if kind is not None:
                ids[kind].update(_uuids(pair))
    comment_tasks: dict[uuid.UUID, uuid.UUID] = {}
    if ids["comment"]:
        for cid, tid in (
            await session.execute(
                select(Comment.id, Comment.task_id).where(Comment.id.in_(ids["comment"]))
            )
        ).all():
            comment_tasks[cid] = tid
            ids["task"].add(tid)
    names = await _names(session, ids)
    out: list[DiffRow] = []
    for r in rows:
        label = names.get(("task" if r.entity_type == "task" else r.entity_type, r.entity_id))
        if r.entity_type == "comment":
            on = names.get(("task", comment_tasks.get(r.entity_id)))  # type: ignore[arg-type]
            label = f"Comment on {on}" if on else "Comment"
        display: dict[str, list[Any]] = {}
        for fld, pair in (r.diff or {}).items():
            if fld in HIDDEN_FIELDS:
                continue
            kind = _ID_FIELDS.get(fld)
            display[fld] = (
                [_name_of(names, kind, v) for v in pair] if kind is not None else list(pair)
            )
        out.append(
            DiffRow(
                entity_type=r.entity_type,
                entity_id=str(r.entity_id),
                label=label or r.entity_type,
                verb=r.verb,
                changes={k: list(v) for k, v in (r.diff or {}).items()},
                display=display,
            )
        )
    return out


_ID_FIELDS: dict[str, str] = {
    "assignee_id": "user",
    "user_id": "user",
    "owner_id": "user",
    "section_id": "section",
    "project_id": "project",
    "team_id": "team",
    "parent_id": "task",
    "task_id": "task",
    "depends_on_id": "task",
}


def _uuids(pair: Any) -> set[uuid.UUID]:
    out: set[uuid.UUID] = set()
    for v in pair if isinstance(pair, list) else []:
        if isinstance(v, str):
            with contextlib.suppress(ValueError):
                out.add(uuid.UUID(v))
    return out


def _name_of(names: dict[tuple[str, uuid.UUID], str], kind: str, value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return names.get((kind, uuid.UUID(value)), value)
    except ValueError:
        return value


async def _names(
    session: AsyncSession, ids: dict[str, set[uuid.UUID]]
) -> dict[tuple[str, uuid.UUID], str]:
    out: dict[tuple[str, uuid.UUID], str] = {}
    if ids["task"]:
        for i, n, t in (
            await session.execute(
                select(Task.id, Task.number, Task.title).where(Task.id.in_(ids["task"]))
            )
        ).all():
            out[("task", i)] = f"{task_key(n)} {t}"
    simple: list[tuple[str, Any]] = [
        ("project", Project),
        ("section", Section),
        ("team", Team),
        ("user", User),
    ]
    for kind, model in simple:
        if ids[kind]:
            for i, n in (
                await session.execute(select(model.id, model.name).where(model.id.in_(ids[kind])))
            ).all():
                out[(kind, i)] = n
    return out
