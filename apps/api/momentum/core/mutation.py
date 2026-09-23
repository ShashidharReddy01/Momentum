"""Result of a service mutation: the entity plus what the UI needs for undo and concurrency."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass
class Mutation(Generic[T]):
    entity: T
    activity_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    version: int | None = None
