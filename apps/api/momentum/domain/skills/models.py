"""Phase 7.6 S76-05 (spec §7.2): skills, what an agent learned and is allowed to use. Every one is
a typed, reviewable row: there is no free-form agent memory."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin, TimestampMixin

SKILL_SCOPES = ("workspace", "entity", "project")
SKILL_KINDS = ("hint", "rule", "example", "field_map")
SKILL_STATUSES = ("proposed", "active", "rejected", "retired")
SKILL_SOURCES = ("learned", "authored", "starter")


class Skill(IdMixin, TimestampMixin, Base):
    __tablename__ = "agent_skills"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    pack_key: Mapped[str] = mapped_column(String(60))
    scope_type: Mapped[str] = mapped_column(String(12))
    scope_id: Mapped[uuid.UUID | None]
    kind: Mapped[str] = mapped_column(String(12))
    field: Mapped[str | None] = mapped_column(String(200))
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(12))
    version: Mapped[int] = mapped_column(Integer, default=1)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_skills.id"))
    source: Mapped[str] = mapped_column(String(12))
    starter_key: Mapped[str | None] = mapped_column(String(120))
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    tryout: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    proposed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(f"scope_type in {SKILL_SCOPES}", name="scope_type"),
        CheckConstraint(f"kind in {SKILL_KINDS}", name="kind"),
        CheckConstraint(f"status in {SKILL_STATUSES}", name="status"),
        CheckConstraint(f"source in {SKILL_SOURCES}", name="source"),
        CheckConstraint("(scope_type = 'workspace') = (scope_id is null)", name="scope"),
        Index("ix_agent_skills_lookup", "workspace_id", "pack_key", "status", "scope_type"),
    )
