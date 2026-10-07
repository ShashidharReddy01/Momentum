"""Phase 7.5 (spec §6.3): a report run, from the request to the stored file.

A run records who asked for which ``ReportSpec`` and how it went (``queued`` → ``running`` →
``done`` / ``failed``); the file itself is an attachment (``source='generated'``) with the spec
in ``generated_spec``, on the project or the portfolio the report is about.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin

RUN_STATUSES = ("queued", "running", "done", "failed")


class ReportRun(IdMixin, Base):
    __tablename__ = "report_runs"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(24))
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(12), default="queued")
    attachment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("attachments.id"), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # regenerate: the generated file this run adds a version to
    replace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("attachments.id"), nullable=True
    )
    created_via: Mapped[str] = mapped_column(String(16), default="ui")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(f"status in {RUN_STATUSES}", name="status"),
        Index("ix_report_runs_workspace_created", "workspace_id", "created_at"),
    )
