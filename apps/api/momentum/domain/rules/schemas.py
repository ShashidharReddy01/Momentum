"""S4.1.1: the rule JSON, validated on write. The stored shape is exactly what the caller sent
(``exclude_unset``), e.g. ``{"trigger": {"type": "task.moved", "to_section": "…"}, "conditions":
[{"field": "priority", "op": "eq", "value": "high"}], "actions": [{"type": "assign",
"user_id": "…"}]}``."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

# Triggers the executor can fire on today.
TRIGGER_PARAMS: dict[str, set[str]] = {
    "task.added": set(),
    "task.moved": {"to_section"},
    "task.field_changed": {"field", "to"},
    "task.completed": set(),
    "task.assigned": {"user_id"},
    "task.due_approaching": set(),
    "task.unblocked": set(),  # S6.1.3: its last open blocker was completed
    "form.submitted": {"form_id"},
    "approval.decided": {"decision"},
}
NOT_YET_TRIGGERS: set[str] = set()

TRIGGER_FIELDS = ("priority", "due_on", "start_on")
# Phase 7.5: ``title`` (compared without case) and ``type`` (task, milestone, approval) let a
# template rule say "when the milestone *Contract signed* is completed"
CONDITION_FIELDS = ("priority", "assignee", "due_on", "start_on", "tag", "title", "type")
TASK_TYPES = ("task", "milestone", "approval")
OPS = ("eq", "neq", "in", "empty", "not_empty", "gt", "lt")
ORDERED_FIELDS = ("due_on", "start_on")  # gt/lt also work on custom number and date fields

# Actions the executor can run today. `allowed` is every param an action accepts; a param
# missing from ACTION_REQUIRED for that action is optional (e.g. add_to_project's section_id
# falls back to the target project's default section, like the API endpoint does).
#
# S4.1.5: ``ai_step`` is the one action the executor doesn't perform itself. It queues a
# ``rule_ai_steps`` row that the ``ai`` queue runs afterwards (``momentum/ai/rule_steps.py``),
# because a model call must not be made inside the rule run's transaction.
AI_STEP_KINDS = ("summarize_to_comment", "classify_field", "extract_fields", "draft_reply")
ACTION_PARAMS: dict[str, set[str]] = {
    "assign": {"user_id"},
    "add_comment": {"text"},
    "move_section": {"section_id"},
    "mark_complete": set(),
    "set_field": {"field_id", "value"},
    "add_to_project": {"project_id", "section_id"},
    "remove_from_project": {"project_id"},
    "add_tag": {"tag_id"},
    "create_subtasks": {"titles"},
    "set_due_relative": {"days"},
    "notify_user": {"user_id", "text"},
    "ai_step": {"kind", "field_id"},
    # Phase 7.5 (spec §5.5): set a field of the rule's own project (e.g. Stage = Implementation
    # when "Contract signed" is completed); respects the project's portfolio stage gates
    "set_project_field": {"field_id", "value"},
}
ACTION_REQUIRED: dict[str, set[str]] = {
    **ACTION_PARAMS,
    "add_to_project": {"project_id"},
    "ai_step": {"kind"},  # field_id only for classify_field (checked below)
}
# Slack messages are on the roadmap (P7) but have no backing service yet.
NOT_YET_ACTIONS = {"slack_message"}
MAX_CONDITIONS = 10
MAX_ACTIONS = 10
MAX_SUBTASK_TITLES = 20


def is_custom_field(name: str) -> bool:
    """A custom field is referred to by its id."""
    try:
        uuid.UUID(name)
    except ValueError:
        return False
    return True


class Trigger(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str
    to_section: uuid.UUID | None = None
    field: str | None = None
    to: Any = None
    user_id: uuid.UUID | None = None
    form_id: uuid.UUID | None = None  # form.submitted: null means any form in the project
    decision: str | None = None  # approval.decided: null means any decision

    @model_validator(mode="after")
    def _check(self) -> Trigger:
        if self.type in NOT_YET_TRIGGERS:
            raise ValueError(f"The trigger {self.type} isn't available yet")
        allowed = TRIGGER_PARAMS.get(self.type)
        if allowed is None:
            raise ValueError(f"Unknown trigger {self.type}")
        extra = self.model_fields_set - {"type"} - allowed
        if extra:
            raise ValueError(f"{self.type} doesn't take {', '.join(sorted(extra))}")
        if self.type == "task.field_changed" and not (
            self.field in TRIGGER_FIELDS or (self.field is not None and is_custom_field(self.field))
        ):
            raise ValueError("field must be priority, due_on, start_on or a custom field id")
        if self.type == "approval.decided" and self.decision not in (
            None,
            "approved",
            "changes_requested",
            "rejected",
        ):
            raise ValueError("decision must be approved, changes_requested or rejected")
        return self


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    op: str
    value: Any = None

    @model_validator(mode="after")
    def _check(self) -> Condition:
        custom = is_custom_field(self.field)
        if not custom and self.field not in CONDITION_FIELDS:
            raise ValueError(
                f"field must be one of {', '.join(CONDITION_FIELDS)} or a custom field id"
            )
        if self.op not in OPS:
            raise ValueError(f"op must be one of {', '.join(OPS)}")
        if self.op in ("empty", "not_empty"):
            if self.value is not None:
                raise ValueError(f"{self.op} takes no value")
        elif self.op == "in":
            if not isinstance(self.value, list) or not self.value:
                raise ValueError("in needs a non-empty list")
        elif self.value is None or isinstance(self.value, list | dict):
            raise ValueError(f"{self.op} needs a single value")
        if self.op in ("gt", "lt") and not (custom or self.field in ORDERED_FIELDS):
            raise ValueError(f"{self.op} only works on dates and custom fields")
        if self.field == "type" and self.value is not None:
            values = self.value if isinstance(self.value, list) else [self.value]
            if not all(v in TASK_TYPES for v in values):
                raise ValueError(f"type is one of {', '.join(TASK_TYPES)}")
        if self.field == "title" and self.value is not None:
            values = self.value if isinstance(self.value, list) else [self.value]
            if not all(isinstance(v, str) and v.strip() for v in values):
                raise ValueError("title conditions compare with text")
        if self.field in ("assignee", "tag") and self.value is not None:
            values = self.value if isinstance(self.value, list) else [self.value]
            if not all(isinstance(v, str) and is_custom_field(v) for v in values):
                raise ValueError(f"{self.field} conditions use ids")
        return self


SubtaskTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str
    user_id: uuid.UUID | None = None
    text: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
        | None
    ) = None
    section_id: uuid.UUID | None = None
    field_id: str | None = None  # "priority" or a custom field id
    value: Any = None
    project_id: uuid.UUID | None = None
    tag_id: uuid.UUID | None = None
    titles: list[SubtaskTitle] | None = Field(default=None, max_length=MAX_SUBTASK_TITLES)
    days: int | None = Field(default=None, ge=-365, le=365)
    kind: str | None = None  # ai_step: one of AI_STEP_KINDS

    @model_validator(mode="after")
    def _check(self) -> Action:
        if self.type in NOT_YET_ACTIONS:
            raise ValueError(f"The action {self.type} isn't available yet")
        allowed = ACTION_PARAMS.get(self.type)
        if allowed is None:
            raise ValueError(f"Unknown action {self.type}")
        extra = self.model_fields_set - {"type"} - allowed
        if extra:
            raise ValueError(f"{self.type} doesn't take {', '.join(sorted(extra))}")
        missing = {
            p for p in ACTION_REQUIRED.get(self.type, allowed) if p not in self.model_fields_set
        }
        if missing:
            raise ValueError(f"{self.type} needs {', '.join(sorted(missing))}")
        if self.type == "add_comment" and self.text is None:
            raise ValueError("add_comment needs text")
        if self.type == "move_section" and self.section_id is None:
            raise ValueError("move_section needs a section_id")
        if self.type == "notify_user" and self.text is None:
            raise ValueError("notify_user needs text")
        if self.type == "create_subtasks" and not self.titles:
            raise ValueError("create_subtasks needs a non-empty titles list")
        if (
            self.type == "set_field"
            and self.field_id != "priority"
            and not (self.field_id is not None and is_custom_field(self.field_id))
        ):
            raise ValueError("field_id must be 'priority' or a custom field id")
        if self.type == "set_project_field" and not (
            self.field_id is not None and is_custom_field(self.field_id)
        ):
            raise ValueError("set_project_field needs a project field id")
        if self.type == "ai_step":
            if self.kind not in AI_STEP_KINDS:
                raise ValueError(f"kind must be one of {', '.join(AI_STEP_KINDS)}")
            if self.kind == "classify_field" and not (
                self.field_id == "priority"
                or (self.field_id is not None and is_custom_field(self.field_id))
            ):
                raise ValueError("classify_field needs a field_id ('priority' or a custom field)")
            if self.kind != "classify_field" and self.field_id is not None:
                raise ValueError(f"{self.kind} doesn't take a field_id")
        return self  # assign with user_id null unassigns


class RuleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trigger: Trigger
    conditions: list[Condition] = Field(default_factory=list, max_length=MAX_CONDITIONS)
    actions: list[Action] = Field(min_length=1, max_length=MAX_ACTIONS)


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class RuleIn(RuleSpec):
    name: Name
    enabled: bool = True
    project_id: uuid.UUID | None = None  # null = a workspace rule (admins)
    created_from_prompt: str | None = Field(default=None, max_length=2000)


class RulePatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name | None = None
    enabled: bool | None = None
    trigger: Trigger | None = None
    conditions: list[Condition] | None = Field(default=None, max_length=MAX_CONDITIONS)
    actions: list[Action] | None = Field(default=None, min_length=1, max_length=MAX_ACTIONS)
    expected_version: int | None = None

    @field_validator("name", "enabled", "trigger", "actions")
    @classmethod
    def _not_null(cls, v: object) -> object:
        if v is None:
            raise ValueError("can't be null")
        return v


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID | None
    name: str
    enabled: bool
    trigger: dict[str, Any]
    conditions: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    created_from_prompt: str | None
    version: int
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class RuleAiStepOut(BaseModel):
    """S4.1.5: one queued AI step of a run. The rule run finishes before the step does, so the
    run history shows the step's own status (queued → running → done/failed)."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    task_id: uuid.UUID
    kind: str
    field_id: str | None
    status: str
    result: str | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class RuleRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    rule_id: uuid.UUID
    outbox_event_id: int
    status: str
    depth: int
    actions_run: int
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    activity_batch_id: uuid.UUID | None
    ai_steps: list[RuleAiStepOut] = Field(default_factory=list)


class RuleTestRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: uuid.UUID


class ActionResultOut(BaseModel):
    type: str
    ok: bool
    error: str | None


class RuleTestRunOut(BaseModel):
    """S4.1.3: what would happen if this rule fired on the given task, right now. Nothing is
    persisted: each action runs inside its own savepoint that's always rolled back, so a later
    action still gets tried even if an earlier one would fail."""

    conditions_passed: bool
    actions: list[ActionResultOut]
