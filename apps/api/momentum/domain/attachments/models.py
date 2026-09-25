from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin

EXTRACT_STATUSES = ("pending", "done", "skipped", "failed")


class Attachment(IdMixin, Base):
    __tablename__ = "attachments"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    comment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("comments.id"), nullable=True)
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
        CheckConstraint("task_id is not null or comment_id is not null", name="has_owner"),
        Index("ix_attachments_task", "task_id"),
        Index("ix_attachments_comment", "comment_id"),
    )
