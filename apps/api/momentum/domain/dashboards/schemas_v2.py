"""Phase 7.5 (spec §7.1-§7.3): ``query_spec`` version 2, the new widget kinds, dashboard filters.

Version 1 specs (``schemas.QuerySpec``) keep working unchanged. A version 2 spec names an
``entity``: ``tasks`` (v1 plus ``split_by`` and a portfolio), ``projects`` (one row per visible
project), ``stage_events`` (lifecycle analytics over a portfolio's stage field), ``snapshots``
(a time series from ``project_snapshots``), or ``note`` (text, no data). Like v1, every field is
an enum, a bounded number, a date or a typed id (``extra='forbid'``), and every query applies
the viewer's visibility first.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from momentum.domain.dashboards.spec import (
    GroupBy,
    Measure,
    QueryFilters,
    QuerySpec,
    TimeBucket,
    TimeField,
    WidgetKind,
    check_kind,
)
from momentum.domain.records.query import Filter as RecordFilter

WidgetKindV2 = Literal[
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
ConditionOp = Literal["is", "is_not", "any", "empty", "set", "gte", "lte"]
Period = Literal["this_week", "this_month", "last_30_days", "this_quarter", "custom"]
SpecPeriod = Literal["this_week", "this_month", "last_30_days", "this_quarter"]
ProjectGroupBy = Literal["project_field", "owner", "status", "team", "stage"]
ProjectMeasure = Literal[
    "count",
    "sum_project_field",
    "avg_project_field",
    "avg_progress",
    "sum_open_tasks",
    "sum_overdue_tasks",
]
PROJECT_FIELD_MEASURES = ("sum_project_field", "avg_project_field")
ProjectTimeField = Literal["created", "project_field", "stage_entered"]
Analysis = Literal["funnel", "time_in_stage", "throughput", "aging"]
SnapshotMetric = Literal["open", "overdue", "progress_avg", "sum_project_field"]
ProjectColumn = Literal[
    "name",
    "owner",
    "status",
    "stage",
    "progress",
    "open",
    "overdue",
    "blocked",
    "waiting_on_customer",
    "next_milestone",
    "target_date",
    "forecast_date",
    "slip_days",
    "stage_age_days",
    "latest_update",
]
AGING_BUCKETS = ((0, 7), (8, 14), (15, 30), (31, 60), (61, None))


def _person(v: str) -> str:
    if v == "me":
        return v
    try:
        uuid.UUID(v)
    except ValueError:
        raise ValueError(f'"{v}" is not a user id or "me"') from None
    return v


class ProjectCondition(BaseModel):
    """A condition on a project field (as in portfolio rules). ``value`` may be ``"me"`` for a
    people field (the viewer)."""

    model_config = ConfigDict(extra="forbid")
    field_id: uuid.UUID
    op: ConditionOp = "is"
    value: Any = None


class ProjectFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    portfolio_id: uuid.UUID | None = None
    fields: list[ProjectCondition] = Field(default_factory=list, max_length=10)
    status: list[Literal["on_track", "at_risk", "off_track", "on_hold", "complete", "none"]] = (
        Field(default_factory=list, max_length=6)
    )
    owner: list[str] = Field(default_factory=list, max_length=20, description='User ids or "me"')
    assignee: list[str] = Field(
        default_factory=list,
        max_length=20,
        description='Projects with open tasks assigned to these people (user ids or "me")',
    )
    template_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    team_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    include_completed: bool = False
    slipping: bool = Field(default=False, description="Forecast (P80) past the target date")
    has_blocked: bool = False
    has_waiting_on_customer: bool = False
    at_risk: bool = Field(
        default=False, description="Status at risk or off track, or slipping (any of them)"
    )

    @field_validator("owner", "assignee")
    @classmethod
    def _owners(cls, v: list[str]) -> list[str]:
        return [_person(x) for x in v]


class TaskFiltersV2(QueryFilters):
    """v1 task filters plus a portfolio and project-field conditions (tasks of the matching
    projects the viewer can see)."""

    portfolio_id: uuid.UUID | None = None
    project_fields: list[ProjectCondition] = Field(default_factory=list, max_length=10)


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[2]
    compare_previous: bool = Field(
        default=False, description="KPI: compare with the previous period of the same length"
    )
    target: float | None = Field(default=None, ge=0, description="KPI: a target (progress ring)")
    period: SpecPeriod | None = Field(
        default=None,
        description="The window as a calendar period (a dashboard period replaces it)",
    )


class TasksSpec(_Base):
    entity: Literal["tasks"]
    filters: TaskFiltersV2 = Field(default_factory=TaskFiltersV2)
    group_by: GroupBy | None = None
    field_id: uuid.UUID | None = None
    split_by: Literal["field", "priority"] | None = None
    split_field_id: uuid.UUID | None = None
    measure: Measure = "count"
    measure_field_id: uuid.UUID | None = None
    time_bucket: TimeBucket | None = None
    time_field: TimeField = "completed"
    time_field_id: uuid.UUID | None = None
    window_days: int = Field(default=84, ge=7, le=366)
    limit: int = Field(default=8, ge=1, le=50)

    @model_validator(mode="after")
    def _consistent(self) -> TasksSpec:
        if (self.split_by == "field") != (self.split_field_id is not None):
            raise ValueError("split_field_id goes with split_by 'field' (and only with it)")
        if self.split_by is not None and self.group_by is None:
            raise ValueError("split_by needs a group_by")
        self.to_v1()  # every v1 rule holds too
        return self

    def to_v1(self, project_ids: list[uuid.UUID] | None = None) -> QuerySpec:
        """The same question as a v1 spec (a portfolio becomes its visible project ids)."""
        data = self.model_dump(
            exclude={
                "version",
                "entity",
                "split_by",
                "split_field_id",
                "compare_previous",
                "target",
                "period",
            }
        )
        filters = dict(data.pop("filters"))
        filters.pop("portfolio_id", None)
        filters.pop("project_fields", None)
        spec = QuerySpec.model_validate({**data, "filters": filters})
        if project_ids is not None:
            # a portfolio can hold more projects than a v1 filter list allows: set, not validated
            spec.filters = spec.filters.model_copy(update={"project_ids": project_ids})
        return spec


class ProjectsSpec(_Base):
    entity: Literal["projects"]
    filters: ProjectFilters = Field(default_factory=ProjectFilters)
    group_by: ProjectGroupBy | None = None
    field_id: uuid.UUID | None = Field(default=None, description="group_by project_field")
    measure: ProjectMeasure = "count"
    measure_field_id: uuid.UUID | None = None
    time_bucket: TimeBucket | None = None
    time_field: ProjectTimeField = "created"
    time_field_id: uuid.UUID | None = Field(default=None, description="time_field project_field")
    stage_option_id: str | None = Field(default=None, max_length=64)
    window_days: int = Field(default=84, ge=7, le=730)
    ahead_days: int | None = Field(
        default=None, ge=1, le=366, description="timeline: dates from today to today + N days"
    )
    columns: list[ProjectColumn | str] = Field(default_factory=list, max_length=15)
    sort: str | None = Field(default=None, max_length=60)
    limit: int = Field(default=8, ge=1, le=50)

    @model_validator(mode="after")
    def _consistent(self) -> ProjectsSpec:
        if (self.group_by == "project_field") != (self.field_id is not None):
            raise ValueError("field_id goes with group_by 'project_field' (and only with it)")
        if (self.measure in PROJECT_FIELD_MEASURES) != (self.measure_field_id is not None):
            raise ValueError("measure_field_id goes with sum/avg_project_field (only)")
        if (self.time_field == "project_field") != (self.time_field_id is not None):
            raise ValueError("time_field_id goes with time_field 'project_field' (only)")
        if (self.time_field == "stage_entered") != (self.stage_option_id is not None):
            raise ValueError("stage_option_id goes with time_field 'stage_entered' (only)")
        if self.group_by is not None and self.time_bucket is not None:
            raise ValueError("Pick one dimension: group_by or time_bucket")
        if self.group_by == "stage" and self.filters.portfolio_id is None:
            raise ValueError("group_by 'stage' needs a portfolio (its stage field)")
        for c in self.columns:
            if c not in ProjectColumn.__args__ and not str(c).startswith("field:"):  # type: ignore[attr-defined]
                raise ValueError(f"Unknown column {c}")
        return self


class StageSpec(_Base):
    entity: Literal["stage_events"]
    portfolio_id: uuid.UUID
    analysis: Analysis
    stages: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Only these stage option ids (all if empty)",
    )
    window_days: int = Field(default=180, ge=7, le=730)
    time_bucket: TimeBucket = "month"
    owner: list[str] = Field(default_factory=list, max_length=20)
    fields: list[ProjectCondition] = Field(default_factory=list, max_length=10)

    @field_validator("owner")
    @classmethod
    def _owners(cls, v: list[str]) -> list[str]:
        return [_person(x) for x in v]


class SnapshotSpec(_Base):
    entity: Literal["snapshots"]
    portfolio_id: uuid.UUID
    metric: SnapshotMetric
    field_id: uuid.UUID | None = None
    owner: list[str] = Field(default_factory=list, max_length=20)
    fields: list[ProjectCondition] = Field(default_factory=list, max_length=10)
    time_bucket: TimeBucket = "week"
    window_days: int = Field(default=84, ge=7, le=730)

    @field_validator("owner")
    @classmethod
    def _owners(cls, v: list[str]) -> list[str]:
        return [_person(x) for x in v]

    @model_validator(mode="after")
    def _consistent(self) -> SnapshotSpec:
        if (self.metric == "sum_project_field") != (self.field_id is not None):
            raise ValueError("field_id goes with metric sum_project_field (only)")
        return self


class RecordsSpec(_Base):
    """Phase 7.6 S76-04 (spec §6.6): records of one type (``records``) or their list items
    (``record_lines``, with ``array``). Money measures come out per currency."""

    entity: Literal["records", "record_lines"]
    type: str = Field(min_length=1, max_length=60)
    array: str | None = Field(default=None, pattern=r"^[a-z_][a-z0-9_]*$")
    project_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    status: list[str] = Field(default_factory=list, max_length=7)
    filters: list[RecordFilter] = Field(default_factory=list, max_length=10)
    group_by: str | None = Field(default=None, max_length=200, description="A field path")
    time_bucket: TimeBucket | None = None
    time_path: str = Field(default="occurred_on", max_length=200)
    measure: Literal["count", "sum", "avg", "min", "max"] = "count"
    measure_path: str | None = Field(default=None, max_length=200)
    window_days: int = Field(default=365, ge=7, le=730)
    limit: int = Field(default=8, ge=1, le=50)

    @model_validator(mode="after")
    def _consistent(self) -> RecordsSpec:
        if (self.entity == "record_lines") != (self.array is not None):
            raise ValueError("record_lines widgets name their array (and only they do)")
        if (self.measure == "count") != (self.measure_path is None):
            raise ValueError("count takes no measure_path; sum, avg, min and max need one")
        if self.group_by is not None and self.time_bucket is not None:
            raise ValueError("Pick one dimension: group_by or time_bucket")
        return self


class NoteSpec(_Base):
    entity: Literal["note"]
    text: str = Field(min_length=1, max_length=4000, description="Markdown, shown as text")


SpecV2 = Annotated[
    TasksSpec | ProjectsSpec | StageSpec | SnapshotSpec | RecordsSpec | NoteSpec,
    Field(discriminator="entity"),
]
AnySpec = QuerySpec | SpecV2

# which kinds each entity draws
KIND_ENTITIES: dict[str, tuple[str, ...]] = {
    "count": ("tasks", "projects", "records", "record_lines"),
    "kpi": ("tasks", "projects", "stage_events", "snapshots", "records", "record_lines"),
    "bar": ("tasks", "projects", "snapshots", "records", "record_lines"),
    "donut": ("tasks", "projects", "records", "record_lines"),
    "line": ("tasks", "projects", "stage_events", "snapshots", "records", "record_lines"),
    "stacked_bar": ("tasks",),
    "list": ("tasks",),
    "table": ("tasks", "projects"),
    "funnel": ("stage_events",),
    "stage_time": ("stage_events",),
    "aging": ("stage_events",),
    "timeline": ("projects",),
    "note": ("note",),
}


def entity_of(spec: QuerySpec | Any) -> str:
    return str(getattr(spec, "entity", "tasks"))


def check_kind_v2(kind: str, spec: Any) -> None:
    """Which v2 specs a widget kind can draw; raises ``ValueError`` with a readable reason."""
    entity = entity_of(spec)
    if entity not in KIND_ENTITIES.get(kind, ()):
        raise ValueError(f"A {kind} widget can't show {entity}")
    if isinstance(spec, StageSpec):
        wanted = {"funnel": "funnel", "stage_time": "time_in_stage", "aging": "aging"}.get(kind)
        if wanted and spec.analysis != wanted:
            raise ValueError(f"A {kind} widget shows the {wanted} analysis")
        if kind == "kpi" and spec.analysis not in ("throughput", "time_in_stage"):
            raise ValueError("A KPI over stages counts throughput or a median time in stage")
        if kind == "line" and spec.analysis != "throughput":
            raise ValueError("A line over stages shows throughput")
    if isinstance(spec, TasksSpec | ProjectsSpec | RecordsSpec):
        grouped = spec.group_by is not None
        timed = spec.time_bucket is not None
        if kind in ("bar", "donut", "stacked_bar") and not grouped:
            raise ValueError(f"A {kind} chart needs group_by")
        if kind == "line" and not timed:
            raise ValueError("A line chart needs time_bucket")
        if kind in ("kpi", "count", "table", "list", "timeline") and (grouped or timed):
            raise ValueError(f"A {kind} widget has no group_by or time_bucket")
        if kind == "stacked_bar" and getattr(spec, "split_by", None) is None:
            raise ValueError("A stacked bar needs split_by")
    if isinstance(spec, SnapshotSpec) and kind == "bar":
        raise ValueError("Snapshots draw as a line or a KPI")


class DashboardFilters(BaseModel):
    """Saved on a dashboard (editors) or passed for one view (anyone): applied to every widget
    whose entity supports them. ``owner: ["me"]`` makes one dashboard serve every person."""

    model_config = ConfigDict(extra="forbid")
    portfolio_id: uuid.UUID | None = None
    period: Period | None = None
    period_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    period_to: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    owner: list[str] = Field(default_factory=list, max_length=5)
    assignee: list[str] = Field(default_factory=list, max_length=5)
    fields: list[ProjectCondition] = Field(default_factory=list, max_length=5)

    @field_validator("owner", "assignee")
    @classmethod
    def _people(cls, v: list[str]) -> list[str]:
        return [_person(x) for x in v]

    @model_validator(mode="after")
    def _custom(self) -> DashboardFilters:
        if (self.period == "custom") != (
            self.period_from is not None and self.period_to is not None
        ):
            raise ValueError("A custom period needs period_from and period_to (and only then)")
        return self


def check_any(kind: str, spec: Any) -> None:
    """A v1 spec draws the v1 kinds (``check_kind``); a v2 spec what its entity allows."""
    if isinstance(spec, QuerySpec):
        if kind not in WidgetKind.__args__:  # type: ignore[attr-defined]
            raise ValueError(f"A {kind} widget needs a version 2 spec")
        check_kind(kind, spec)  # type: ignore[arg-type]
    else:
        check_kind_v2(kind, spec)
