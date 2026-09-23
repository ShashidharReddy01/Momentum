"""Request/job context passed as the first argument to every service function."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from momentum.core.settings import Settings

Via = Literal["ui", "ai", "agent", "rule", "import", "integration", "api", "mcp", "system"]
ActorKind = Literal["user", "agent", "rule", "system", "integration", "import"]


@dataclass(frozen=True)
class Actor:
    """The minimal view of the acting user that core services need."""

    id: uuid.UUID | None
    workspace_id: uuid.UUID
    role: str = "member"
    is_agent: bool = False
    email: str | None = None
    name: str | None = None
    timezone: str = "UTC"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


@dataclass(frozen=True)
class Ctx:
    actor: Actor
    settings: Settings
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    via: Via = "ui"
    dry_run: bool = False
    acting_for: Actor | None = None

    @property
    def workspace_id(self) -> uuid.UUID:
        return self.actor.workspace_id

    @property
    def actor_kind(self) -> ActorKind:
        if self.via == "rule":
            return "rule"
        if self.via in ("import",):
            return "import"
        if self.via in ("integration",):
            return "integration"
        if self.actor.id is None:
            return "system"
        return "agent" if self.actor.is_agent else "user"

    def with_(self, **changes: object) -> Ctx:
        return replace(self, **changes)  # type: ignore[arg-type]
