from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from momentum.domain.status_updates.schemas import StatusUpdateIn

ProgressSource = Literal["manual", "projects", "subgoals"]
LinkType = Literal["project", "portfolio"]


class GoalMetric(BaseModel):
    """How a goal is measured: from ``start`` towards ``target``; ``current`` moves with check-ins.
    A target below the start is fine (e.g. reduce churn from 8% to 5%)."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["number", "percent", "currency"] = "number"
    start: float = 0
    target: float
    current: float | None = None
    unit: str | None = Field(default=None, max_length=12)  # e.g. "customers", "USD"


class GoalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    owner_id: uuid.UUID | None = None  # defaults to the creator
    parent_id: uuid.UUID | None = None
    period_start: date
    period_end: date
    period_label: str | None = Field(default=None, max_length=40)
    metric: GoalMetric | None = None
    progress_source: ProgressSource = "manual"

    @model_validator(mode="after")
    def _period(self) -> GoalIn:
        if self.period_start > self.period_end:
            raise ValueError("the period ends before it starts")
        return self


class GoalPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    owner_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    period_start: date | None = None
    period_end: date | None = None
    period_label: str | None = Field(default=None, max_length=40)
    metric: GoalMetric | None = None
    progress_source: ProgressSource | None = None


class GoalLinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_type: LinkType
    entity_id: uuid.UUID


class GoalOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    owner_id: uuid.UUID
    parent_id: uuid.UUID | None
    period_start: date
    period_end: date
    period_label: str | None
    metric: GoalMetric | None
    progress_source: ProgressSource
    status: str | None
    version: int
    can_edit: bool
    # 0..1, computed for this viewer from the progress source; null when there's nothing to go on
    progress: float | None
    created_at: datetime


class GoalLinkOut(BaseModel):
    entity_type: LinkType
    id: uuid.UUID
    name: str
    status: str | None
    progress: float | None  # completion of the project (or its portfolio's visible projects)


class GoalDetailOut(GoalOut):
    links: list[GoalLinkOut]
    hidden_links: int  # linked projects the viewer can't see (counted only)
    children: list[GoalOut]


class GoalCheckInIn(StatusUpdateIn):
    """A goal check-in: a status update, optionally moving the metric's current value."""

    current: float | None = None
