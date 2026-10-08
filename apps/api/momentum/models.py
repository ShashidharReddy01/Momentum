"""Import every ORM model so ``metadata`` is complete (used by Alembic and tests)."""

from momentum.ai.models import AiAction, AiMemory, AiSummary, ConversationFile, Embedding, LlmCall
from momentum.core.activity import Activity
from momentum.core.db import Base
from momentum.core.events import OutboxEvent
from momentum.core.idempotency import IdempotencyKey
from momentum.domain.agents.models import Agent, AgentRun, AgentRunStep
from momentum.domain.asks.models import Ask
from momentum.domain.attachments.models import Attachment
from momentum.domain.comments.models import Comment, Mention, Reaction
from momentum.domain.dashboards.models import (
    Dashboard,
    DashboardMember,
    DashboardPin,
    DashboardWidget,
    UserVisit,
)
from momentum.domain.fields.models import (
    FieldDef,
    FieldValue,
    ProjectField,
    ProjectFieldEvent,
    ProjectFieldValue,
)
from momentum.domain.forecasts.models import Forecast
from momentum.domain.forms.models import Form, FormSubmission
from momentum.domain.goals.models import Goal, GoalLink
from momentum.domain.integrations.models import ExternalLink, ImportJob
from momentum.domain.mytasks.models import MyTaskPlacement
from momentum.domain.notifications.models import Notification
from momentum.domain.portfolios.models import (
    Portfolio,
    PortfolioItem,
    PortfolioMember,
    PortfolioView,
)
from momentum.domain.projects.models import Favorite, Project, ProjectMember, ProjectSnapshot
from momentum.domain.reports.models import ReportRun
from momentum.domain.rules.models import Rule, RuleRun
from momentum.domain.sections.models import Section
from momentum.domain.status_updates.models import StatusUpdate
from momentum.domain.tags.models import Tag, TaskTag
from momentum.domain.tasks.models import Follower, Task, TaskDependency, TaskProject
from momentum.domain.teams.models import Team, TeamMember
from momentum.domain.templates.models import Template
from momentum.domain.users.models import ApiToken, User, UserIdentity
from momentum.domain.workload.models import Capacity
from momentum.domain.workspace.models import Workspace
from momentum.files.models import FileParse

metadata = Base.metadata

__all__ = [
    "Activity",
    "Agent",
    "AgentRun",
    "AgentRunStep",
    "AiAction",
    "AiMemory",
    "AiSummary",
    "ApiToken",
    "Ask",
    "Attachment",
    "Capacity",
    "Comment",
    "ConversationFile",
    "Dashboard",
    "DashboardMember",
    "DashboardPin",
    "DashboardWidget",
    "Embedding",
    "ExternalLink",
    "Favorite",
    "FieldDef",
    "FieldValue",
    "FileParse",
    "Follower",
    "Forecast",
    "Form",
    "FormSubmission",
    "Goal",
    "GoalLink",
    "IdempotencyKey",
    "ImportJob",
    "LlmCall",
    "Mention",
    "MyTaskPlacement",
    "Notification",
    "OutboxEvent",
    "Portfolio",
    "PortfolioItem",
    "PortfolioMember",
    "PortfolioView",
    "Project",
    "ProjectField",
    "ProjectFieldEvent",
    "ProjectFieldValue",
    "ProjectMember",
    "ProjectSnapshot",
    "Reaction",
    "ReportRun",
    "Rule",
    "RuleRun",
    "Section",
    "StatusUpdate",
    "Tag",
    "Task",
    "TaskDependency",
    "TaskProject",
    "TaskTag",
    "Team",
    "TeamMember",
    "Template",
    "User",
    "UserIdentity",
    "UserVisit",
    "Workspace",
    "metadata",
]
