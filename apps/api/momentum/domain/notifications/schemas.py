from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

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


NotificationChannel = Literal["in_app", "email", "slack", "off"]
# Only "in_app" actually delivers anything right now — there's no email or Slack sender
# built yet. "email"/"slack" are stored as chosen-but-not-yet-active preferences (the
# roadmap's own "email-later"/"Slack-later" naming), so picking one behaves exactly like
# "off" for now: notify() only creates a row when the channel is "in_app". This lets a
# user record their intended channel ahead of the sender existing, without silently
# claiming to deliver something the backend can't yet.
DIGEST_TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"  # "HH:MM", 24h, local to the user


class NotificationPrefsOut(BaseModel):
    """Per-kind channel choice (default in_app) plus a digest-time preference.

    The digest time is stored only — nothing reads it yet. It's for the Pulse agent's
    daily digest in Phase 5 (P5); persisting it now means users can set it once and have
    it already in place when that consumer exists.
    """

    assigned: NotificationChannel = "in_app"
    mentioned: NotificationChannel = "in_app"
    commented: NotificationChannel = "in_app"
    completed: NotificationChannel = "in_app"
    due_soon: NotificationChannel = "in_app"
    overdue: NotificationChannel = "in_app"
    digest_time: str | None = None

    @field_validator("digest_time")
    @classmethod
    def _validate_digest_time(cls, value: str | None) -> str | None:
        if value is not None and not re.match(DIGEST_TIME_PATTERN, value):
            raise ValueError('digest_time must be "HH:MM" (24h)')
        return value


class NotificationPrefsIn(NotificationPrefsOut):
    model_config = ConfigDict(extra="forbid")


class UnreadCountOut(BaseModel):
    count: int
