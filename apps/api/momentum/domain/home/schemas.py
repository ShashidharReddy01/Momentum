from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from momentum.domain.mytasks.schemas import MyTaskOut


class HomeCounts(BaseModel):
    open: int
    due_today: int
    overdue: int


class HomeProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    color: str | None
    team_id: uuid.UUID
    team_name: str
    open_count: int
    overdue_count: int
    last_active_at: datetime | None


class HomeOut(BaseModel):
    priorities: list[MyTaskOut]
    counts: HomeCounts
    recent_projects: list[HomeProjectOut]
    waiting: list[MyTaskOut]
    waiting_total: int
    has_projects: bool
