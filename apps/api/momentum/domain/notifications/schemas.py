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
    "rule",
    "approval_requested",
    "approval_decided",
    "agent_proposal",
    "digest",
    "agent_alert",
    "unblocked",
    "agent_ask",  # Phase 7.6 S76-03
    "agent_ask_reminder",
    "skill_proposed",  # Phase 7.6 S76-05
]

# The kinds a user can actually toggle in this slice (the rest have no producer yet).
PREF_KINDS: tuple[NotificationKind, ...] = (
    "assigned",
    "mentioned",
    "commented",
    "completed",
    "due_soon",
    "overdue",
    "unblocked",
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

    S5.3.1: ``digest`` is the Pulse daily digest ("off" = no digest, and no model call spent on
    it); ``digest_time`` ("HH:MM", the person's own timezone) is when it arrives on weekdays
    (08:30 when unset).
    """

    assigned: NotificationChannel = "in_app"
    mentioned: NotificationChannel = "in_app"
    commented: NotificationChannel = "in_app"
    completed: NotificationChannel = "in_app"
    due_soon: NotificationChannel = "in_app"
    overdue: NotificationChannel = "in_app"
    # S6.1.3: "You're up": the last task mine was waiting on is done
    unblocked: NotificationChannel = "in_app"
    digest: NotificationChannel = "in_app"
    digest_time: str | None = None
    # S5.3.4 (kickoff Q7): false = Nudge never reminds me (per task: snooze on My Tasks)
    nudge_me: bool = True

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
