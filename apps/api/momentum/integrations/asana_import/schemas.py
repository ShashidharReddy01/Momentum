from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

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


PAT = Field(
    min_length=1,
    max_length=512,
    pattern=r"^[!-~]+$",  # printable ASCII: it goes in an HTTP header
    description="Asana personal access token: used for this call only, never stored",
)


class AsanaDiscoverIn(BaseModel):
    """S7.4.2: browse Asana with a token: its workspaces, a workspace's teams, a team's projects."""

    model_config = ConfigDict(extra="forbid")
    pat: str = PAT
    workspace_gid: str | None = Field(default=None, pattern=GID)
    team_gid: str | None = Field(default=None, pattern=GID)


class AsanaThing(BaseModel):
    gid: str
    name: str
    archived: bool = False


class AsanaDiscoverOut(BaseModel):
    workspaces: list[AsanaThing]
    teams: list[AsanaThing]
    projects: list[AsanaThing]


class AsanaJobIn(BaseModel):
    """S7.4.2: what to import. No token here: each step sends it (``AsanaStepIn``)."""

    model_config = ConfigDict(extra="forbid")
    workspace_gid: str = Field(pattern=GID)
    team_gid: str = Field(pattern=GID)
    team_name: str = Field(min_length=1, max_length=120)
    project_gids: list[Annotated[str, StringConstraints(pattern=GID)]] | None = Field(
        default=None, max_length=1000
    )
    dry_run: bool = Field(default=False, description="Count and report only; write nothing")
    invite_unmatched: bool = Field(
        default=True,
        description="Asana people with no Momentum account join as invited (matched by email "
        "when they first sign in), so their tasks keep their assignee",
    )


class AsanaStepIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pat: str = PAT


class ImportJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: Literal["asana", "csv"]
    status: Literal["pending", "running", "done", "failed"]
    stats: dict[str, Any] | None
    created_at: datetime
    finished_at: datetime | None
    dry_run: bool = False
    remaining: int = Field(default=0, description="Work items left (0 when finished)")

    @classmethod
    def of(cls, job: Any) -> ImportJobOut:
        """The job without its working state (the queue and maps stay server-side)."""
        log = job.log or {}
        return cls(
            id=job.id,
            source=job.source,
            status=job.status,
            stats=job.stats,
            created_at=job.created_at,
            finished_at=job.finished_at,
            dry_run=bool(log.get("dry_run")),
            remaining=len(log.get("queue") or []),
        )
