"""Phase 6.5: the showcase seed builds a workspace that exercises every screen, through the
services, and is safe to re-run."""

from __future__ import annotations

from sqlalchemy import func, select

from momentum.core.db import UnitOfWork
from momentum.core.settings import Settings
from momentum.domain.notifications.models import Notification
from momentum.domain.tasks.models import Task, TaskDependency
from momentum.domain.users.models import User
from momentum.seed_showcase import seed_showcase


async def test_showcase_fills_every_surface_and_is_idempotent(
    uow: UnitOfWork, settings: Settings
) -> None:
    async with uow.transaction() as s:
        made = await seed_showcase(s, settings)
    assert made["showcase_projects"] == 5 and made["showcase_tasks"] > 40
    async with uow.transaction() as s:
        again = await seed_showcase(s, settings)
        assert again == {"showcase_projects": 0}
        spans = await s.scalar(
            select(func.count()).select_from(Task).where(Task.start_on.is_not(None))
        )
        deps = await s.scalar(select(func.count()).select_from(TaskDependency))
        admin = (await s.execute(select(User).where(User.email.startswith("admin@")))).scalar_one()
        inbox = await s.scalar(
            select(func.count()).select_from(Notification).where(Notification.user_id == admin.id)
        )
    assert (spans or 0) > 25 and (deps or 0) >= 12
    assert (inbox or 0) >= 3  # mentions and the approval request reach the admin
