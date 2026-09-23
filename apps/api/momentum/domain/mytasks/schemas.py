from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict

from momentum.domain.tasks.schemas import ProjectRef, TaskOut

Bucket = Literal["recently_assigned", "today", "this_week", "later"]


class MyTaskOut(TaskOut):
    bucket: Bucket | None
    my_position: str | None
    project: ProjectRef | None


class MyTaskMoveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bucket: Bucket
    after_id: uuid.UUID | None = None
    before_id: uuid.UUID | None = None
