"""Phase 7.6 S76-03 (spec §5.1, §5.5): what an ask looks like, and how an answer is checked."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from momentum.core.errors import ValidationFailed

AskKind = Literal["choice", "confirm", "form", "text", "pick_entity", "pick_record"]
FieldType = Literal["text", "number", "money", "date", "enum", "boolean", "entity"]
ROUTE_PATTERN = (
    r"^(requester|project_owner|approver|stewards|admins|person:[0-9a-f-]{36}|field:.{1,100})$"
)
FIELD_NAME = r"^[a-z][a-z0-9_]{0,39}$"
EXPIRY_ACTIONS = ("escalate", "fail", "route_to_review")
PICK_KINDS = ("choice", "pick_entity", "pick_record")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AskOption(_Strict):
    value: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=300)


class FormField(_Strict):
    name: str = Field(pattern=FIELD_NAME)
    label: str = Field(min_length=1, max_length=120)
    type: FieldType
    required: bool = True
    default: Any = None
    options: list[str] | None = Field(default=None, max_length=30)

    @model_validator(mode="after")
    def _enum(self) -> FormField:
        if self.type == "enum" and not self.options:
            raise ValueError(f"Field {self.name}: an enum field needs options")
        return self


class Evidence(_Strict):
    attachment_id: uuid.UUID | None = None
    page: int | None = Field(default=None, ge=1)
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)
    crop_ref: str | None = Field(default=None, max_length=200)
    excerpt: str | None = Field(default=None, max_length=1000)


class AskSpec(_Strict):
    """What a pack asks (``job.ask``). Every ask declares what happens when nobody answers."""

    kind: AskKind
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=5000)
    options: list[AskOption] | None = None
    form: list[FormField] | None = None
    evidence: list[Evidence] = Field(default_factory=list, max_length=12)
    route: str = Field(default="requester", pattern=ROUTE_PATTERN)
    default_on_expiry: dict[str, Any]
    expires_in_days: float | None = Field(default=None, gt=0, le=60)
    remind_in_hours: float | None = Field(default=None, gt=0, le=24 * 30)

    @model_validator(mode="after")
    def _shape(self) -> AskSpec:
        if self.kind == "choice" and not (self.options and 2 <= len(self.options) <= 6):
            raise ValueError("A choice ask offers 2 to 6 options")
        if self.kind in ("pick_entity", "pick_record") and not (
            self.options and 1 <= len(self.options) <= 20
        ):
            raise ValueError("A pick ask offers 1 to 20 candidates")
        if self.kind not in PICK_KINDS and self.options:
            raise ValueError(f"A {self.kind} ask has no options")
        if self.kind == "form" and not (self.form and 1 <= len(self.form) <= 12):
            raise ValueError("A form ask has 1 to 12 fields")
        if self.kind != "form" and self.form:
            raise ValueError(f"A {self.kind} ask has no form")
        if self.options and len({o.value for o in self.options}) != len(self.options):
            raise ValueError("Option values must be unique")
        if self.form and len({f.name for f in self.form}) != len(self.form):
            raise ValueError("Form field names must be unique")
        d = self.default_on_expiry
        if set(d) == {"value"}:
            validate_answer(self.kind, self.options_dicts(), self.form_dicts(), d["value"])
        elif not (set(d) == {"action"} and d.get("action") in EXPIRY_ACTIONS):
            raise ValueError(
                "default_on_expiry is {'value': …} or"
                " {'action': 'escalate'|'fail'|'route_to_review'}"
            )
        return self

    def options_dicts(self) -> list[dict[str, Any]] | None:
        return [o.model_dump(exclude_none=True) for o in self.options] if self.options else None

    def form_dicts(self) -> list[dict[str, Any]] | None:
        return [f.model_dump(exclude_none=True) for f in self.form] if self.form else None


_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


def _number(raw: Any, label: str) -> float:
    if isinstance(raw, bool):
        raise ValidationFailed(f"{label}: expected a number")
    if isinstance(raw, int | float):
        return float(raw)
    if isinstance(raw, str):
        text = raw.strip().replace(",", "").replace(" ", "")
        text = re.sub(r"^[£$€¥]|[£$€¥]$", "", text)
        try:
            return float(Decimal(text))
        except InvalidOperation:
            pass
    raise ValidationFailed(f"{label}: expected a number")


def _option(options: list[dict[str, Any]], raw: Any) -> str:
    """An option by value, or by its label (case and spacing ignored)."""
    if isinstance(raw, str):
        for o in options:
            if raw == o["value"]:
                return str(o["value"])
        wanted = " ".join(raw.split()).casefold()
        for o in options:
            if wanted in (" ".join(str(o["label"]).split()).casefold(), str(o["value"]).casefold()):
                return str(o["value"])
    raise ValidationFailed("That isn't one of the options")


def _field(f: dict[str, Any], raw: Any) -> Any:
    label, kind = f["label"], f["type"]
    if kind in ("number", "money"):
        return _number(raw, label)
    if kind == "boolean":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str) and raw.strip().lower() in ("yes", "no", "true", "false"):
            return raw.strip().lower() in ("yes", "true")
        raise ValidationFailed(f"{label}: expected yes or no")
    if kind == "date":
        try:
            return date.fromisoformat(str(raw)).isoformat()
        except ValueError:
            raise ValidationFailed(f"{label}: expected a YYYY-MM-DD date") from None
    if kind == "enum":
        opts = [{"value": o, "label": o} for o in f.get("options") or []]
        return _option(opts, raw)
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 2000:
        raise ValidationFailed(f"{label}: expected text")
    return raw.strip()


def validate_answer(
    kind: str, options: list[dict[str, Any]] | None, form: list[dict[str, Any]] | None, value: Any
) -> Any:
    """The answer, cleaned, or ``ValidationFailed`` saying what's wrong."""
    if kind in PICK_KINDS:
        return _option(options or [], value)
    if kind == "confirm":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in ("yes", "no"):
            return value.strip().lower() == "yes"
        raise ValidationFailed("Answer yes or no")
    if kind == "text":
        if not isinstance(value, str) or not value.strip() or len(value) > 5000:
            raise ValidationFailed("Give a short text answer")
        return value.strip()
    if not isinstance(value, dict):
        raise ValidationFailed("Fill in the form")
    fields = form or []
    unknown = set(value) - {f["name"] for f in fields}
    if unknown:
        raise ValidationFailed(f"Unknown field(s): {', '.join(sorted(unknown))}")
    out: dict[str, Any] = {}
    for f in fields:
        raw = value.get(f["name"], f.get("default"))
        if raw is None or raw == "":
            if f.get("required", True):
                raise ValidationFailed(f"{f['label']} is required")
            out[f["name"]] = None
            continue
        out[f["name"]] = _field(f, raw)
    return out


