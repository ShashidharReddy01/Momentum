from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from momentum.core.errors import ValidationFailed
from momentum.domain.fields.filters import parse_field_filter


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    avatar_url: str | None
    role: str
    status: str
    is_agent: bool
    timezone: str


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str


class MeOut(BaseModel):
    user: UserOut
    workspace: WorkspaceOut


class MemberPatchIn(BaseModel):
    """S7.5.4: an admin changes someone's role or disables / re-enables them."""

    model_config = ConfigDict(extra="forbid")
    role: Literal["admin", "member", "guest"] | None = None
    status: Literal["active", "disabled"] | None = None


class TransferIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to_user_id: uuid.UUID


class TransferOut(BaseModel):
    tasks: int = Field(description="Open tasks reassigned")
    projects: int = Field(description="Projects whose owner changed")
    not_visible: int = Field(
        description="Left in place: in private projects the admin can't see (their admins can)"
    )


class UserInviteIn(BaseModel):
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=254)]
    name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    role: Literal["admin", "member", "guest"] = "member"


class OnboardingStatusOut(BaseModel):
    created_project: bool
    tried_import: bool
    used_command_palette: bool
    dismissed: bool


class OnboardingPatchIn(BaseModel):
    used_command_palette: bool | None = None
    dismissed: bool | None = None


_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
ASSIGNEE_FILTER = rf"^(me|none|{_UUID})$"
SORT_PREF = rf"^(manual|due|assignee|created|title|field:{_UUID})$"
GROUP_PREF = rf"^(section|assignee|due|field:{_UUID})$"


class ProjectViewPrefs(BaseModel):
    """How one user last viewed a project (restored on revisit)."""

    model_config = ConfigDict(extra="forbid")
    assignees: list[Annotated[str, StringConstraints(pattern=ASSIGNEE_FILTER)]] = Field(
        default_factory=list, max_length=50
    )
    # S2.3.3: tag ids to filter by (OR-ed, like assignees).
    tags: list[Annotated[str, StringConstraints(pattern=rf"^{_UUID}$")]] = Field(
        default_factory=list, max_length=50
    )
    due: Literal["any", "overdue", "today", "this_week", "next_week", "no_date"] = "any"
    show_completed: bool = False
    # S7.4.1: also "field:<field id>" (sort by, or group by, a custom field)
    sort: Annotated[str, StringConstraints(pattern=SORT_PREF)] = "manual"
    group: Annotated[str, StringConstraints(pattern=GROUP_PREF)] = "section"
    # S7.4.1: custom-field filters, "<field id>:<op>[:<arg>]" (domain/fields/filters.py)
    fields: list[Annotated[str, StringConstraints(max_length=300)]] = Field(
        default_factory=list, max_length=10
    )

    @field_validator("fields")
    @classmethod
    def _fields(cls, v: list[str]) -> list[str]:
        for text in v:
            try:
                parse_field_filter(text)
            except ValidationFailed as e:
                raise ValueError(e.detail) from None
        return v

    # S2.2.3: the tab this user last had open (list-view filter/sort/group above are unrelated
    # to *which* view is showing). None = never chosen here yet: fall back to the project's
    # default_view, distinct from explicitly picking "list".
    view: (
        Literal["list", "board", "calendar", "timeline", "overview", "files", "dashboard"] | None
    ) = None


class ApiTokenIn(BaseModel):
    """S5.1.6: a new API token. ``expires_in_days`` defaults to 90 (at most 365)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(min_length=1, max_length=5)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


class ApiTokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    prefix: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None


class ApiTokenCreatedOut(BaseModel):
    """The only response that ever carries the secret."""

    data: ApiTokenOut
    secret: str
