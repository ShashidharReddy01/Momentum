"""Phase 7.6 S76-03 (spec §5.1): an agent's question to people, asked from a durable job and
answered from the task thread, the inbox, Mo or the API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin

ASK_KINDS = ("choice", "confirm", "form", "text", "pick_entity", "pick_record")
ASK_STATUSES = ("open", "answered", "expired", "cancelled", "superseded")
ANSWER_VIAS = ("card", "thread", "inbox", "mo", "api", "expiry")


class Ask(IdMixin, Base):
    """One question from a job (``run_id`` + ``step_key``: the step waiting on it). Lives in the
    job's task thread as a comment (``comment_id``) carrying an ``askCard`` node. ``to_user_ids``
    is resolved from ``route`` when the ask is made (``route_fallback`` says when that route
    resolved to nobody and who got it instead); guests are never on it."""

    __tablename__ = "asks"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"))
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id"))
    step_key: Mapped[str] = mapped_column(String(120))
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"))
    comment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("comments.id"))
    to_user_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), default=list)
    route: Mapped[str] = mapped_column(String(60))
    route_fallback: Mapped[str | None] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(12))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    options: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    form: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    default_on_expiry: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(12), default="open")
    answer: Mapped[Any | None] = mapped_column(JSONB)
    answered_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    answered_via: Mapped[str | None] = mapped_column(String(12))
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("asks.id"))
    remind_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reminders_sent: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(f"kind in {ASK_KINDS}", name="kind"),
        CheckConstraint(f"status in {ASK_STATUSES}", name="status"),
        CheckConstraint(f"answered_via in {ANSWER_VIAS}", name="answered_via"),
        # one live ask per waiting step (an escalation supersedes the old row)
        Index(
            "uq_asks_run_step_live",
            "run_id",
            "step_key",
            unique=True,
            postgresql_where=text("status <> 'superseded'"),
        ),
        Index("ix_asks_task", "task_id"),
        Index("ix_asks_open_due", "status", "expires_at"),
        Index("ix_asks_to_user_ids", "to_user_ids", postgresql_using="gin"),
    )
