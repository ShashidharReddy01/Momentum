"""Phase 7.6 S76-04 (spec §6): records, the structured things packs produce (Bernie's invoices),
their types and their versions."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin, SoftDeleteMixin, TimestampMixin

RECORD_STATUSES = (
    "draft",
    "needs_review",
    "ready",
    "approved",
    "rejected",
    "void",
    "superseded",
)
CLASSIFICATIONS = ("public", "internal", "financial", "personal")
RECORD_VIAS = ("agent", "review", "api", "undo")


class RecordType(IdMixin, TimestampMixin, Base):
    """A record type as a pack registered it at install (one row per key and version): its JSON
    Schema snapshot and display spec (title template, money and date paths, arrays, columns, task
    fields, search and identity paths) and its data classification. SQL, dashboards and exports
    read field paths from here; validation and rechecks run in the pack's code."""

    __tablename__ = "record_types"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    pack_key: Mapped[str] = mapped_column(String(60))
    key: Mapped[str] = mapped_column(String(60))
    version: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(80))
    schema: Mapped[dict[str, Any]] = mapped_column(JSONB)
    display: Mapped[dict[str, Any]] = mapped_column(JSONB)
    classification: Mapped[str] = mapped_column(String(12))

    __table_args__ = (
        UniqueConstraint("workspace_id", "key", "version"),
        CheckConstraint(f"classification in {CLASSIFICATIONS}", name="classification"),
    )


class Record(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "records"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    type: Mapped[str] = mapped_column(String(60))
    type_version: Mapped[int] = mapped_column(Integer)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id"))
    source_attachment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("attachments.id"))
    source_sha256: Mapped[str | None] = mapped_column(String(64))
    source_locator: Mapped[str | None] = mapped_column(String(120))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_via: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(300))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    decision: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    identity_key: Mapped[str | None] = mapped_column(String(300))
    entity_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), default=list)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    currency: Mapped[str | None] = mapped_column(String(3))
    occurred_on: Mapped[date | None] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, default=1)
    search_text: Mapped[str] = mapped_column(Text, default="")
    search: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', coalesce(search_text, ''))", persisted=True),
        deferred=True,
    )

    __table_args__ = (
        CheckConstraint(f"status in {RECORD_STATUSES}", name="status"),
        Index(
            "ix_records_project_type_status",
            "project_id",
            "type",
            "status",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_records_identity", "workspace_id", "type", "identity_key"),
        Index("ix_records_occurred", "workspace_id", "type", "occurred_on"),
        Index("ix_records_entity_ids", "entity_ids", postgresql_using="gin"),
        Index("ix_records_search", "search", postgresql_using="gin"),
        Index("ix_records_task", "task_id"),
    )


class RecordVersion(IdMixin, Base):
    """Every version of a record: its data, provenance, checks and status, who changed it and
    how (``change``: the correction operations used and the top-level fields they touched)."""

    __tablename__ = "record_versions"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(16))
    changed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    via: Mapped[str] = mapped_column(String(12))
    change: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("record_id", "version"),
        CheckConstraint(f"via in {RECORD_VIAS}", name="via"),
    )
