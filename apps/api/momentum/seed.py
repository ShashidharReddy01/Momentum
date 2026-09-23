"""Synthetic seed data (never real company data). Grows each phase."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.settings import Settings
from momentum.domain.users.models import User
from momentum.domain.workspace.service import ensure_default_workspace

SEED_DOMAIN = "acme-demo.test"

SEED_USERS: list[tuple[str, str, str, str]] = [
    # (name, local-part, role, timezone)
    ("Avery Admin", "admin", "admin", "Europe/London"),
    ("Ravi Kumar", "ravi", "member", "Asia/Kolkata"),
    ("Ana Souza", "ana", "member", "America/Sao_Paulo"),
    ("Priya Nair", "priya", "member", "Asia/Kolkata"),
    ("Tom Becker", "tom", "member", "Europe/Berlin"),
    ("Mei Chen", "mei", "member", "Asia/Singapore"),
    ("Jordan Lee", "jordan", "member", "America/New_York"),
    ("Sam Okafor", "sam", "member", "Africa/Lagos"),
    ("Lena Novak", "lena", "member", "Europe/Prague"),
    ("Diego Ruiz", "diego", "member", "Europe/Madrid"),
    ("Kim Park", "kim", "member", "Asia/Seoul"),
    ("Noor Haddad", "noor", "member", "Asia/Dubai"),
]


async def seed(session: AsyncSession, settings: Settings) -> dict[str, int]:
    ws = await ensure_default_workspace(session, settings)
    if ws.name == settings.default_workspace_name:
        ws.name = "Acme Demo"
    created = 0
    for name, local, role, tz in SEED_USERS:
        email = f"{local}@{SEED_DOMAIN}"
        exists = await session.execute(
            select(User.id).where(User.workspace_id == ws.id, User.email == email)
        )
        if exists.scalar_one_or_none() is None:
            session.add(User(workspace_id=ws.id, email=email, name=name, role=role, timezone=tz))
            created += 1
    await session.flush()
    return {"users_created": created}
