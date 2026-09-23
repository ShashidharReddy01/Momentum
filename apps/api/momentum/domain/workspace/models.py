from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin, TimestampMixin


class Workspace(IdMixin, TimestampMixin, Base):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    task_seq: Mapped[int] = mapped_column(BigInteger, default=0)

    @property
    def workspace_id(self) -> object:
        return self.id
