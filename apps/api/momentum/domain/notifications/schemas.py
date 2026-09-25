from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

NotificationKind = Literal[
    "assigned",
    "mentioned",
    "commented",
    "completed",
    "due_soon",
    "overdue",
    "approval_requested",
    "approval_decided",
    "agent_proposal",
    "digest",
]

# The kinds a user can actually toggle in this slice (the rest have no producer yet).
PREF_KINDS: tuple[NotificationKind, ...] = (
    "assigned",
    "mentioned",
    "commented",
    "completed",
    "due_soon",
    "overdue",
)


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    kind: NotificationKind
    entity_type: str
    entity_id: uuid.UUID
    activity_id: uuid.UUID | None
    title: str
    snippet: str | None
    read_at: datetime | None
    archived_at: datetime | None
    created_at: datetime


class NotificationPrefsOut(BaseModel):
    """Per-kind in-app on/off (default on). Digest time / email / Slack are S2.5.3."""

    assigned: bool = True
    mentioned: bool = True
    commented: bool = True
    completed: bool = True
    due_soon: bool = True
    overdue: bool = True


class NotificationPrefsIn(NotificationPrefsOut):
    model_config = ConfigDict(extra="forbid")


class UnreadCountOut(BaseModel):
    count: int
