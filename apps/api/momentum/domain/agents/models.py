"""S5.1.1: agents and their runs; see data-model.md §9."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin, TimestampMixin

AGENT_KINDS = ("llm", "handler", "pack")  # pack: Phase 7.6 (ADR-0012)
AUTONOMY_LEVELS = ("suggest", "confirm", "auto")
AGENT_MODEL_ALIASES = ("fast", "default", "smart")
# starter = packaged with Momentum, host = a definition directory the host app passed in,
# custom = created in the UI/API, pack = installed from a pack's manifest (Phase 7.6)
AGENT_SOURCES = ("starter", "host", "custom", "pack")
RUN_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled", "budget_exceeded")


class Agent(IdMixin, TimestampMixin, Base):
    """An agent's configuration. Every agent has its own user account (``user_id``,
    ``users.is_agent``) that it acts as and that project membership is granted to (kickoff Q1:
    explicit membership only). Agents are disabled, never deleted: runs and activity keep
    pointing at them.

    ``installed_hash`` is the hash of the definition as last installed from YAML (null for
    custom agents), so a re-install can tell an admin's edits (drift) from an untouched row."""

    __tablename__ = "agents"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    key: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(80))
    avatar: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text, default="")
    instructions: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(16), default="llm")
    handler: Mapped[str | None] = mapped_column(String(120))
    # Phase 7.6 (migration 0046): the pack an agent was installed from, and the version installed.
    # Capabilities, effects and data are always read from the pack's code, never from this row.
    pack_key: Mapped[str | None] = mapped_column(String(60))
    pack_version: Mapped[str | None] = mapped_column(String(20))
    tools: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    scope: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    autonomy: Mapped[str] = mapped_column(String(16), default="confirm")
    triggers: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    model_alias: Mapped[str] = mapped_column(String(16), default="default")
    budget_monthly_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    budget_monthly_tokens: Mapped[int] = mapped_column(BigInteger)
    limits: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # S5.1.2 (migration 0029): when it was last switched on; triggers ignore older events
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(16))
    installed_hash: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

    __table_args__ = (
        UniqueConstraint("workspace_id", "key"),
        CheckConstraint(f"kind in {AGENT_KINDS}", name="kind"),
        CheckConstraint("(kind = 'handler') = (handler is not null)", name="handler"),
        CheckConstraint(
            "(kind = 'pack') = (pack_key is not null and pack_version is not null)", name="pack"
        ),
        CheckConstraint(f"autonomy in {AUTONOMY_LEVELS}", name="autonomy"),
        CheckConstraint(f"model_alias in {AGENT_MODEL_ALIASES}", name="model_alias"),
        CheckConstraint(f"source in {AGENT_SOURCES}", name="source"),
    )


class AgentRun(IdMixin, Base):
    """One execution of an agent for one trigger (written by the runtime, S5.1.2).

    ``dedupe_key`` (unique per agent) is what makes the same trigger delivered twice run once:
    ``agent:trigger:entity[:period]``. ``trace`` is a list of short step records (summary, tool
    name, redacted args, result digest, tokens), never full prompts."""

    __tablename__ = "agent_runs"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"))
    trigger: Mapped[dict[str, Any]] = mapped_column(JSONB)
    dedupe_key: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    steps: Mapped[int] = mapped_column(Integer, default=0)
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    trace: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("agent_id", "dedupe_key"),
        CheckConstraint(f"status in {RUN_STATUSES}", name="status"),
        Index("ix_agent_runs_agent_created", "agent_id", "created_at"),
        Index("ix_agent_runs_workspace_created", "workspace_id", "created_at"),
    )
