"""Building blocks of the tool registry: the ``@tool`` decorator, what a tool receives
(``ToolContext``) and what it returns (``ToolResult``). ai-architecture.md §3.

A tool is a thin adapter: it resolves references, calls domain services (the one write path)
and returns compact, model-friendly JSON. It never writes through the ORM itself, and never
decides permissions: the services do, for whoever ``ctx.actor`` is.
"""

from __future__ import annotations

import typing
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx

Risk = Literal["read", "low", "medium", "high"]
RISK_RANK: dict[str, int] = {"read": 0, "low": 1, "medium": 2, "high": 3}
Mode = Literal["dry_run", "apply"]


class ToolError(Exception):
    """A failure the model should see and can act on (ambiguous reference, not found, …).

    Domain errors raised by services are converted to the same shape by the registry."""

    def __init__(
        self, code: str, message: str, *, candidates: list[dict[str, Any]] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.candidates = candidates


@dataclass
class ToolResult:
    """What a tool returns. ``targets`` lists the entities the call changes (for write tools;
    the registry escalates risk when there are more than the tool's ``bulk_limit``)."""

    ok: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    targets: list[dict[str, Any]] = field(default_factory=list)
    error: dict[str, Any] | None = None

    @classmethod
    def success(
        cls,
        summary: str,
        data: dict[str, Any] | None = None,
        *,
        targets: list[dict[str, Any]] | None = None,
    ) -> ToolResult:
        return cls(ok=True, summary=summary, data=data or {}, targets=targets or [])

    @classmethod
    def failure(
        cls, code: str, message: str, *, candidates: list[dict[str, Any]] | None = None
    ) -> ToolResult:
        err: dict[str, Any] = {"code": code, "message": message}
        if candidates is not None:
            err["candidates"] = candidates
        return cls(ok=False, summary=message, error=err)

    def to_json(self) -> dict[str, Any]:
        if not self.ok:
            return {"ok": False, "error": self.error}
        out: dict[str, Any] = {"ok": True, "summary": self.summary}
        if self.data:
            out["data"] = self.data
        return out


@dataclass(frozen=True)
class ToolContext:
    """Everything a tool body needs. ``ctx`` is already the invocation's context (its own
    request id, ``dry_run`` set in preview mode, ``via`` marked as AI)."""

    session: AsyncSession
    ctx: Ctx
    mode: Mode
    batch_id: uuid.UUID | None = None

    @property
    def preview(self) -> bool:
        return self.mode == "dry_run"

    def verb(self, done: str, would: str) -> str:
        """Phrase a summary for the mode: "Created …" applied, "Would create …" previewed."""
        return would if self.preview else done


ArgsT = typing.TypeVar("ArgsT", bound=BaseModel)
ToolFn = Callable[[ToolContext, Any], Awaitable[ToolResult]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    risk: Risk
    scopes: tuple[str, ...]
    args_model: type[BaseModel]
    bulk_limit: int | None = None  # more targets than this escalates the risk to "high"

    @property
    def writes(self) -> bool:
        return self.risk != "read"


@dataclass(frozen=True)
class Tool:
    spec: ToolSpec
    fn: ToolFn


def tool(
    *,
    name: str,
    description: str,
    risk: Risk,
    scopes: tuple[str, ...],
    bulk_limit: int | None = None,
) -> Callable[[Callable[[ToolContext, ArgsT], Awaitable[ToolResult]]], Tool]:
    """Declare a tool. The arguments model is the annotation of the function's second parameter.

    Declaring a tool has no side effect: registries are built explicitly from these objects
    (``registry.build_registry``), so nothing is registered at import time."""

    def wrap(fn: Callable[[ToolContext, ArgsT], Awaitable[ToolResult]]) -> Tool:
        hints = typing.get_type_hints(fn)
        params = [p for p in fn.__code__.co_varnames[: fn.__code__.co_argcount]]
        if len(params) != 2:
            raise TypeError(f"tool {name}: expected (tc, args) parameters")
        model = hints.get(params[1])
        if not (isinstance(model, type) and issubclass(model, BaseModel)):
            raise TypeError(f"tool {name}: the args parameter must be a Pydantic model")
        spec = ToolSpec(
            name=name,
            description=description,
            risk=risk,
            scopes=scopes,
            args_model=model,
            bulk_limit=bulk_limit,
        )
        return Tool(spec=spec, fn=typing.cast(ToolFn, fn))

    return wrap
