from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class WeekLoadOut(BaseModel):
    week_start: date
    capacity_minutes: int
    override: bool = Field(description="This week's capacity was set for this week (e.g. time off)")
    planned_minutes: int
    task_count: int
    unestimated: int = Field(description="Tasks this week with no effort estimate")


class PersonLoadOut(BaseModel):
    user_id: uuid.UUID | None = Field(description="Null for the unassigned row")
    name: str
    avatar_url: str | None = None
    weekly_minutes: int
    hours_source: Literal["person", "workspace", "setting"]
    can_edit: bool = Field(description="You can change this person's hours (yourself, or admin)")
    no_date: int = Field(description="Open tasks you can see with no due date (not placed)")
    hidden: int = Field(description="Open tasks in projects you can't see (counted, not named)")
    weeks: list[WeekLoadOut]


class WorkloadTaskOut(BaseModel):
    id: uuid.UUID
    number: int
    title: str
    assignee_id: uuid.UUID | None
    start_on: date | None
    due_on: date
    estimate_minutes: int | None
    project_id: uuid.UUID
    project_name: str
    overdue: bool
    version: int
    weeks: dict[str, int] = Field(description="Minutes of this task in each week it touches")


class WorkloadOut(BaseModel):
    start: date
    weeks: list[date]
    default_minutes: int
    default_source: Literal["workspace", "setting"]
    can_admin: bool
    people: list[PersonLoadOut]
    unassigned: PersonLoadOut
    any_estimate: bool = Field(description="Any placed task has an effort estimate")
    tasks: list[WorkloadTaskOut] = Field(description="The placed tasks `tasks_for` asked for")


class HoursIn(BaseModel):
    hours: float | None = Field(
        default=None, ge=0, le=80, description="Hours per week; null = back to the default"
    )


class HoursOut(BaseModel):
    hours: float | None
