from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


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


_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
ASSIGNEE_FILTER = rf"^(me|none|{_UUID})$"


class ProjectViewPrefs(BaseModel):
    """How one user last viewed a project (restored on revisit)."""

    model_config = ConfigDict(extra="forbid")
    assignees: list[Annotated[str, StringConstraints(pattern=ASSIGNEE_FILTER)]] = Field(
        default_factory=list, max_length=50
    )
    # S2.3.3: tag ids to filter by (OR-ed, like assignees).
    tags: list[Annotated[str, StringConstraints(pattern=_UUID)]] = Field(
        default_factory=list, max_length=50
    )
    due: Literal["any", "overdue", "today", "this_week", "next_week", "no_date"] = "any"
    show_completed: bool = False
    sort: Literal["manual", "due", "assignee", "created", "title"] = "manual"
    group: Literal["section", "assignee", "due"] = "section"
    # S2.2.3: the tab this user last had open (list-view filter/sort/group above are unrelated
    # to *which* view is showing). None = never chosen here yet: fall back to the project's
    # default_view, distinct from explicitly picking "list".
    view: Literal["list", "board", "calendar", "timeline", "overview", "dashboard"] | None = None
