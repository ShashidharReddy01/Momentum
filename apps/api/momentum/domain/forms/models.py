"""S4.2.1: form builder (+ public forms); see data-model.md.

A form belongs to one project and turns answers into a task via the same
``domain.tasks.service.create_task`` every other caller uses. ``questions`` is a JSON list
validated on write by ``schemas.FormSpec``; each question maps to the task's title, description,
assignee, due date, priority, or one of the project's custom fields.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin, SoftDeleteMixin, TimestampMixin


class Form(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "forms"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    section_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sections.id"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    questions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    public_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # S4.2.2: chat UI asks the questions naturally instead of a plain form; answers still map
    # to the same fields, and the transcript is attached as a comment on the created task.
    conversational: Mapped[bool] = mapped_column(Boolean, default=False)
    # Generated once, kept even while the public link is off, so re-enabling it doesn't hand
    # out a new URL. Never guessable (secrets.token_urlsafe); only shown to a project admin.
    public_token: Mapped[str] = mapped_column(String(64), unique=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))

    __table_args__ = (UniqueConstraint("public_token", name="uq_forms_public_token"),)


class FormSubmission(IdMixin, Base):
    """One answered form; ``ip_hash`` is a salted hash of the submitter's IP (never the raw
    address), used only to throttle spam on the public link."""

    __tablename__ = "form_submissions"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    form_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forms.id"))
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"))
    answers: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_form_submissions_form_created", "form_id", "created_at"),
        Index("ix_form_submissions_form_ip_created", "form_id", "ip_hash", "created_at"),
    )
