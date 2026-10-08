"""Phase 7.5 (spec §6.1): what a report is about, as data. Like a dashboard spec, every field is an
enum, a bounded number, a date or a typed id (``extra='forbid'``), so a spec drafted by Mo is the
same model a person submits."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from momentum.domain.dashboards.spec import QueryFilters

Kind = Literal[
    "project_status",
    "portfolio_status",
    "task_export",
    "customer_status",
    "closeout",
    "dashboard",
    "records_export",  # Phase 7.6 S76-04
]
Format = Literal["docx", "xlsx", "pdf", "md", "csv"]
Audience = Literal["internal", "customer"]

# spec §6.2: which formats each kind renders, and its sections in order
FORMATS: dict[str, tuple[str, ...]] = {
    "project_status": ("docx", "pdf", "md"),
    "portfolio_status": ("docx", "pdf", "xlsx"),
    "task_export": ("xlsx", "csv"),
    "customer_status": ("docx", "pdf"),
    "closeout": ("docx", "pdf"),
    "dashboard": ("pdf", "docx"),
    "records_export": ("xlsx", "csv"),
}
SECTIONS: dict[str, tuple[str, ...]] = {
    "project_status": (
        "kpis",
        "status",
        "milestones",
        "completed",
        "upcoming",
        "overdue",
        "risks",
        "narrative",
    ),
    "portfolio_status": ("kpis", "stages", "at_risk", "go_lives", "slipping", "narrative"),
    "task_export": ("summary", "tasks"),
    "customer_status": ("progress", "milestones", "needs", "next_steps", "narrative"),
    "closeout": (
        "planned_actual",
        "scope",
        "milestone_slips",
        "stages",
        "blockers",
        "workload",
        "narrative",
    ),
    "dashboard": ("widgets",),
    "records_export": ("records",),
}
NARRATIVE_DEFAULT = {"project_status", "customer_status", "closeout", "portfolio_status"}
SCOPES: dict[str, tuple[str, ...]] = {
    "project_status": ("project",),
    "portfolio_status": ("portfolio",),
    "task_export": ("project", "portfolio", "filters"),
    "customer_status": ("project",),
    "closeout": ("project",),
    "dashboard": ("dashboard",),
    "records_export": ("project", "portfolio"),
}


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: uuid.UUID | None = None
    portfolio_id: uuid.UUID | None = None
    dashboard_id: uuid.UUID | None = None

    def which(self) -> str:
        set_ = [k for k in ("project", "portfolio", "dashboard") if getattr(self, f"{k}_id")]
        return set_[0] if len(set_) == 1 else ("filters" if not set_ else "many")


class Period(BaseModel):
    start: date = Field(alias="from")
    end: date = Field(alias="to")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @model_validator(mode="after")
    def _order(self) -> Period:
        if self.start > self.end:
            raise ValueError("The period starts after it ends")
        return self


class ReportSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Kind
    scope: Scope = Field(default_factory=Scope)
    period: Period | None = Field(
        default=None, description="Default: the last 7 days (status), the whole life (close-out)"
    )
    format: Format
    sections: list[str] = Field(
        default_factory=list, max_length=12, description="Default: every section the kind has"
    )
    narrative: bool | None = Field(
        default=None, description="Default: on for status, customer and close-out reports"
    )
    filters: QueryFilters | None = Field(default=None, description="Task exports only")
    audience: Audience = "internal"
    record_type: str | None = Field(
        default=None, max_length=60, description="Records exports: which record type"
    )
    record_status: list[str] = Field(
        default_factory=list, max_length=7, description="Records exports: only these statuses"
    )

    @model_validator(mode="after")
    def _consistent(self) -> ReportSpec:
        if self.format not in FORMATS[self.kind]:
            raise ValueError(
                f"A {self.kind.replace('_', ' ')} report comes as "
                + " or ".join(FORMATS[self.kind])
            )
        where = self.scope.which()
        if where not in SCOPES[self.kind]:
            raise ValueError(
                f"A {self.kind.replace('_', ' ')} report is about one "
                + " or ".join(SCOPES[self.kind])
            )
        for s in self.sections:
            if s not in SECTIONS[self.kind]:
                raise ValueError(f"A {self.kind.replace('_', ' ')} report has no section {s}")
        if self.filters is not None and self.kind != "task_export":
            raise ValueError("Filters are for task exports")
        if (self.kind == "records_export") != (self.record_type is not None):
            raise ValueError("A records export names its record type (and only it does)")
        if self.record_status and self.kind != "records_export":
            raise ValueError("record_status is for records exports")
        if self.kind == "customer_status":
            self.audience = "customer"
        return self

    def wants(self, section: str) -> bool:
        return not self.sections or section in self.sections

    @property
    def with_narrative(self) -> bool:
        if not self.wants("narrative") or "narrative" not in SECTIONS[self.kind]:
            return False
        return self.narrative if self.narrative is not None else self.kind in NARRATIVE_DEFAULT
