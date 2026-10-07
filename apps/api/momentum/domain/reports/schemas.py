"""Phase 7.5 (spec §6.3): the reports API shapes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from momentum.reports.spec import ReportSpec


class ReportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spec: ReportSpec


class OutlineItemOut(BaseModel):
    type: Literal["heading", "kpis", "table", "tasks", "chart", "narrative"]
    title: str
    rows: int | None = None


class ReportPreviewOut(BaseModel):
    title: str
    subtitle: str
    scope_note: str
    items: list[OutlineItemOut]
    pages: int | None = None  # docx, pdf
    sheets: int | None = None  # xlsx


class ReportRunOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: Literal["queued", "running", "done", "failed"]
    attachment_id: uuid.UUID | None
    filename: str | None = None
    project_id: uuid.UUID | None = None
    portfolio_id: uuid.UUID | None = None
    error: str | None = None
    activity_id: uuid.UUID | None = None  # report.generated (undo deletes the file)
    created_at: datetime
    finished_at: datetime | None
