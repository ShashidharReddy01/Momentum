from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class AsanaImportIn(BaseModel):
    pat: str
    workspace_gid: str
    team_gid: str
    team_name: str
    project_gids: list[str] | None = None


class ImportJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: Literal["asana", "csv"]
    status: Literal["pending", "running", "done", "failed"]
    stats: dict[str, Any] | None
    log: dict[str, Any] | None
    created_at: datetime
    finished_at: datetime | None