class AskAgentOut(BaseModel):
    id: uuid.UUID
    name: str
    avatar: str


class AskPersonOut(BaseModel):
    id: uuid.UUID
    name: str


class AskOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    task_id: uuid.UUID
    comment_id: uuid.UUID | None
    agent: AskAgentOut
    kind: str
    title: str
    body: str
    evidence: list[dict[str, Any]]
    options: list[dict[str, Any]] | None
    form: list[dict[str, Any]] | None
    route: str
    route_fallback: str | None
    status: str
    answer: Any = None
    answered_by: AskPersonOut | None
    answered_via: str | None
    to: list[AskPersonOut]
    can_answer: bool
    default_on_expiry: dict[str, Any]
    created_at: datetime
    answered_at: datetime | None
    expires_at: datetime
    change_activity_id: uuid.UUID | None = Field(
        default=None,
        description="For the person who answered, while the agent hasn't used the answer: undo"
        " this activity to change it",
    )


class AnswerIn(_Strict):
    value: Any
    via: Literal["card", "thread", "inbox", "api"] = "card"


class InterpretIn(_Strict):
    text: str = Field(min_length=1, max_length=4000)


class InterpretOut(BaseModel):
    applied: bool = Field(description="True when the reply mapped to an answer with certainty")
    certain: bool
    value: Any = None
    understood: str = Field(description="The interpretation in words, for the confirm step")
    ask: AskOut
