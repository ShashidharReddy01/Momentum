from __future__ import annotations

import pytest
from sqlalchemy import select

from momentum.auth.base import Principal
from momentum.auth.identity import resolve_user
from momentum.core.db import UnitOfWork
from momentum.core.errors import AccountDisabled, NotInvited
from momentum.domain.users.models import User, UserIdentity
from tests.conftest import make_settings


async def test_first_login_provisions_member_and_bootstrap_admin(uow: UnitOfWork) -> None:
    s = make_settings()
    async with uow.transaction() as session:
        member, _ = await resolve_user(
            session, s, Principal(provider="dev", subject="p", email="new@acme-demo.test")
        )
        admin, _ = await resolve_user(
            session, s, Principal(provider="dev", subject="a", email="admin@acme-demo.test")
        )
    assert member.role == "member"
    assert admin.role == "admin"


async def test_admin_role_claim_grants_admin(uow: UnitOfWork) -> None:
    s = make_settings()
    async with uow.transaction() as session:
        u, _ = await resolve_user(
            session,
            s,
            Principal(
                provider="easyauth-aad",
                subject="o",
                tenant_id="t",
                email="x@acme-demo.test",
                roles=("Momentum.Admin",),
            ),
        )
    assert u.role == "admin"


async def test_lift_and_shift_relinks_by_email(uow: UnitOfWork) -> None:
    """Same email under a new provider/tenant keeps the same user (tenant move)."""
    s = make_settings()
    async with uow.transaction() as session:
        before, _ = await resolve_user(
            session,
            s,
            Principal(
                provider="easyauth-aad",
                subject="old-oid",
                tenant_id="T1",
                email="ravi@acme-demo.test",
            ),
        )
        after, _ = await resolve_user(
            session,
            s,
            Principal(
                provider="easyauth-aad",
                subject="new-oid",
                tenant_id="T2",
                email="Ravi@Acme-Demo.test",
            ),
        )
        links = (
            (await session.execute(select(UserIdentity).where(UserIdentity.user_id == before.id)))
            .scalars()
            .all()
        )
    assert before.id == after.id
    assert {link.tenant_id for link in links} == {"T1", "T2"}


async def test_not_allowed_domain_is_rejected(uow: UnitOfWork) -> None:
    s = make_settings()
    async with uow.transaction() as session:
        with pytest.raises(NotInvited):
            await resolve_user(
                session, s, Principal(provider="dev", subject="x", email="x@evil.test")
            )


async def test_tenant_allow_list(uow: UnitOfWork) -> None:
    s = make_settings(allowed_tenant_ids="good-tenant")
    async with uow.transaction() as session:
        with pytest.raises(NotInvited):
            await resolve_user(
                session,
                s,
                Principal(
                    provider="easyauth-aad", subject="o", tenant_id="bad", email="a@acme-demo.test"
                ),
            )


async def test_disabled_user_is_blocked(uow: UnitOfWork) -> None:
    s = make_settings()
    async with uow.transaction() as session:
        u, _ = await resolve_user(
            session, s, Principal(provider="dev", subject="d", email="d@acme-demo.test")
        )
        u.status = "disabled"
    async with uow.transaction() as session:
        with pytest.raises(AccountDisabled):
            await resolve_user(
                session, s, Principal(provider="dev", subject="d", email="d@acme-demo.test")
            )


async def test_no_auto_provision_without_invite(uow: UnitOfWork) -> None:
    s = make_settings(auto_provision=False)
    async with uow.transaction() as session:
        with pytest.raises(NotInvited):
            await resolve_user(
                session, s, Principal(provider="dev", subject="n", email="n@acme-demo.test")
            )
        count = len((await session.execute(select(User))).scalars().all())
    assert count == 0


async def test_concurrent_first_requests_create_one_user_and_link(engine) -> None:  # type: ignore[no-untyped-def]
    """A new person's first page load fires several requests at once; none may fail."""
    import asyncio

    from momentum.core.db import create_session_factory

    s = make_settings()
    factory = create_session_factory(engine)
    principal = Principal(
        provider="easyauth", subject="oid-race", tenant_id="t1", email="race@acme-demo.test"
    )

    async def first_request() -> str:
        uow = UnitOfWork(factory())
        try:
            async with uow.transaction() as session:
                user, _ = await resolve_user(session, s, principal)
                return str(user.id)
        finally:
            await uow.close()

    ids = await asyncio.gather(*(first_request() for _ in range(6)))
    assert len(set(ids)) == 1
    uow = UnitOfWork(factory())
    try:
        async with uow.transaction() as session:
            users = (
                (await session.execute(select(User).where(User.email == "race@acme-demo.test")))
                .scalars()
                .all()
            )
            links = (
                (
                    await session.execute(
                        select(UserIdentity).where(UserIdentity.subject == "oid-race")
                    )
                )
                .scalars()
                .all()
            )
    finally:
        await uow.close()
    assert len(users) == 1 and len(links) == 1
