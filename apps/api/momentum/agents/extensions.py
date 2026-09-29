"""S5.1.5 (ADR-0009): how a host application extends agents without forking Momentum.

A host gives Momentum an ``Extensions`` object:

- ``tools``: extra AI tools (built with ``momentum.ai.tools.base.tool``), added to the registry
  so its agents (and Mo) can call them; the same rules as built-in tools apply (a ``risk``, a
  dry-run path, writes only through services);
- ``handlers``: Python functions that *are* agents (``kind: handler`` definitions name them). A
  handler gets a ``HandlerRun`` and returns a ``HandlerResult``; it runs with the same triggers,
  access, scope, timeout, kill switches, trace and runs page as a model-driven agent;
- ``definition_dirs``: directories of the host's own agent definition files.

It reaches Momentum either as ``create_app(extensions=…)`` / ``mount_momentum(extensions=…)``, or
through the ``MOMENTUM_AGENT_EXTENSIONS`` setting (``"package.module:attribute"``, the attribute
being an ``Extensions`` or a zero-argument function returning one). The setting is what a
separate worker process uses, so set it wherever agents run.
"""

from __future__ import annotations

import hashlib
import importlib
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai.actions import ProposedCall
from momentum.ai.tools.base import Tool
from momentum.ai.tools.write_tools import text_doc
from momentum.core.context import Ctx
from momentum.core.errors import ValidationFailed
from momentum.core.ids import new_id
from momentum.core.settings import Settings
from momentum.core.storage import build_storage
from momentum.domain.attachments import service as attachments
from momentum.domain.comments.service import create_comment
from momentum.domain.tasks.models import Task

if TYPE_CHECKING:
    from momentum.ai.llm import LLM
    from momentum.ai.tools.registry import ToolOutcome, ToolRegistry
    from momentum.ai.types import Alias, Completion, Msg


