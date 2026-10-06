"""Phase 7.5 (spec §4.3): the parse cache. One row per parsed file and parser version.

A parse is a cache of a file's content, the same as ``attachments.text_extract``: it isn't a
change to anyone's data, so it records no activity. The DocumentModel goes in ``model`` without
its sheet rows; the rows are gzipped JSON in the storage backend under ``rows_key``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin

PARSE_STATUSES = ("ok", "failed", "unsupported", "encrypted")


class FileParse(IdMixin, Base):
    __tablename__ = "file_parses"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    # exactly one: a task/comment/project/portfolio file, or a file attached to an Ask Mo chat
    attachment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("attachments.id", ondelete="CASCADE"), nullable=True
    )
    conversation_file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_conversation_files.id", ondelete="CASCADE"), nullable=True
    )
    parser_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    model: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    rows_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(f"status in {PARSE_STATUSES}", name="status"),
        CheckConstraint("num_nonnulls(attachment_id, conversation_file_id) = 1", name="one_file"),
        Index("ix_file_parses_attachment", "attachment_id", "parser_version", unique=True),
        Index(
            "ix_file_parses_conversation_file",
            "conversation_file_id",
            "parser_version",
            unique=True,
        ),
    )
