"""s6_1_3 unblocked notification kind

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-30 12:00:00.000000

S6.1.3 dependency hand-offs: when a task's last open blocker is completed, its assignee gets an
``unblocked`` ("You're up") notification. Only the notifications kind check constraint changes;
no data is touched.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = (
    "assigned",
    "mentioned",
    "commented",
    "completed",
    "due_soon",
    "overdue",
    "rule",
    "approval_requested",
    "approval_decided",
    "agent_proposal",
    "digest",
    "agent_alert",
)
NEW_KINDS = (*OLD_KINDS, "unblocked")


def upgrade() -> None:
    op.drop_constraint(op.f("ck_notifications_kind"), "notifications", type_="check")
    op.create_check_constraint(
        op.f("ck_notifications_kind"), "notifications", f"kind in {NEW_KINDS}"
    )


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE kind = 'unblocked'")
    op.drop_constraint(op.f("ck_notifications_kind"), "notifications", type_="check")
    op.create_check_constraint(
        op.f("ck_notifications_kind"), "notifications", f"kind in {OLD_KINDS}"
    )
