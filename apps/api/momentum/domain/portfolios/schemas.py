from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from momentum.domain.status_updates.schemas import StatusUpdateIn


class PortfolioIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class PortfolioPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class PortfolioItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: uuid.UUID


class PortfolioOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    owner_id: uuid.UUID
    status: str | None
    version: int
    can_edit: bool
    project_count: int  # projects the viewer can see
    created_at: datetime


class PortfolioProjectRow(BaseModel):
    """One project line of the portfolio table, as the viewer sees it."""

    id: uuid.UUID
    name: str
    color: str | None
    owner_id: uuid.UUID | None
    status: str | None
    total_tasks: int
    completed_tasks: int
    overdue_tasks: int
    start_on: date | None
    due_on: date | None
    latest_update_title: str | None
    latest_update_at: datetime | None


class PortfolioDetailOut(PortfolioOut):
    projects: list[PortfolioProjectRow]
    hidden_projects: int  # in the portfolio, but in projects the viewer can't see (counted only)


class PortfolioStatusDraftOut(BaseModel):
    draft: StatusUpdateIn
