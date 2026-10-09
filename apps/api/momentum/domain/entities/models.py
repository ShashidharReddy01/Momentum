"""Phase 7.6 S76-05 (spec §7.1): entities, the things packs know about across records (vendors
now; customers, contracts and merchants later)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin, TimestampMixin

ENTITY_STATUSES = ("active", "merged", "archived")


class Entity(IdMixin, TimestampMixin, Base):
    """``attributes`` are validated by the pack's ``EntityType`` model. A bank account is stored
    only as ``bank: {fingerprint, last4, seen_first, seen_last}``: the fingerprint is an HMAC with
    the workspace secret and never leaves the server. ``match_text`` (name and aliases) is what
    trigram matching runs on; ``profile`` is computed nightly by the pack."""

    __tablename__ = "entities"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    pack_key: Mapped[str] = mapped_column(String(60))
    type: Mapped[str] = mapped_column(String(40))
    key: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(300))
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    match_text: Mapped[str] = mapped_column(Text, default="")
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    profile: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="active")
    merged_into: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("entities.id"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_via: Mapped[str] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(default=1)

    __table_args__ = (
        UniqueConstraint("workspace_id", "type", "key"),
        CheckConstraint(f"status in {ENTITY_STATUSES}", name="status"),
        Index(
            "ix_entities_match_text",
            "match_text",
            postgresql_using="gin",
            postgresql_ops={"match_text": "gin_trgm_ops"},
        ),
        Index("ix_entities_type", "workspace_id", "type", "status"),
    )
