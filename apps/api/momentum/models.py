"""Import every ORM model so ``metadata`` is complete (used by Alembic and tests)."""

from momentum.core.activity import Activity
from momentum.core.db import Base
from momentum.core.events import OutboxEvent
from momentum.core.idempotency import IdempotencyKey
from momentum.domain.users.models import ApiToken, User, UserIdentity
from momentum.domain.workspace.models import Workspace

metadata = Base.metadata

__all__ = [
    "Activity",
    "ApiToken",
    "IdempotencyKey",
    "OutboxEvent",
    "User",
    "UserIdentity",
    "Workspace",
    "metadata",
]
