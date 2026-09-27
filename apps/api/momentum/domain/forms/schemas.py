"""S4.2.1: the form JSON, validated on write, plus the public-facing shapes (which never expose
a question's raw ``maps_to`` field id — only what's needed to render and answer it)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

# A question maps to one of these fixed task targets, or a custom field id (a uuid string, like
# rules' ``is_custom_field``).
FIXED_TARGETS = ("title", "description", "assignee", "due_on", "priority")
MAX_QUESTIONS = 20
MAX_LABEL = 200
MAX_ANSWER_TEXT = 5000


def is_custom_field(name: str) -> bool:
    try:
        uuid.UUID(name)
    except ValueError:
        return False
    return True


QuestionId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_LABEL)]


class ShowIf(BaseModel):
    """Branching v1: show this question only if an earlier one's answer equals a value."""

    model_config = ConfigDict(extra="forbid")
    question_id: QuestionId
    equals: Any = None


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: QuestionId
    label: Label
    help_text: Annotated[str, StringConstraints(max_length=500)] | None = None
    required: bool = False
    maps_to: str  # one of FIXED_TARGETS, or a custom field id
    show_if: ShowIf | None = None

    @model_validator(mode="after")
    def _check(self) -> Question:
        if self.maps_to not in FIXED_TARGETS and not is_custom_field(self.maps_to):
            raise ValueError(f"maps_to must be one of {', '.join(FIXED_TARGETS)} or a field id")
        if self.show_if is not None and self.show_if.question_id == self.id:
            raise ValueError("A question can't depend on its own answer")
        return self


class FormSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    questions: list[Question] = Field(min_length=1, max_length=MAX_QUESTIONS)

    @model_validator(mode="after")
    def _check(self) -> FormSpec:
        ids = [q.id for q in self.questions]
        if len(set(ids)) != len(ids):
            raise ValueError("Question ids must be unique")
        targets = [q.maps_to for q in self.questions]
        if len(set(targets)) != len(targets):
            raise ValueError("Each field can only be asked once")
        titles = [q for q in self.questions if q.maps_to == "title"]
        if len(titles) != 1:
            raise ValueError("A form needs exactly one question mapped to the task title")
        if not titles[0].required:
            raise ValueError("The title question must be required")
        if titles[0].show_if is not None:
            raise ValueError("The title question can't be conditionally shown")
        index = {q.id: i for i, q in enumerate(self.questions)}
        for i, q in enumerate(self.questions):
            if q.show_if is not None:
                dep = index.get(q.show_if.question_id)
                if dep is None:
                    raise ValueError(f"{q.id} depends on an unknown question")
                if dep >= i:
                    raise ValueError(f"{q.id} can only depend on an earlier question")
        return self


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class FormIn(FormSpec):
    project_id: uuid.UUID
    name: Name
    description: Description | None = None
    section_id: uuid.UUID | None = None
    enabled: bool = True
    public_enabled: bool = False


class FormPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name | None = None
    description: Description | None = None
    section_id: uuid.UUID | None = None
    questions: list[Question] | None = Field(default=None, min_length=1, max_length=MAX_QUESTIONS)
    enabled: bool | None = None
    public_enabled: bool | None = None
    expected_version: int | None = None


class FormOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    section_id: uuid.UUID | None
    name: str
    description: str | None
    questions: list[dict[str, Any]]
    enabled: bool
    public_enabled: bool
    public_token: str
    version: int
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


QuestionKind = Literal[
    "short_text", "long_text", "select", "multi_select", "number", "date", "checkbox", "person"
]


class PublicOption(BaseModel):
    id: str
    label: str


class PublicQuestionOut(BaseModel):
    id: str
    label: str
    help_text: str | None
    required: bool
    kind: QuestionKind
    options: list[PublicOption] | None = None
    people: list[PublicOption] | None = None
    show_if: ShowIf | None = None


class PublicFormOut(BaseModel):
    name: str
    description: str | None
    questions: list[PublicQuestionOut]


class SubmitFormIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answers: dict[str, Any] = Field(default_factory=dict, max_length=MAX_QUESTIONS)
    # Honeypot: a real person never fills this hidden field in. Tripping it returns an
    # ordinary-looking success without creating anything (never signal the trap to a bot).
    website: Annotated[str, StringConstraints(max_length=200)] = ""


class FormSubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    task_id: uuid.UUID
    submitted_by: uuid.UUID | None
    created_at: datetime
