from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

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
    # Phase 7.5 (spec §5.2): lifecycle settings; `my_role` is owner|admin|editor|viewer|null
    kind: str = "manual"
    rule: dict[str, Any] | None = None
    stage_field_id: uuid.UUID | None = None
    stage_targets: dict[str, Any] = Field(default_factory=dict)
    stage_gates: dict[str, Any] = Field(default_factory=dict)
    columns: list[dict[str, Any]] = Field(default_factory=list)
    my_role: str | None = None
    summary: PortfolioSummaryOut | None = None  # only with ?summaries=true (the list page)


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


# ---------------- Phase 7.5: portfolio v2 (spec §5.2-§5.6) ----------------

ConditionOp = Literal["is", "is_not", "any", "empty", "set", "gte", "lte"]
SortDir = Literal["asc", "desc"]


class FieldConditionIn(BaseModel):
    """A condition on a project field (rule membership and view filters)."""

    model_config = ConfigDict(extra="forbid")
    field_id: uuid.UUID
    op: ConditionOp = "is"
    value: Any = None


class PortfolioRuleIn(BaseModel):
    """Which projects a rule portfolio holds; every given criterion must hold."""

    model_config = ConfigDict(extra="forbid")
    template_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    team_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    project_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    project_field_conditions: list[FieldConditionIn] = Field(default_factory=list, max_length=10)
    include_completed: bool = False
    include_archived: bool = False


class GateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    required_fields: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    required_milestones: list[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    ] = Field(default_factory=list, max_length=20)
    required_files: list[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    ] = Field(default_factory=list, max_length=20)


class ColumnIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(max_length=60)
    visible: bool = True
    width: int | None = Field(default=None, ge=60, le=800)
    # waiting_on_customer only (spec §5.3): which task field and choice mean "waiting on the
    # customer" (default: a field named "Waiting on", choice "Customer")
    field_name: str | None = Field(default=None, max_length=100)
    option_label: str | None = Field(default=None, max_length=100)


class PortfolioConfigIn(BaseModel):
    """Phase 7.5: a portfolio's lifecycle settings (editors only). Omitted keys stay as they are."""

    model_config = ConfigDict(extra="forbid")
    rule: PortfolioRuleIn | None = None
    stage_field_id: uuid.UUID | None = None
    stage_targets: dict[str, Annotated[int, Field(ge=0, le=3650)]] | None = None
    stage_gates: dict[str, GateIn] | None = None
    columns: list[ColumnIn] | None = Field(default=None, max_length=60)


class ConvertIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["manual", "rule"]
    rule: PortfolioRuleIn | None = None


class SortIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(max_length=60)
    dir: SortDir = "asc"


class ViewFiltersIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str | None = Field(default=None, max_length=200)
    status: list[str] = Field(default_factory=list, max_length=10)
    owner_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    stage: list[str] = Field(default_factory=list, max_length=30)
    fields: list[FieldConditionIn] = Field(default_factory=list, max_length=10)
    overdue_only: bool = False


ViewLayout = Literal["table", "board", "timeline", "workload"]


class BulkSetFieldIn(BaseModel):
    """Phase 7.5 (spec §5.4): "Set field…" on the selected rows, one undo for all of them."""

    model_config = ConfigDict(extra="forbid")
    project_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    field_id: uuid.UUID
    value: Any = None


class BulkSetFieldOut(BaseModel):
    updated: int
    skipped: int  # projects the viewer can't edit, or not in the portfolio


class StageCount(BaseModel):
    option_id: str
    label: str
    count: int


class PortfolioSummaryOut(BaseModel):
    """The list page's card: count per stage (lifecycle order) and the total of the first
    currency column, as the viewer sees it."""

    portfolio_id: uuid.UUID
    stages: list[StageCount]
    value_field: str | None
    total_value: float | None


class PortfolioViewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    layout: ViewLayout = "table"
    filters: ViewFiltersIn = Field(default_factory=ViewFiltersIn)
    group_by: str | None = Field(default=None, max_length=80)
    sort: list[SortIn] = Field(default_factory=list, max_length=5)
    shared: bool = False


class PortfolioViewPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
        | None
    ) = None
    layout: ViewLayout | None = None
    filters: ViewFiltersIn | None = None
    group_by: str | None = Field(default=None, max_length=80)
    sort: list[SortIn] | None = Field(default=None, max_length=5)


class PortfolioViewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    owner_id: uuid.UUID | None
    shared: bool
    layout: str
    filters: dict[str, Any]
    group_by: str | None
    sort: list[dict[str, Any]]
    updated_at: datetime


class PortfolioMemberIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["editor", "viewer"]


class PortfolioMemberOut(BaseModel):
    user_id: uuid.UUID
    name: str
    role: str


class StageMoveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: str = Field(min_length=1, max_length=64)
    override: bool = False


class GateItemOut(BaseModel):
    kind: str
    label: str
    met: bool
    ref: dict[str, Any] | None


class ReadinessOut(BaseModel):
    stage: str
    stage_label: str
    met: bool
    items: list[GateItemOut]


class MilestoneRef(BaseModel):
    id: uuid.UUID
    title: str
    due_on: date | None


class StageRef(BaseModel):
    option_id: str
    label: str | None


class LatestUpdate(BaseModel):
    title: str
    at: datetime
    status: str


class PortfolioRowOut(BaseModel):
    """One project row of a portfolio v2 table, every built-in column (spec §5.3)."""

    id: uuid.UUID
    name: str
    color: str | None
    owner_id: uuid.UUID | None
    owner_name: str | None
    status: str | None
    template_id: uuid.UUID | None
    start_on: date | None
    due_on: date | None
    total_tasks: int
    completed_tasks: int
    open: int
    overdue: int
    progress: float | None
    blocked: int
    waiting_on_customer: int | None  # null: no "Waiting on" task field in the workspace
    next_milestone: MilestoneRef | None
    stage: StageRef | None
    stage_age_days: int | None
    stage_target_days: int | None
    target_date: date | None
    forecast_date: date | None
    slip_days: int | None
    latest_update: LatestUpdate | None
    fields: dict[str, Any]
    can_edit: bool = False  # the viewer may change this project's fields (project editor)


class PortfolioGroupOut(BaseModel):
    key: str | None
    label: str
    project_ids: list[uuid.UUID]
    rollup: dict[str, Any]


class ColumnOut(BaseModel):
    key: str
    label: str
    visible: bool
    width: int | None


class PortfolioRowsOut(BaseModel):
    columns: list[ColumnOut]
    rows: list[PortfolioRowOut]
    groups: list[PortfolioGroupOut] | None
    hidden_projects: int
    view_id: uuid.UUID | None


PortfolioOut.model_rebuild()
PortfolioDetailOut.model_rebuild()
