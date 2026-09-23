"""Authorization. One place for every access rule (docs/architecture/auth-and-permissions.md).

Changes to this module require human approval (CLAUDE.md §6).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from momentum.core.context import Ctx
from momentum.core.errors import Forbidden, NotFound


class Action(StrEnum):
    WORKSPACE_VIEW = "workspace.view"
    WORKSPACE_ADMIN = "workspace.admin"
    USERS_MANAGE = "users.manage"
    TEAM_CREATE = "team.create"
    PROJECT_CREATE = "project.create"


class Resource(Protocol):
    """Anything that belongs to a workspace."""

    @property
    def workspace_id(self) -> object: ...


def can(ctx: Ctx, action: Action, resource: Resource | None = None) -> bool:
    actor = ctx.actor
    if resource is not None and resource.workspace_id != actor.workspace_id:
        return False
    match action:
        case Action.WORKSPACE_VIEW:
            return True
        case Action.WORKSPACE_ADMIN | Action.USERS_MANAGE:
            return actor.is_admin
        case Action.TEAM_CREATE | Action.PROJECT_CREATE:
            return actor.role in ("admin", "member")
    return False


def require(
    ctx: Ctx, action: Action, resource: Resource | None = None, *, visible: bool = True
) -> None:
    """Raise if not allowed.

    ``visible`` says whether the caller may know the resource exists: invisible resources raise
    ``NotFound`` so their existence is not leaked; visible-but-forbidden raise ``Forbidden``.
    """
    if resource is not None and resource.workspace_id != ctx.actor.workspace_id:
        raise NotFound()
    if not can(ctx, action, resource):
        raise Forbidden() if visible else NotFound()
