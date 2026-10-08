"""S6.5.1: the dashboard API shapes. ``query_spec`` v1 lives in ``spec.py`` (re-exported here) and
v2 in ``schemas_v2.py`` (Phase 7.5); a widget stores either (``AnySpec``), and both are **data,
never SQL**, run as the viewer.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from momentum.domain.dashboards.schemas_v2 import AnySpec, DashboardFilters, check_any
from momentum.domain.dashboards.spec import (
    FIELD_MEASURES,
    NONE_KEY,
    OTHER_KEY,
    STATUS_KEYS,
    AnyKind,
    GroupBy,
    Measure,
    Priority,
    QueryFilters,
    QuerySpec,
    TaskStatus,
    TimeBucket,
    TimeField,
    WidgetKind,
    WidgetSize,
    check_kind,
)

__all__ = [
    "FIELD_MEASURES",
    "NONE_KEY",
    "OTHER_KEY",
    "STATUS_KEYS",
    "AnyKind",
    "GroupBy",
    "Measure",
    "Priority",
    "QueryFilters",
    "QuerySpec",
    "TaskStatus",
    "TimeBucket",
    "TimeField",
    "WidgetKind",
    "WidgetSize",
    "check_kind",
]

KindIn = AnyKind  # a widget's kind: the v1 kinds draw v1 or v2 specs, the new ones v2 only


class WidgetQueryIn(BaseModel):
    """A spec to run without saving it (the add-chart preview, the starter dashboard)."""

    model_config = ConfigDict(extra="forbid")
    kind: KindIn
    query_spec: AnySpec
    project_id: uuid.UUID | None = Field(
        default=None, description="Run inside this project, as a project dashboard would"
    )
    filters: DashboardFilters | None = Field(
        default=None, description="Dashboard filters to apply (Phase 7.5)"
    )

    @model_validator(mode="after")
    def _kind(self) -> WidgetQueryIn:
        check_any(self.kind, self.query_spec)
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


class DrillAnyIn(BaseModel):
    """Phase 7.5: the drill for any spec. A v1 spec (no filters) drills exactly as ``DrillIn``;
    a v2 one returns tasks or projects, and ``key`` names a stage for stage analyses."""

    model_config = ConfigDict(extra="forbid")
    query_spec: AnySpec
    project_id: uuid.UUID | None = None
    key: str | None = Field(default=None, max_length=64)
    bucket_start: date | None = None
    limit: int = Field(default=100, ge=1, le=200)
    filters: DashboardFilters | None = None
    split_key: str | None = Field(
        default=None, max_length=64, description="A stacked bar's split value (its segment)"
    )

    @model_validator(mode="after")
    def _point(self) -> DrillAnyIn:
        spec: Any = self.query_spec
        if getattr(spec, "entity", "tasks") in ("tasks", "projects"):
            if self.key is not None and spec.group_by is None:
                raise ValueError("key needs a spec with group_by")
            if self.bucket_start is not None and spec.time_bucket is None:
                raise ValueError("bucket_start needs a spec with time_bucket")
        return self


class VizIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    size: WidgetSize = "md"


class WidgetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: KindIn
    title: str = Field(min_length=1, max_length=200)
    query_spec: AnySpec
    viz: VizIn = Field(default_factory=VizIn)
    created_from_prompt: str | None = Field(
        default=None, max_length=300, description="The question, when Mo drafted this chart"
    )

    @model_validator(mode="after")
    def _kind(self) -> WidgetIn:
        check_any(self.kind, self.query_spec)
        return self


class WidgetPatchIn(BaseModel):
    """Partial; a new ``kind`` or ``query_spec`` is checked against the other's current value."""

    model_config = ConfigDict(extra="forbid")
    kind: KindIn | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    query_spec: AnySpec | None = None
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
    portfolio_id: uuid.UUID | None = Field(
        default=None, description="Phase 7.5: make it this portfolio's Dashboard tab"
    )


class DashboardPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    filters: DashboardFilters | None = Field(
        default=None, description="Phase 7.5: the saved filters (editors)"
    )


class WidgetOut(BaseModel):
    id: uuid.UUID
    kind: KindIn
    title: str
    query_spec: AnySpec
    viz: VizIn
    version: int
    created_from_prompt: str | None = None


class StarterWidgetOut(BaseModel):
    """A widget of the starter layout, shown live before a dashboard is saved."""

    kind: KindIn
    title: str
    query_spec: AnySpec
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
    # Phase 7.5
    filters: DashboardFilters = Field(default_factory=lambda: DashboardFilters())
    portfolio_id: uuid.UUID | None = None
    template: str | None = None
    pinned: bool = False


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


class FilterNameOut(BaseModel):
    """A readable name for one value of a list filter (a project, section, person, tag or
    priority), so a chart can say what it is narrowed to and the editor can show it. A value the
    viewer can't see is named generically, never by its real name."""

    filter: Literal["project_ids", "section_ids", "assignees", "tag_ids", "priorities", "fields"]
    key: str
    label: str


