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
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin
from momentum.core.ids import new_id

EXTRACT_STATUSES = ("pending", "done", "skipped", "failed")
# Phase 7.5 (spec §3.1): where a file came from
SOURCES = ("upload", "generated", "agent", "import")


class Attachment(IdMixin, Base):
    __tablename__ = "attachments"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    comment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("comments.id"), nullable=True)
    # Phase 7.5: a file uploaded straight to a project (D3), or a generated portfolio report.
    # Exactly one owner among task, comment, project and portfolio.
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    portfolio_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("portfolios.id"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(16), default="upload", server_default="upload")
    # every version of one file shares a group (the first version's id); only the newest live
    # version is current
    version_group: Mapped[uuid.UUID] = mapped_column()
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # source='generated': the report spec that produced the file, so it can be regenerated
    generated_spec: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    storage_key: Mapped[str] = mapped_column(String(300))
    filename: Mapped[str] = mapped_column(String(300))
    mime: Mapped[str] = mapped_column(String(150))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    text_extract: Mapped[str | None] = mapped_column(Text, nullable=True)
    extract_status: Mapped[str] = mapped_column(String(20), default="pending")
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(f"extract_status in {EXTRACT_STATUSES}", name="extract_status"),
        CheckConstraint(
            "num_nonnulls(task_id, comment_id, project_id, portfolio_id) = 1", name="one_owner"
        ),
        CheckConstraint(f"source in {SOURCES}", name="source"),
        Index("ix_attachments_task", "task_id"),
        Index("ix_attachments_comment", "comment_id"),
        Index("ix_attachments_project", "project_id", postgresql_where=text("deleted_at is null")),
        Index(
            "ix_attachments_portfolio", "portfolio_id", postgresql_where=text("deleted_at is null")
        ),
        Index("ix_attachments_version_group", "version_group", "version"),
    )


@event.listens_for(Attachment, "before_insert")
def _first_version(_mapper: object, _conn: object, target: Attachment) -> None:
    """A new file starts its own version group (its own id), unless it's a new version."""
    if target.id is None:
        target.id = new_id()
    if target.version_group is None:
        target.version_group = target.id
