"""S5.1.1: agent management: install from definitions, create, edit, enable, and project access.

Rules (docs/roadmap/phase-5-kickoff.md §5):
- Only workspace admins manage agents; every non-guest can see them (they're teammates).
- Each agent acts as its own user account (``users.is_agent``). **Access is explicit project
  membership** of that account (Q1): giving an agent a project goes through the ordinary
  project-member write path, so it shows in Share and anyone who may share the project may
  remove it. An agent is never a project admin and never a team member (team membership would
  grant implicit access to every team-visible project).
- Agents are disabled, never deleted. Installed agents start **disabled** (Q3).
- Agent configuration is configuration, not task data: changes record activity and events but
  no undo payload (like rules, fields and tags).

Tool names are validated against the caller's tool registry, passed in as ``tool_names``: the
domain layer never imports the AI package.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import Diff, record_activity
from momentum.core.context import Ctx
from momentum.core.errors import Conflict, Forbidden, NotFound, ValidationFailed, VersionConflict
from momentum.core.events import emit
from momentum.core.ids import new_id
from momentum.core.mutation import Mutation
from momentum.core.permissions import Action, can
from momentum.domain.access import visible_projects_clause
from momentum.domain.agents.models import Agent
from momentum.domain.agents.schemas import (
    AgentConfig,
    AgentDefinition,
    AgentIn,
    AgentPatchIn,
    InstallOutcome,
)
from momentum.domain.agents.stats import agent_stats
from momentum.domain.projects import service as projects_service
from momentum.domain.projects.models import Project, ProjectMember
from momentum.domain.users.models import User

# The fields a definition file controls; `enabled` is the admin's, never a definition's.
CONFIG_FIELDS = tuple(AgentConfig.model_fields)
AGENT_EMAIL_DOMAIN = "agents.momentum.invalid"  # .invalid can never be a real mailbox


@dataclass(frozen=True)
class InstallResult:
    key: str
    outcome: InstallOutcome
    agent: Agent


# ---------- helpers ----------


def _require_admin(ctx: Ctx) -> None:
    if not can(ctx, Action.WORKSPACE_ADMIN):
        raise Forbidden("Only workspace admins can manage agents")


def _require_member(ctx: Ctx) -> None:
    if ctx.actor.role == "guest":
        raise Forbidden("Guests can't see agents")


def _channels(ctx: Ctx) -> list[str]:
    return [f"workspace:{ctx.workspace_id}"]


def canonical(cfg: AgentConfig) -> dict[str, Any]:
    """The configuration as stored: JSON-safe, and the same whether it came from YAML, the API or
    a row (so hashes compare)."""
    data = cfg.model_dump(mode="json", include=set(CONFIG_FIELDS))
    data["budget_monthly_usd"] = f"{Decimal(cfg.budget_monthly_usd):.2f}"
    return data


def config_hash(cfg: AgentConfig) -> str:
    raw = json.dumps(canonical(cfg), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def config_of(agent: Agent) -> AgentConfig:
    return AgentConfig.model_validate({f: getattr(agent, f) for f in CONFIG_FIELDS})


def is_drifted(agent: Agent) -> bool:
    """An installed agent an admin has edited since its definition was last applied."""
    return (
        agent.installed_hash is not None and config_hash(config_of(agent)) != agent.installed_hash
    )


def _check(ctx: Ctx, cfg: AgentConfig, tool_names: Collection[str]) -> None:
    unknown = sorted(set(cfg.tools) - set(tool_names))
    if unknown:
        raise ValidationFailed(f"Unknown tool(s): {', '.join(unknown)}")
    if cfg.limits.max_steps is not None and cfg.limits.max_steps > ctx.settings.agent_max_steps:
        raise ValidationFailed(
            f"max_steps can be at most {ctx.settings.agent_max_steps} (MOMENTUM_AGENT_MAX_STEPS)"
        )
    if cfg.limits.timeout_s is not None and cfg.limits.timeout_s > ctx.settings.agent_timeout_s:
        raise ValidationFailed(
            f"timeout_s can be at most {ctx.settings.agent_timeout_s} (MOMENTUM_AGENT_TIMEOUT_S)"
        )


def _apply(agent: Agent, cfg: AgentConfig) -> Diff:
    """Write ``cfg`` onto the row; returns what changed."""
    data = canonical(cfg)
    data["budget_monthly_usd"] = Decimal(data["budget_monthly_usd"])
    changes: Diff = {}
    for name, value in data.items():
        old = getattr(agent, name)
        if old != value:
            changes[name] = (old, value)
            setattr(agent, name, value)
    return changes


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:50] or "agent"
    if not base[0].isalpha():
        base = f"agent_{base}"[:50]
    return base if len(base) >= 2 else f"{base}_agent"  # keys are at least 2 characters


async def _by_key(session: AsyncSession, ctx: Ctx, key: str) -> Agent | None:
    return (
        await session.execute(
            select(Agent).where(Agent.workspace_id == ctx.workspace_id, Agent.key == key)
        )
    ).scalar_one_or_none()


async def _free_key(session: AsyncSession, ctx: Ctx, base: str) -> str:
    key, n = base, 1
    while await _by_key(session, ctx, key) is not None:
        n += 1
        key = f"{base}_{n}"
    return key


async def _load(session: AsyncSession, ctx: Ctx, agent_id: uuid.UUID) -> Agent:
    agent = await session.get(Agent, agent_id)
    if agent is None or agent.workspace_id != ctx.workspace_id:
        raise NotFound("Agent not found")
    return agent


async def _create(
    session: AsyncSession,
    ctx: Ctx,
    key: str,
    cfg: AgentConfig,
    *,
    source: str,
    installed_hash: str | None,
) -> tuple[Agent, uuid.UUID]:
    user = User(
        id=new_id(),
        workspace_id=ctx.workspace_id,
        email=f"{key}@{AGENT_EMAIL_DOMAIN}",
        name=cfg.name,
        role="member",
        status="active",
        timezone="UTC",
        prefs={},
        is_agent=True,
    )
    session.add(user)
    await session.flush()  # the account first: agents.user_id and users.agent_id point both ways
    agent = Agent(
        workspace_id=ctx.workspace_id,
        user_id=user.id,
        key=key,
        enabled=False,
        source=source,
        installed_hash=installed_hash,
        created_by=ctx.actor.id,
        version=1,
    )
    _apply(agent, cfg)
    session.add(agent)
    await session.flush()
    user.agent_id = agent.id
    act = await record_activity(
        session,
        ctx,
        entity_type="agent",
        entity_id=agent.id,
        verb="agent.created",
        changes={"name": (None, agent.name), "source": (None, source)},
    )
    await emit(
        session,
        ctx,
        type="agent.created",
        entity_type="agent",
        entity_id=agent.id,
        data={"key": key, "source": source},
        channels=_channels(ctx),
        activity_id=act.id,
    )
    return agent, act.id


async def _updated(
    session: AsyncSession, ctx: Ctx, agent: Agent, changes: Diff
) -> uuid.UUID | None:
    if not changes:
        return None
    agent.version += 1
    agent.updated_at = datetime.now(UTC)
    if "name" in changes:
        user = await session.get(User, agent.user_id)
        if user is not None:
            user.name = agent.name
    act = await record_activity(
        session,
        ctx,
        entity_type="agent",
        entity_id=agent.id,
        verb="agent.updated",
        changes=changes,
    )
    await emit(
        session,
        ctx,
        type="agent.updated",
        entity_type="agent",
        entity_id=agent.id,
        data={"changes": sorted(changes), "version": agent.version},
        channels=_channels(ctx),
        activity_id=act.id,
    )
    return act.id


# ---------- reads ----------


async def list_agents(session: AsyncSession, ctx: Ctx) -> list[Agent]:
    _require_member(ctx)
    rows = await session.execute(
        select(Agent).where(Agent.workspace_id == ctx.workspace_id).order_by(Agent.name, Agent.id)
    )
    return list(rows.scalars())


async def get_agent(session: AsyncSession, ctx: Ctx, agent_id: uuid.UUID) -> Agent:
    _require_member(ctx)
    return await _load(session, ctx, agent_id)


async def get_agent_for_admin(session: AsyncSession, ctx: Ctx, agent_id: uuid.UUID) -> Agent:
    _require_admin(ctx)
    return await _load(session, ctx, agent_id)


async def agent_projects(
    session: AsyncSession, ctx: Ctx, agent: Agent
) -> list[tuple[Project, str]]:
    """The projects the agent's account is a member of, **limited to those the caller can see**
    (a private project's name must not leak through an agent's detail page)."""
    rows = await session.execute(
        select(Project, ProjectMember.role)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(
            ProjectMember.user_id == agent.user_id,
            Project.deleted_at.is_(None),
            visible_projects_clause(ctx),
        )
        .order_by(Project.name, Project.id)
    )
    return [(p, role) for p, role in rows.tuples()]


# ---------- writes ----------


async def create_agent(
    session: AsyncSession, ctx: Ctx, data: AgentIn, tool_names: Collection[str]
) -> Mutation[Agent]:
    """A custom agent (disabled until an admin enables it)."""
    _require_admin(ctx)
    if data.kind == "handler":
        raise ValidationFailed(
            "Code-backed agents come from the host application's agent definitions"
        )
    if data.autonomy == "auto":
        # S5.1.4 (agents.md §5): acting alone is earned with a track record, never a default
        raise ValidationFailed(
            "A new agent starts at confirm or suggest; promote it to auto once it has earned it",
            code="not_eligible",
        )
    _check(ctx, data, tool_names)
    if data.key is not None:
        if await _by_key(session, ctx, data.key) is not None:
            raise Conflict("An agent with that key already exists", code="duplicate")
        key = data.key
    else:
        key = await _free_key(session, ctx, _slug(data.name))
    cfg = AgentConfig.model_validate(data.model_dump(include=set(CONFIG_FIELDS)))
    agent, activity_id = await _create(session, ctx, key, cfg, source="custom", installed_hash=None)
    return Mutation(agent, activity_id, version=agent.version)


async def update_agent(
    session: AsyncSession,
    ctx: Ctx,
    agent_id: uuid.UUID,
    data: AgentPatchIn,
    tool_names: Collection[str],
) -> Mutation[Agent]:
    _require_admin(ctx)
    agent = await _load(session, ctx, agent_id)
    if data.expected_version is not None and data.expected_version != agent.version:
        raise VersionConflict("This agent was changed by someone else", version=agent.version)
    patch = data.model_dump(exclude_unset=True, exclude={"enabled", "expected_version"})
    try:
        cfg = AgentConfig.model_validate(
            {**config_of(agent).model_dump(include=set(CONFIG_FIELDS)), **patch}
        )
    except ValueError as e:
        raise ValidationFailed(str(e)) from e
    _check(ctx, cfg, tool_names)
    if cfg.autonomy == "auto" and agent.autonomy != "auto":
        stats = await agent_stats(session, agent)
        if not stats.eligible_for_auto:
            raise ValidationFailed(
                f"{agent.name} can't act on its own yet: " + "; ".join(stats.reasons),
                code="not_eligible",
            )
    changes = _apply(agent, cfg)
    if data.enabled is not None and data.enabled != agent.enabled:
        changes["enabled"] = (agent.enabled, data.enabled)
        agent.enabled = data.enabled
        if data.enabled:
            agent.enabled_at = datetime.now(UTC)
    activity_id = await _updated(session, ctx, agent, changes)
    return Mutation(agent, activity_id, version=agent.version)


async def install_definitions(
    session: AsyncSession,
    ctx: Ctx,
    definitions: Sequence[tuple[AgentDefinition, str]],
    tool_names: Collection[str],
    *,
    keys: Collection[str] | None = None,
    force: bool = False,
) -> list[InstallResult]:
    """Install or refresh agents from definitions (``(definition, source)`` pairs, source
    ``starter`` or ``host``). Idempotent by ``key``:

    - new key → a disabled agent with its own account (``installed``);
    - definition unchanged since the last install → ``unchanged``;
    - definition changed and the row untouched since the last install → ``updated``;
    - the row was edited by an admin (or is a custom agent with the same key) → left alone
      (``drifted``), unless ``force`` (``forced``).

    ``enabled`` is never touched: turning an agent on is the admin's decision.
    """
    _require_admin(ctx)
    by_key = {d.key: (d, source) for d, source in definitions}
    wanted = list(keys) if keys else list(by_key)
    missing = [k for k in wanted if k not in by_key]
    if missing:
        raise ValidationFailed(f"No agent definition for: {', '.join(sorted(missing))}")
    results: list[InstallResult] = []
    for key in wanted:
        definition, source = by_key[key]
        cfg = AgentConfig.model_validate(definition.model_dump(include=set(CONFIG_FIELDS)))
        _check(ctx, cfg, tool_names)
        new_hash = config_hash(cfg)
        agent = await _by_key(session, ctx, key)
        if agent is None:
            agent, _ = await _create(session, ctx, key, cfg, source=source, installed_hash=new_hash)
            results.append(InstallResult(key, "installed", agent))
            continue
        if agent.installed_hash == new_hash and not is_drifted(agent):
            results.append(InstallResult(key, "unchanged", agent))
            continue
        drifted = agent.installed_hash is None or is_drifted(agent)
        if drifted and not force:
            results.append(InstallResult(key, "drifted", agent))
            continue
        changes = _apply(agent, cfg)
        if agent.source != source:
            changes["source"] = (agent.source, source)
            agent.source = source
        agent.installed_hash = new_hash
        await _updated(session, ctx, agent, changes)
        results.append(InstallResult(key, "forced" if drifted else "updated", agent))
    return results


async def add_to_project(
    session: AsyncSession, ctx: Ctx, agent_id: uuid.UUID, project_id: uuid.UUID, role: str
) -> Mutation[Any]:
    """Make the agent's account a member of a project: the ordinary sharing path, so the caller
    needs admin on that project (like sharing it with a person) and the change can be undone."""
    _require_member(ctx)
    agent = await _load(session, ctx, agent_id)
    return await projects_service.add_member(session, ctx, project_id, agent.user_id, role)


async def remove_from_project(
    session: AsyncSession, ctx: Ctx, agent_id: uuid.UUID, project_id: uuid.UUID
) -> Mutation[Any]:
    _require_member(ctx)
    agent = await _load(session, ctx, agent_id)
    if agent.user_id == ctx.actor.id:
        raise Forbidden("An agent can't change its own access")
    return await projects_service.remove_member(session, ctx, project_id, agent.user_id)


async def demote(session: AsyncSession, ctx: Ctx, agent: Agent, reason: str) -> Mutation[Agent]:
    """S5.1.4: back to ``confirm`` after too many of its own changes were undone (the daily
    job decides; see ``stats.should_demote``). The reason is kept on the activity row."""
    if agent.autonomy != "auto":
        return Mutation(agent, version=agent.version)
    agent.autonomy = "confirm"
    changes: Diff = {"autonomy": ("auto", "confirm"), "reason": (None, reason)}
    activity_id = await _updated(session, ctx, agent, changes)
    return Mutation(agent, activity_id, version=agent.version)