class StackOut(BaseModel):
    """Phase 7.5: one split value of a stacked bar; ``values`` line up with ``groups``."""

    key: str
    label: str
    color: str | None = None
    values: list[float]


class StageStatOut(BaseModel):
    """Phase 7.5: one stage of a funnel, time-in-stage or aging analysis."""

    option_id: str
    label: str
    count: int = 0  # funnel: reached it; time in stage: stays that ended; aging: in it now
    conversion: float | None = None  # funnel: share of the previous stage's count
    median_days: float | None = None
    p75_days: float | None = None
    p90_days: float | None = None
    target_days: int | None = None
    buckets: list[int] = Field(default_factory=list)  # aging: 0-7, 8-14, 15-30, 31-60, 60+
    breaches: int = 0  # aging: past the stage's target


class TimelineItemOut(BaseModel):
    """Phase 7.5: one dated thing on a projects timeline widget."""

    date: date
    kind: Literal["milestone", "target", "go_live"]
    title: str
    project_id: uuid.UUID
    project_name: str


class QueryResultOut(BaseModel):
    """One widget's numbers, computed as the viewer. ``value`` for a count, ``groups`` for a bar
    or donut, ``series`` for a line, ``tasks`` for a list; ``total`` and ``tasks_total`` cover
    everything matched; ``unestimated`` counts matched tasks with no estimate (``sum_estimate``)
    or no value in the measured field (``sum_field`` / ``avg_field``)."""

    kind: AnyKind
    measure: str
    description: str
    value: float | None = None
    total: float
    tasks_total: int
    unestimated: int = 0
    groups: list[GroupOut] = Field(default_factory=list)
    series: list[PointOut] = Field(default_factory=list)
    tasks: list[TaskRowOut] = Field(default_factory=list)
    more: int = 0  # list rows past the limit
    filter_names: list[FilterNameOut] = Field(default_factory=list)
    field_name: str | None = None  # the custom field a group_by 'field' chart splits by
    measure_field_name: str | None = None  # the number field a sum_field/avg_field adds up
    # Phase 7.5 (v2 specs; absent from v1 results' meaning, empty there)
    entity: str = "tasks"
    previous: float | None = None  # KPI: the previous period, when asked to compare
    target: float | None = None  # KPI: its target
    stacks: list[StackOut] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)  # projects table
    columns: list[str] = Field(default_factory=list)  # projects table, in order
    stages: list[StageStatOut] = Field(default_factory=list)
    timeline: list[TimelineItemOut] = Field(default_factory=list)
    text: str | None = None  # note
    notes: list[str] = Field(default_factory=list)  # what the numbers leave out, in words
    computed_at: datetime


class DrillProjectOut(BaseModel):
    """Phase 7.5: one project behind a projects or stage widget's mark."""

    id: uuid.UUID
    name: str
    color: str | None = None
    status: str | None = None
    owner_name: str | None = None
    stage: str | None = None


class DrillOut(BaseModel):
    label: str
    tasks: list[TaskRowOut]
    total: int
    entity: str = "tasks"
    projects: list[DrillProjectOut] = Field(default_factory=list)
    records: list[dict[str, Any]] = Field(default_factory=list)  # Phase 7.6: records widgets


# ---------- Phase 7.5: templates, the portfolio tab, members ----------


class DashboardTemplateOut(BaseModel):
    key: str
    name: str
    description: str
    persona: str
    widgets: list[str]


class FromTemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template: str = Field(min_length=1, max_length=40)
    portfolio_id: uuid.UUID
    name: str | None = Field(default=None, max_length=200)
    portfolio_tab: bool = Field(
        default=False, description="Make it the portfolio's Dashboard tab (its editors)"
    )


class TemplateWidgetOut(BaseModel):
    kind: KindIn
    title: str
    query_spec: AnySpec
    viz: VizIn


class TemplatePreviewOut(BaseModel):
    """A template bound to a portfolio: its widgets and what was left out (in words)."""

    template: str
    name: str
    description: str
    filters: DashboardFilters
    widgets: list[TemplateWidgetOut]
    notes: list[str]


class FromDraftIn(BaseModel):
    """S75-10: create the dashboard Mo drafted from a sentence (after its preview), in one step.
    The widgets are checked again like any hand-built ones."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    filters: DashboardFilters = Field(default_factory=DashboardFilters)
    widgets: list[WidgetIn] = Field(min_length=1, max_length=12)
    prompt: str = Field(min_length=1, max_length=300, description="The sentence Mo drafted it from")


class FromTemplateOut(BaseModel):
    dashboard: DashboardDetailOut
    notes: list[str]


class PortfolioDashboardOut(BaseModel):
    """A portfolio's Dashboard tab: its dashboard (or none yet) and whether the viewer can make
    or edit it."""

    dashboard: DashboardDetailOut | None
    can_edit: bool


class MemberIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["editor", "viewer"]


class MemberOut(BaseModel):
    user_id: uuid.UUID
    name: str
    role: Literal["editor", "viewer"]
