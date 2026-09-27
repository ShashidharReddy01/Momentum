"""S4.1.1: automation rules and the log of their runs; see data-model.md."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin, SoftDeleteMixin, TimestampMixin

RUN_STATUSES = ("success", "skipped", "failed")


class Rule(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    """``project_id`` null means a workspace rule. ``trigger``, ``conditions`` and ``actions`` are
    validated on write by ``schemas.RuleSpec`` and read back tolerantly by the executor."""

    __tablename__ = "rules"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    trigger: Mapped[dict[str, Any]] = mapped_column(JSONB)
    conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    created_from_prompt: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class RuleRun(IdMixin, Base):
    """One rule reacting to one outbox event. ``(rule_id, outbox_event_id)`` is unique: a rule
    can't fire twice on the same event, however often the event is delivered. ``depth`` is the
    depth of the *triggering* event (0 = caused by a person)."""

    __tablename__ = "rule_runs"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rules.id"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"))
    outbox_event_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16))
    depth: Mapped[int] = mapped_column(Integer, default=0)
    actions_run: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activity_batch_id: Mapped[uuid.UUID | None]

    __table_args__ = (
        UniqueConstraint("rule_id", "outbox_event_id"),
        CheckConstraint(f"status in {RUN_STATUSES}", name="status"),
        Index("ix_rule_runs_rule_started", "rule_id", "started_at"),
        Index("ix_rule_runs_project_finished", "project_id", "finished_at"),
    )