async def attach_file(
    session: AsyncSession,
    ctx: Ctx,
    settings: Settings,
    task_id: uuid.UUID,
    filename: str,
    data: bytes,
    mime: str = "text/plain",
) -> uuid.UUID:
    """Store ``data`` and attach it to a task as ``ctx``'s actor, with its text extracted for
    search and ``get_attachment_text``. Used by handlers and by long agent answers (S5.2.1)."""
    key = f"{ctx.workspace_id}/{new_id()}"

    async def chunks() -> Any:
        yield data

    await build_storage(settings).save_stream(key, chunks())
    m = await attachments.create_attachment(
        session,
        ctx,
        task_id=task_id,
        comment_id=None,
        storage_key=key,
        filename=filename,
        mime=mime,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    await attachments.record_text_extract(
        session, m.entity.id, attachments.extract_text_from_bytes(data, mime)
    )
    return m.entity.id


@dataclass
class HandlerResult:
    """What a handler hands back. ``text`` is its answer: posted in the task's thread when a
    person asked (assigned, mentioned, run now), like a model-driven agent's."""

    text: str | None = None


Handler = Callable[["HandlerRun"], Awaitable[HandlerResult | None]]


@dataclass
class Extensions:
    tools: Sequence[Tool] = ()
    handlers: Mapping[str, Handler] = field(default_factory=dict)
    definition_dirs: Sequence[str | Path] = ()


EMPTY = Extensions()


def load_extensions(settings: Settings) -> Extensions:
    """The extensions named by ``MOMENTUM_AGENT_EXTENSIONS`` (none when it's empty)."""
    ref = settings.agent_extensions.strip()
    if not ref:
        return EMPTY
    module_name, _, attr = ref.partition(":")
    if not module_name or not attr:
        raise ValueError('MOMENTUM_AGENT_EXTENSIONS must look like "package.module:attribute"')
    value: Any = getattr(importlib.import_module(module_name), attr)
    if callable(value) and not isinstance(value, Extensions):
        value = value()
    if not isinstance(value, Extensions):
        raise ValueError(f"MOMENTUM_AGENT_EXTENSIONS {ref!r} is not an Extensions object")
    return value


def merge(*parts: Extensions | None) -> Extensions:
    tools: list[Tool] = []
    handlers: dict[str, Handler] = {}
    dirs: list[str | Path] = []
    for part in parts:
        if part is None:
            continue
        tools.extend(part.tools)
        handlers.update(part.handlers)
        dirs.extend(part.definition_dirs)
    return Extensions(tools=tools, handlers=handlers, definition_dirs=dirs)


class HandlerRun:
    """What a handler works with. Its writes go through Momentum's services as ``ctx`` (the
    agent's account, or — when a person asked — the agent acting for them, seeing only what both
    can see), so they are permission-checked, recorded, undoable and marked ``via="agent"``."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        ctx: Ctx,
        settings: Settings,
        llm: LLM,
        registry: ToolRegistry,
        run_id: uuid.UUID,
        agent_key: str,
        agent_name: str,
        model_alias: str,
        trigger: dict[str, Any],
        step: Callable[[str], None],
    ) -> None:
        self.session = session
        self.ctx = ctx
        self.settings = settings
        self.run_id = run_id
        self.agent_key = agent_key
        self.agent_name = agent_name
        self.trigger = trigger
        self._llm = llm
        self._registry = registry
        self._alias = model_alias
        self._step = step
        self.proposals: list[ProposedCall] = []

    # --- what the run is about ---
    @property
    def task_id(self) -> uuid.UUID | None:
        raw = self.trigger.get("task_id")
        return uuid.UUID(str(raw)) if raw else None

    @property
    def project_id(self) -> uuid.UUID | None:
        raw = self.trigger.get("project_id")
        return uuid.UUID(str(raw)) if raw else None

    @property
    def input(self) -> str | None:
        """Text a person passed with "Run now" (notes, a brief)."""
        raw = self.trigger.get("input")
        return str(raw) if raw else None

    async def task(self) -> Task | None:
        if self.task_id is None:
            return None
        from momentum.domain.access import get_visible_task

        return (await get_visible_task(self.session, self.ctx, self.task_id))[0]

    # --- recording ---
    def step(self, summary: str) -> None:
        """A line on the run's timeline (keep it short; no secrets)."""
        self._step(summary)

    # --- the model, billed to this run and its budget ---
    async def complete(
        self, messages: list[Msg], *, alias: Alias | None = None, max_tokens: int = 1500
    ) -> Completion:
        return await self._llm.complete(
            alias=alias or self._alias,  # type: ignore[arg-type]
            messages=messages,
            feature=f"agent:{self.agent_key}",
            ctx=self.ctx,
            max_tokens=max_tokens,
            agent_run_id=self.run_id,
        )

    # --- tools ---
    async def read(self, tool: str, args: dict[str, Any]) -> ToolOutcome:
        """Call a read tool (search, get_task, get_attachment_text, a host's own read tools)."""
        t = self._registry.get(tool)
        if t is None or t.spec.writes:
            raise ValidationFailed(f"{tool} isn't a read tool this agent can use")
        return await self._registry.invoke(
            self.session, self.ctx, tool, args, mode="dry_run", llm=self._llm
        )

    def propose(self, tool: str, args: dict[str, Any]) -> None:
        """A change for the person the run is for to apply (it's previewed and sent to them
        when the handler returns), instead of making it directly."""
        self.proposals.append(ProposedCall(tool, args))

    # --- output on the run's task ---
    async def comment(self, text: str) -> uuid.UUID:
        if self.task_id is None:
            raise ValidationFailed("This run isn't about a task")
        m = await create_comment(self.session, self.ctx, self.task_id, text_doc(text))
        self.step(f"Commented: {text.splitlines()[0][:120] if text else ''}")
        return m.entity.id

    async def attach(self, filename: str, data: bytes, mime: str = "text/plain") -> uuid.UUID:
        """Attach a file (a report, a generated document) to the run's task."""
        if self.task_id is None:
            raise ValidationFailed("This run isn't about a task")
        attachment_id = await attach_file(
            self.session, self.ctx, self.settings, self.task_id, filename, data, mime
        )
        self.step(f"Attached {filename}")
        return attachment_id
