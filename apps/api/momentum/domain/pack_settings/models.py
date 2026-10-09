"""Phase 7.6 S76-05 (spec §8.3): a pack's settings, as workspace defaults and per-project
overrides (field by field)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin, TimestampMixin


class PackSettingsRow(IdMixin, TimestampMixin, Base):
    __tablename__ = "agent_pack_settings"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    pack_key: Mapped[str] = mapped_column(String(60))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"))
    values: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

    __table_args__ = (
        Index(
            "uq_agent_pack_settings_workspace",
            "workspace_id",
            "pack_key",
            unique=True,
            postgresql_where=text("project_id IS NULL"),
        ),
        Index(
            "uq_agent_pack_settings_project",
            "workspace_id",
            "pack_key",
            "project_id",
            unique=True,
            postgresql_where=text("project_id IS NOT NULL"),
        ),
    )
