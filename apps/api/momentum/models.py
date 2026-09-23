"""Import every ORM model so ``metadata`` is complete (used by Alembic and tests)."""

from momentum.core.activity import Activity
from momentum.core.db import Base
from momentum.core.events import OutboxEvent
from momentum.core.idempotency import IdempotencyKey
from momentum.domain.projects.models import Favorite, Project, ProjectMember
from momentum.domain.sections.models import Section
from momentum.domain.teams.models import Team, TeamMember
from momentum.domain.users.models import ApiToken, User, UserIdentity
from momentum.domain.workspace.models import Workspace

metadata = Base.metadata

__all__ = [
    "Activity",
    "ApiToken",
    "Favorite",
    "IdempotencyKey",
    "OutboxEvent",
    "Project",
    "ProjectMember",
    "Section",
    "Team",
    "TeamMember",
    "User",
    "UserIdentity",
    "Workspace",
    "metadata",
]
