"""S3.5.2: AI usage and settings (admin). Workspace AI policy (enable/disable, budget override,
auto-apply policy) stored in ``workspaces.settings['ai']``, how it combines with the environment,
the usage report from ``llm_calls``, and the two admin endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.ai.actions import ProposedCall
from momentum.ai.errors import AIDisabled, BudgetExceeded
from momentum.ai.loop import LoopResult, emit_proposals
from momentum.ai.models import LlmCall
from momentum.ai.prefs import AiPrefs, set_prefs
from momentum.ai.tools.catalog import build_registry
from momentum.ai.usage import DbUsageLog
from momentum.ai.usage_report import get_usage_report
from momentum.core.db import UnitOfWork
from momentum.core.errors import Forbidden
from momentum.core.settings import Settings
from momentum.core.undo import undo
from momentum.domain.workspace.service import (
    AiConfig,
    effective_ai,
    get_ai_config,
    get_ai_config_for_admin,
    set_ai_config,
)
from tests.ai_fixtures import World, key, world
from tests.helpers import Clients, ctx_for

_ = world


# ======================= service: config, permissions, undo =======================


async def test_untouched_workspace_matches_the_environment(uow: UnitOfWork, world: World) -> None:
    async with uow.transaction() as s:
        config = await get_ai_config(s, world.ravi.workspace_id)
    assert config == AiConfig()
    eff = effective_ai(world.ravi.settings, config)
    assert eff.enabled == world.ravi.settings.ai_enabled
    assert eff.monthly_budget_usd == world.ravi.settings.ai_monthly_budget_usd
    assert eff.allow_auto_apply is True


async def test_only_a_workspace_admin_can_read_or_change_settings(
    uow: UnitOfWork, world: World, settings: Settings
) -> None:
    with pytest.raises(Forbidden):
        async with uow.transaction() as s:
            await get_ai_config_for_admin(s, world.ravi)
    with pytest.raises(Forbidden):
        async with uow.transaction() as s:
            await set_ai_config(s, world.ravi, AiConfig(enabled=False))
    admin = await ctx_for(uow, settings, "admin")
    async with uow.transaction() as s:
        config, eff = await get_ai_config_for_admin(s, admin)
    assert config == AiConfig() and eff.enabled is True


async def test_environment_bounds_the_workspace_override(uow: UnitOfWork, world: World) -> None:
    """An admin can switch AI off where the environment allows it, but never on where the
    environment disabled it (the outer kill switch always wins)."""
    off_env = world.ravi.settings.model_copy(update={"ai_enabled": False})
    on_override = AiConfig(enabled=True)
    assert effective_ai(off_env, on_override).enabled is False
    on_env = world.ravi.settings.model_copy(update={"ai_enabled": True})
    off_override = AiConfig(enabled=False)
    assert effective_ai(on_env, off_override).enabled is False
    assert effective_ai(on_env, AiConfig()).enabled is True


async def test_set_ai_config_records_activity_and_undoes(
    uow: UnitOfWork, world: World, settings: Settings
) -> None:
    admin = await ctx_for(uow, settings, "admin")
    async with uow.transaction() as s:
        m = await set_ai_config(
            s, admin, AiConfig(enabled=False, monthly_budget_usd=25, allow_auto_apply=False)
        )
    assert m.entity.enabled is False and m.entity.monthly_budget_usd == 25
    async with uow.transaction() as s:
        config = await get_ai_config(s, admin.workspace_id)
    assert config == AiConfig(enabled=False, monthly_budget_usd=25, allow_auto_apply=False)
    async with uow.transaction() as s:
        await undo(s, admin, activity_id=m.activity_id)
    async with uow.transaction() as s:
        restored = await get_ai_config(s, admin.workspace_id)
    assert restored == AiConfig()


# ======================= enforcement: preflight and auto-apply =======================


async def test_workspace_disabled_blocks_calls_even_though_the_environment_allows_ai(
    uow: UnitOfWork,
    world: World,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    admin = await ctx_for(uow, settings, "admin")
    async with uow.transaction() as s:
        await set_ai_config(s, admin, AiConfig(enabled=False))
    usage = DbUsageLog(session_factory, 0)
    with pytest.raises(AIDisabled):
        await usage.check_enabled(world.ravi)


async def test_workspace_budget_override_is_used_instead_of_the_environment_default(
    uow: UnitOfWork,
    world: World,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    admin = await ctx_for(uow, settings, "admin")
    async with uow.transaction() as s:
        await set_ai_config(s, admin, AiConfig(monthly_budget_usd=5))
    async with session_factory() as session, session.begin():
        session.add(
            LlmCall(
                workspace_id=world.ravi.workspace_id,
                feature="chat",
                alias="default",
                model="m",
                status="ok",
                cost_usd=Decimal(5),
            )
        )
    usage = DbUsageLog(session_factory, 0)  # environment default: unlimited
    with pytest.raises(BudgetExceeded):
        await usage.check_budget(world.ravi)


async def test_admin_can_switch_off_auto_apply_workspace_wide(
    uow: UnitOfWork, world: World, settings: Settings
) -> None:
    admin = await ctx_for(uow, settings, "admin")
    async with uow.transaction() as s:
        await set_prefs(s, world.ravi, AiPrefs(auto_apply_low_risk=True))
        await set_ai_config(s, admin, AiConfig(allow_auto_apply=False))
    registry = build_registry()
    events: list[tuple[str, dict[str, object]]] = []

    async def emit(kind: str, data: dict[str, object]) -> None:
        events.append((kind, data))

    async with uow.transaction() as s:
        result = LoopResult(
            text="", proposals=[ProposedCall(tool="complete_task", args={"task": key(world.faq)})]
        )
        await emit_proposals(s, world.ravi, registry, result, emit, source="command")
    kinds = [k for k, _ in events]
    assert "action_proposed" in kinds and "action_applied" not in kinds


# ======================= usage report =======================


async def test_usage_report_aggregates_by_feature_user_and_day(
    uow: UnitOfWork,
    world: World,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    admin = await ctx_for(uow, settings, "admin")
    today = datetime.now(UTC)
    yesterday = today - timedelta(days=1)
    async with session_factory() as session, session.begin():
        session.add_all(
            [
                LlmCall(
                    workspace_id=world.ravi.workspace_id,
                    feature="chat",
                    alias="default",
                    model="m",
                    user_id=world.ravi.actor.id,
                    tokens_in=100,
                    tokens_out=50,
                    cost_usd=Decimal("0.01"),
                    status="ok",
                    created_at=today,
                ),
                LlmCall(
                    workspace_id=world.ravi.workspace_id,
                    feature="chat",
                    alias="default",
                    model="m",
                    user_id=world.ana.actor.id,
                    tokens_in=10,
                    tokens_out=5,
                    cost_usd=Decimal("0.02"),
                    status="error",
                    error_code="timeout",
                    created_at=yesterday,
                ),
                LlmCall(
                    workspace_id=world.ravi.workspace_id,
                    feature="quick_add",
                    alias="fast",
                    model="m",
                    user_id=world.ravi.actor.id,
                    tokens_in=5,
                    tokens_out=5,
                    cost_usd=Decimal("0.03"),
                    status="ok",
                    created_at=today,
                ),
            ]
        )
    async with uow.transaction() as s:
        report = await get_usage_report(s, admin, days=30)
    by_feature = {r.feature: r for r in report.by_feature}
    assert by_feature["chat"].calls == 2 and by_feature["chat"].errors == 1
    assert by_feature["quick_add"].calls == 1
    assert report.month_spend_usd == Decimal("0.06")
    by_user = {r.user_id: r for r in report.by_user}
    assert by_user[world.ravi.actor.id].calls == 2
    assert by_user[world.ana.actor.id].calls == 1
    assert len(report.by_day) == 2  # today and yesterday


async def test_usage_report_requires_admin(uow: UnitOfWork, world: World) -> None:
    with pytest.raises(Forbidden):
        async with uow.transaction() as s:
            await get_usage_report(s, world.ravi)


# ======================= API =======================


async def test_admin_settings_and_usage_endpoints(
    as_user: Clients, uow: UnitOfWork, world: World
) -> None:
    admin = await as_user("admin")
    ravi = await as_user("ravi")
    assert (await ravi.get("/api/v1/ai/admin/settings")).status_code == 403
    assert (await ravi.get("/api/v1/ai/admin/usage")).status_code == 403
    r = await admin.get("/api/v1/ai/admin/settings")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["config"] == {"enabled": None, "monthly_budget_usd": None, "allow_auto_apply": None}
    assert body["effective"]["enabled"] is True
    assert body["models"]["default"]
    r = await admin.put("/api/v1/ai/admin/settings", json={"enabled": False})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["enabled"] is False
    assert r.json()["meta"]["activity_id"]
    r = await admin.get("/api/v1/ai/admin/usage")
    assert r.status_code == 200, r.text
    assert r.json()["by_feature"] == []
