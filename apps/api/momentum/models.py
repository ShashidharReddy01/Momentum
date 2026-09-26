"""Import every ORM model so ``metadata`` is complete (used by Alembic and tests)."""

from momentum.ai.models import AiAction, AiSummary, Embedding, LlmCall
from momentum.core.activity import Activity
from momentum.core.db import Base
from momentum.core.events import OutboxEvent
from momentum.core.idempotency import IdempotencyKey
from momentum.domain.attachments.models import Attachment
from momentum.domain.comments.models import Comment, Mention, Reaction
from momentum.domain.fields.models import FieldDef, FieldValue, ProjectField
from momentum.domain.integrations.models import ExternalLink, ImportJob
from momentum.domain.mytasks.models import MyTaskPlacement
from momentum.domain.notifications.models import Notification
from momentum.domain.projects.models import Favorite, Project, ProjectMember
from momentum.domain.sections.models import Section
from momentum.domain.tags.models import Tag, TaskTag
from momentum.domain.tasks.models import Follower, Task, TaskDependency, TaskProject
from momentum.domain.teams.models import Team, TeamMember
from momentum.domain.users.models import ApiToken, User, UserIdentity
from momentum.domain.workspace.models import Workspace

metadata = Base.metadata

__all__ = [
    "Activity",
    "AiAction",
    "AiSummary",
    "ApiToken",
    "Attachment",
    "Comment",
    "Embedding",
    "ExternalLink",
    "Favorite",
    "FieldDef",
    "FieldValue",
    "Follower",
    "IdempotencyKey",
    "ImportJob",
    "LlmCall",
    "Mention",
    "MyTaskPlacement",
    "Notification",
    "OutboxEvent",
    "Project",
    "ProjectField",
    "ProjectMember",
    "Reaction",
    "Section",
    "Tag",
    "Task",
    "TaskDependency",
    "TaskProject",
    "TaskTag",
    "Team",
    "TeamMember",
    "User",
    "UserIdentity",
    "Workspace",
    "metadata",
]
