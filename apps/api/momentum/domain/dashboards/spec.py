"""S6.5.1: ``query_spec`` version 1 (moved here from ``schemas.py`` in Phase 7.5 so version 2,
``schemas_v2.py``, can build on it; ``schemas.py`` re-exports every name).

A query spec is **data, never SQL**: every field is an enum, a bounded number, a date, or a typed
id, and ``query.py`` turns it into SQLAlchemy expressions with the viewer's visibility clause
applied first. Unknown keys are refused (``extra='forbid'``), so a spec can't smuggle anything in.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from momentum.domain.fields.filters import FieldFilter

WidgetKind = Literal["count", "bar", "line", "donut", "list"]
# Phase 7.5 (spec §7.2): every kind a result or a stored widget may have (v2 specs draw them)
AnyKind = Literal[
    "count",
    "bar",
    "line",
    "donut",
    "list",
    "kpi",
    "stacked_bar",
    "table",
    "funnel",
    "stage_time",
    "aging",
    "timeline",
    "note",
]
GroupBy = Literal["assignee", "section", "project", "status", "priority", "tag", "field"]
Measure = Literal["count", "sum_estimate", "sum_field", "avg_field"]
FIELD_MEASURES = ("sum_field", "avg_field")
TimeBucket = Literal["day", "week", "month"]
TimeField = Literal["completed", "created", "due", "field"]
TaskStatus = Literal["open", "completed", "all"]
Priority = Literal["urgent", "high", "medium", "low", "none"]
WidgetSize = Literal["sm", "md", "lg"]

# grouping keys that aren't ids
NONE_KEY = "none"  # unassigned / no priority / no tag / no value
OTHER_KEY = "other"  # the groups past ``limit``, folded together
# ``group_by='status'``: where open work stands against its due date, plus done
STATUS_KEYS = ("overdue", "due_soon", "later", "no_date", "completed")


class QueryFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TaskStatus = "open"
    project_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=50, description="Only these projects (workspace scope)"
    )
    section_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    assignees: list[str] = Field(
        default_factory=list,
        max_length=50,
        description='User ids, "me" (whoever is viewing) or "none" (unassigned)',
    )
    tag_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    priorities: list[Priority] = Field(default_factory=list, max_length=5)
    overdue: bool = Field(default=False, description="Open tasks due before today")
    blocked: bool = Field(default=False, description="Open tasks waiting on an open blocker")
    due_within_days: int | None = Field(
        default=None, ge=0, le=366, description="Due between today and today + N days"
    )
    completed_within_days: int | None = Field(
        default=None, ge=1, le=366, description="Completed in the last N days (today included)"
    )
    due_from: date | None = None
    due_to: date | None = None
    fields: list[FieldFilter] = Field(
        default_factory=list,
        max_length=10,
        description="Custom-field conditions, all of which must hold (S7.4.1)",
    )

    @field_validator("assignees")
    @classmethod
    def _assignees(cls, v: list[str]) -> list[str]:
        for a in v:
            if a in ("me", NONE_KEY):
                continue
            try:
                uuid.UUID(a)
            except ValueError:
                raise ValueError(f'"{a}" is not a user id, "me" or "none"') from None
        return v

    @model_validator(mode="after")
    def _consistent(self) -> QueryFilters:
        if self.due_from and self.due_to and self.due_from > self.due_to:
            raise ValueError("due_from must be on or before due_to")
        if self.completed_within_days is not None and self.status == "open":
            raise ValueError("completed_within_days needs status 'completed' or 'all'")
        if (self.overdue or self.blocked) and self.status == "completed":
            raise ValueError("overdue and blocked only apply to open tasks")
        return self


class QuerySpec(BaseModel):
    """What a widget shows: which tasks (``filters``), one dimension (``group_by`` *or*
    ``time_bucket``), and a ``measure``. Always top-level tasks the viewer can see."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    entity: Literal["tasks"] = "tasks"
    filters: QueryFilters = Field(default_factory=QueryFilters)
    group_by: GroupBy | None = None
    field_id: uuid.UUID | None = Field(
        default=None,
        description="The custom field to split by when group_by is 'field' (single- or "
        "multi-select, people, checkbox)",
    )
    measure: Measure = "count"
    measure_field_id: uuid.UUID | None = Field(
        default=None,
        description="The number, currency or percent field summed or averaged (measure "
        "'sum_field' / 'avg_field')",
    )
    time_bucket: TimeBucket | None = None
    time_field: TimeField = Field(
        default="completed", description="Which date places a task in a time bucket"
    )
    time_field_id: uuid.UUID | None = Field(
        default=None, description="The custom date field when time_field is 'field'"
    )
    window_days: int = Field(
        default=84, ge=7, le=366, description="How far back (or ahead, for due) a series goes"
    )
    limit: int = Field(
        default=8, ge=1, le=50, description="Groups shown (the rest fold into Other) or list rows"
    )

    @model_validator(mode="after")
    def _consistent(self) -> QuerySpec:
        if (self.group_by == "field") != (self.field_id is not None):
            raise ValueError("field_id goes with group_by 'field' (and only with it)")
        if (self.measure in FIELD_MEASURES) != (self.measure_field_id is not None):
            raise ValueError("measure_field_id goes with measure sum_field/avg_field (only)")
        if (self.time_field == "field") != (self.time_field_id is not None):
            raise ValueError("time_field_id goes with time_field 'field' (and only with it)")
        if self.group_by is not None and self.time_bucket is not None:
            raise ValueError("Pick one dimension: group_by or time_bucket")
        if (
            self.time_bucket is not None
            and self.time_field == "completed"
            and self.filters.status == "open"
        ):
            raise ValueError("A completed-over-time series needs status 'completed' or 'all'")
        return self


def check_kind(kind: WidgetKind, spec: QuerySpec) -> None:
    """Which specs a widget kind can draw; raises ``ValueError`` with a readable reason."""
    if kind in ("bar", "donut") and spec.group_by is None:
        raise ValueError(f"A {kind} chart needs group_by")
    if kind == "line" and spec.time_bucket is None:
        raise ValueError("A line chart needs time_bucket")
    if kind in ("count", "list") and (spec.group_by or spec.time_bucket):
        raise ValueError(f"A {kind} widget has no group_by or time_bucket")
    if kind == "list" and spec.measure != "count":
        raise ValueError("A list widget lists tasks (measure 'count')")
