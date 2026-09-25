"""S2.7.1: import bookkeeping (`docs/architecture/data-model.md §10`).

Plain storage entities, kept in the domain layer like every other model — the code that actually
talks to a provider (Asana's REST API) lives outside domain, in `momentum/integrations/`, per the
import-linter contract ("Domain does not depend on ... integrations").
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin

IMPORT_STATUSES = ("pending", "running", "done", "failed")


class ExternalLink(IdMixin, Base):
    __tablename__ = "external_links"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[uuid.UUID]
    provider: Mapped[str] = mapped_column(String(24))
    external_id: Mapped[str] = mapped_column(String(100))
    url: Mapped[str | None] = mapped_column(String(500))
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("provider", "entity_type", "external_id", name="uq_provider_gid"),
        Index("ix_external_links_entity", "entity_type", "entity_id"),
    )


class ImportJob(IdMixin, Base):
    __tablename__ = "import_jobs"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    source: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    log: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("source in ('asana','csv')", name="source"),
        CheckConstraint(f"status in {IMPORT_STATUSES}", name="status"),
    )
