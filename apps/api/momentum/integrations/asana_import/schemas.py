from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Asana ids are numeric strings (letters too in synthetic fixtures); a personal access token is
# printable ASCII (it goes in an HTTP header, which can't carry anything else)
GID = r"^[A-Za-z0-9_-]{1,64}$"


class AsanaImportIn(BaseModel):
    pat: str = Field(
        min_length=1,
        max_length=512,
        pattern=r"^[!-~]+$",  # printable ASCII
        description="Asana personal access token (printable ASCII, no spaces)",
    )
    workspace_gid: str = Field(pattern=GID)
    team_gid: str = Field(pattern=GID)
    team_name: str = Field(min_length=1, max_length=120)
    project_gids: list[str] | None = Field(default=None, max_length=1000)


class ImportJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: Literal["asana", "csv"]
    status: Literal["pending", "running", "done", "failed"]
    stats: dict[str, Any] | None
    log: dict[str, Any] | None
    created_at: datetime
    finished_at: datetime | None
