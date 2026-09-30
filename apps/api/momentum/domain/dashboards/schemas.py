"""S6.5.1: the dashboard API shapes and ``query_spec`` v1.

A query spec is **data, never SQL**: every field is an enum, a bounded number, a date, or a typed
id, and ``query.py`` turns it into SQLAlchemy expressions with the viewer's visibility clause
applied first. Unknown keys are refused (``extra='forbid'``), so a spec can't smuggle anything in,
and S6.5.2's "ask for a chart" produces the same model.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

WidgetKind = Literal["count", "bar", "line", "donut", "list"]
GroupBy = Literal["assignee", "section", "project", "status", "priority", "tag", "field"]
Measure = Literal["count", "sum_estimate"]
TimeBucket = Literal["day", "week", "month"]
TimeField = Literal["completed", "created", "due"]
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
        default=None, description="The single-select custom field when group_by is 'field'"
    )
    measure: Measure = "count"
    time_bucket: TimeBucket | None = None
    time_field: TimeField = Field(
        default="completed", description="Which date places a task in a time bucket"
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


class WidgetQueryIn(BaseModel):
    """A spec to run without saving it (the add-chart preview, the starter dashboard)."""

    model_config = ConfigDict(extra="forbid")
    kind: WidgetKind
    query_spec: QuerySpec
    project_id: uuid.UUID | None = Field(
        default=None, description="Run inside this project, as a project dashboard would"
    )

    @model_validator(mode="after")
    def _kind(self) -> WidgetQueryIn:
        check_kind(self.kind, self.query_spec)
        return self


class DrillIn(BaseModel):
    """The tasks behind one bar, slice, point or tile: the same spec narrowed to one group
    (``key``) or one time bucket (``bucket_start``)."""

    model_config = ConfigDict(extra="forbid")
    query_spec: QuerySpec
    project_id: uuid.UUID | None = None
    key: str | None = Field(default=None, max_length=64)
    bucket_start: date | None = None
    limit: int = Field(default=100, ge=1, le=200)

    @model_validator(mode="after")
    def _point(self) -> DrillIn:
        if self.key is not None and self.query_spec.group_by is None:
            raise ValueError("key needs a spec with group_by")
        if self.bucket_start is not None and self.query_spec.time_bucket is None:
            raise ValueError("bucket_start needs a spec with time_bucket")
        return self


class VizIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    size: WidgetSize = "md"


class WidgetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: WidgetKind
    title: str = Field(min_length=1, max_length=200)
    query_spec: QuerySpec
    viz: VizIn = Field(default_factory=VizIn)

    @model_validator(mode="after")
    def _kind(self) -> WidgetIn:
        check_kind(self.kind, self.query_spec)
        return self


class WidgetPatchIn(BaseModel):
    """Partial; a new ``kind`` or ``query_spec`` is checked against the other's current value."""

    model_config = ConfigDict(extra="forbid")
    kind: WidgetKind | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    query_spec: QuerySpec | None = None
    viz: VizIn | None = None


class WidgetMoveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    before_id: uuid.UUID | None = None
    after_id: uuid.UUID | None = None


class DashboardIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    project_id: uuid.UUID | None = Field(
        default=None, description="Set for a project's Dashboard tab; omit for a workspace one"
    )
    starter: bool = Field(default=True, description="Start with the starter widgets")


class DashboardPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class WidgetOut(BaseModel):
    id: uuid.UUID
    kind: WidgetKind
    title: str
    query_spec: QuerySpec
    viz: VizIn
    version: int


class StarterWidgetOut(BaseModel):
    """A widget of the starter layout, shown live before a dashboard is saved."""

    kind: WidgetKind
    title: str
    query_spec: QuerySpec
    viz: VizIn


class DashboardOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    scope: Literal["project", "workspace"]
    project_id: uuid.UUID | None
    owner_id: uuid.UUID
    version: int
    can_edit: bool
    widget_count: int
    created_at: datetime
    updated_at: datetime


class DashboardDetailOut(DashboardOut):
    widgets: list[WidgetOut]


class ProjectDashboardOut(BaseModel):
    """A project's Dashboard tab: its saved dashboard, or none yet plus the starter layout."""

    dashboard: DashboardDetailOut | None
    starter: list[StarterWidgetOut]
    can_edit: bool


class GroupOut(BaseModel):
    key: str
    label: str
    value: float
    tasks: int
    color: str | None = None  # the entity's own colour token (project, tag, option)


class PointOut(BaseModel):
    start: date
    end: date  # last day in the bucket (inclusive)
    value: float
    tasks: int


class TaskRowOut(BaseModel):
    id: uuid.UUID
    key: str
    title: str
    assignee_id: uuid.UUID | None
    assignee_name: str | None
    due_on: date | None
    completed_at: datetime | None
    estimate_minutes: int | None
    project_id: uuid.UUID | None
    project_name: str | None
    project_color: str | None


class QueryResultOut(BaseModel):
    """One widget's numbers, computed as the viewer. ``value`` for a count, ``groups`` for a bar
    or donut, ``series`` for a line, ``tasks`` for a list; ``total`` and ``tasks_total`` cover
    everything matched; ``unestimated`` counts matched tasks with no estimate when the measure
    is ``sum_estimate``."""

    kind: WidgetKind
    measure: Measure
    description: str
    value: float | None = None
    total: float
    tasks_total: int
    unestimated: int = 0
    groups: list[GroupOut] = Field(default_factory=list)
    series: list[PointOut] = Field(default_factory=list)
    tasks: list[TaskRowOut] = Field(default_factory=list)
    more: int = 0  # list rows past the limit
    computed_at: datetime


class DrillOut(BaseModel):
    label: str
    tasks: list[TaskRowOut]
    total: int
