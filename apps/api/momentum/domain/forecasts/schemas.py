from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel


class DriverOut(BaseModel):
    kind: str  # overdue | blocked | unassigned | scope | forecast
    text: str
    points: int
    tasks: list[str]


class ForecastOut(BaseModel):
    """A project's latest forecast. ``p50``/``p80``/``p95``: the dates by which the remaining work
    is done in 50/80/95% of the simulated futures (null unless ``status`` is ``ok``)."""

    id: uuid.UUID
    project_id: uuid.UUID
    computed_at: datetime
    as_of: date
    status: Literal["ok", "done", "no_history"]
    p50: date | None
    p80: date | None
    p95: date | None
    due_on: date | None  # the project's own due date, for comparison
    risk_score: float
    risk_level: Literal["none", "low", "medium", "high"]
    drivers: list[DriverOut]
    inputs: dict[str, Any]


class ProjectForecastOut(BaseModel):
    forecast: ForecastOut | None
