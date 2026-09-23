"""Identifier helpers. All primary keys are time-ordered UUIDv7 generated in the app."""

from __future__ import annotations

import uuid

import uuid_utils


def new_id() -> uuid.UUID:
    return uuid.UUID(str(uuid_utils.uuid7()))


def task_key(number: int) -> str:
    return f"T-{number}"
