"""Import every ORM model so ``metadata`` is complete (used by Alembic and tests)."""

from momentum.core.activity import Activity
from momentum.core.db import Base
from momentum.core.events import OutboxEvent
from momentum.core.idempotency import IdempotencyKey
from momentum.domain.comments.models import Comment, Mention, Reaction
from momentum.domain.fields.models import FieldDef, FieldValue, ProjectField
from momentum.domain.mytasks.models import MyTaskPlacement
from momentum.domain.projects.models import Favorite, Project, ProjectMember
from momentum.domain.sections.models import Section
from momentum.domain.tasks.models import Follower, Task, TaskProject
from momentum.domain.teams.models import Team, TeamMember
from momentum.domain.users.models import ApiToken, User, UserIdentity
from momentum.domain.workspace.models import Workspace

metadata = Base.metadata

__all__ = [
    "Activity",
    "ApiToken",
    "Comment",
    "Favorite",
    "FieldDef",
    "FieldValue",
    "Follower",
    "IdempotencyKey",
    "Mention",
    "MyTaskPlacement",
    "OutboxEvent",
    "Project",
    "ProjectField",
    "ProjectMember",
    "Reaction",
    "Section",
    "Task",
    "TaskProject",
    "Team",
    "TeamMember",
    "User",
    "UserIdentity",
    "Workspace",
    "metadata",
]
