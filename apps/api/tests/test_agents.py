"""S5.1.1: agents — definitions, install, accounts, admin API, and explicit project access
(kickoff Q1: an agent sees only what its own account was given)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from momentum.agents.loader import PACKAGED_DIR, DefinitionError, load_definitions
from momentum.ai.tools.catalog import build_registry
from momentum.auth.base import Principal
from momentum.auth.identity import resolve_user
from momentum.core.activity import Activity
from momentum.core.context import Actor, Ctx
from momentum.core.db import UnitOfWork
from momentum.core.errors import NotFound, NotInvited, ValidationFailed
from momentum.core.events import OutboxEvent
from momentum.core.settings import Settings
from momentum.domain.access import get_visible_project
from momentum.domain.agents import service
from momentum.domain.agents.models import Agent
from momentum.domain.agents.schemas import AgentDefinition, ScheduleTrigger
from momentum.domain.users.models import User
from momentum.domain.workspace.service import ensure_default_workspace
from tests.conftest import AppFactory, make_settings
from tests.helpers import Clients, ctx_for

BASE = "/api/v1"
STARTERS = {
    "daily_digest",
    "meeting_notes",
    "nudger",
    "planner",
    "risk_watcher",
    "status_reporter",
    "teammate",
    "triage",
}
TOOLS = build_registry().names


def _defn(key: str = "helper", **over: Any) -> AgentDefinition:
    return AgentDefinition.model_validate(
        {"key": key, "name": "Helper", "tools": ["get_task"], **over}
    )


async def _agent_ctx(uow: UnitOfWork, settings: Settings, agent: Agent) -> Ctx:
    async with uow.transaction() as s:
        user = await s.get(User, agent.user_id)
        assert user is not None
        return Ctx(
            actor=Actor(id=user.id, workspace_id=user.workspace_id, is_agent=True),
            settings=settings,
            via="agent",
        )


async def _install(c: httpx.AsyncClient, **body: Any) -> dict[str, str]:
    r = await c.post(f"{BASE}/agents/install", json=body)
    assert r.status_code == 200, r.text
    return {row["key"]: row["outcome"] for row in r.json()["results"]}


async def _agents(c: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
    r = await c.get(f"{BASE}/agents")
    assert r.status_code == 200, r.text
    return {a["key"]: a for a in r.json()["data"]}


async def _project(c: httpx.AsyncClient, name: str) -> str:
    return next(
        p["id"] for p in (await c.get(f"{BASE}/projects")).json()["data"] if p["name"] == name
    )


# ---------- definitions ----------


def test_starter_definitions_load_and_encode_the_kickoff_decisions() -> None:
    defs = {d.key: (d, source) for d, source in load_definitions()}
    assert set(defs) == STARTERS
    assert {source for _, source in defs.values()} == {"starter"}
    # kickoff Q2: the agents.md §4 autonomy table
    autonomy = {k: d.autonomy for k, (d, _) in defs.items()}
    assert autonomy == {
        "daily_digest": "auto",
        "triage": "confirm",
        "status_reporter": "confirm",
        "nudger": "auto",
        "planner": "confirm",
        "meeting_notes": "confirm",
        "risk_watcher": "suggest",
        "teammate": "confirm",
    }
    # kickoff Q4 set Pulse $10 and the rest $5 for 10-15 people; Phase 7 sized them for ~150
    # people and ~60 projects (each definition says how)
    assert {
        k: (str(d.budget_monthly_usd), d.budget_monthly_tokens) for k, (d, _) in defs.items()
    } == {
        "daily_digest": ("40", 12_000_000),
        "risk_watcher": ("25", 8_000_000),
        "teammate": ("25", 8_000_000),
        "nudger": ("15", 5_000_000),
        "status_reporter": ("15", 5_000_000),
        "planner": ("10", 4_000_000),
        "meeting_notes": ("10", 4_000_000),
        "triage": ("10", 4_000_000),
    }
    # every tool a starter names exists, and none is one agents may never use
    for d, _ in defs.values():
        assert set(d.tools) <= set(TOOLS), d.key
        assert not {"delete_task", "decide_approval"} & set(d.tools)


def test_definition_files_are_named_after_their_key() -> None:
    assert {p.stem for p in PACKAGED_DIR.glob("*.yaml")} == STARTERS


def test_loader_reports_the_bad_file(tmp_path: Path) -> None:
    (tmp_path / "broken.yaml").write_text("key: broken\nname: Broken\ntools: [delete_task]\n")
    with pytest.raises(DefinitionError, match=r"(?s)broken\.yaml.*delete_task"):
        load_definitions([tmp_path])


def test_loader_rejects_a_key_that_differs_from_the_file_name(tmp_path: Path) -> None:
    (tmp_path / "one.yaml").write_text("key: two\nname: Two\n")
    with pytest.raises(DefinitionError, match="must match the file name"):
        load_definitions([tmp_path])


def test_a_host_cannot_redefine_a_starter_key(tmp_path: Path) -> None:
    (tmp_path / "teammate.yaml").write_text("key: teammate\nname: Mine\n")
    with pytest.raises(DefinitionError, match="already defined"):
        load_definitions([tmp_path])


def test_host_definitions_are_loaded_as_host(tmp_path: Path) -> None:
    (tmp_path / "invoice_reader.yaml").write_text(
        "key: invoice_reader\nname: Invoice Reader\nkind: handler\nhandler: acme.invoices:read\n"
        "triggers: [{type: assigned}]\n"
    )
    host = [(d, s) for d, s in load_definitions([tmp_path]) if s == "host"]
    assert [(d.key, d.kind, d.handler) for d, _ in host] == [
        ("invoice_reader", "handler", "acme.invoices:read")
    ]


def test_missing_definitions_directory_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(DefinitionError, match="not found"):
        load_definitions([tmp_path / "nope"])


@pytest.mark.parametrize(
    ("trigger", "ok"),
    [
        ({"type": "schedule", "cron": "0 15 * * FRI"}, True),
        ({"type": "schedule", "cron": "30 8 * * 1-5", "timezone": "user"}, True),
        ({"type": "schedule", "cron": "0 9 * * *", "timezone": "Asia/Kolkata"}, True),
        ({"type": "schedule", "cron": "every friday"}, False),
        ({"type": "schedule", "cron": "0 0 9 * * *"}, False),  # 6 fields
        ({"type": "schedule", "cron": "0 9 * * *", "timezone": "Mars/Base"}, False),
        ({"type": "event", "event": "task.created"}, True),
        ({"type": "event", "event": "created"}, False),
        ({"type": "event", "event": "task.created", "filter": {"sql": "1=1"}}, False),
        ({"type": "assigned"}, True),
        ({"type": "sometimes"}, False),
    ],
)
def test_trigger_validation(trigger: dict[str, Any], ok: bool) -> None:
    if ok:
        _defn(triggers=[trigger])
    else:
        with pytest.raises(ValidationError):
            _defn(triggers=[trigger])


def test_handler_kind_needs_a_handler_and_llm_kind_has_none() -> None:
    with pytest.raises(ValidationError, match="needs `handler`"):
        _defn(kind="handler")
    with pytest.raises(ValidationError, match="Only handler agents"):
        _defn(handler="x.y:z")
    assert isinstance(
        _defn(triggers=[{"type": "schedule", "cron": "0 8 * * *"}]).triggers[0], ScheduleTrigger
    )


# ---------- install ----------


async def test_install_creates_disabled_agents_with_their_own_accounts(
    as_user: Clients, uow: UnitOfWork
) -> None:
    admin = await as_user("admin")
    assert await _install(admin) == {k: "installed" for k in STARTERS}
    agents = await _agents(admin)
    assert set(agents) == STARTERS
    assert all(not a["enabled"] and a["source"] == "starter" for a in agents.values())
    assert not any(a["drifted"] for a in agents.values())
    async with uow.transaction() as s:
        accounts = list((await s.execute(select(User).where(User.is_agent.is_(True)))).scalars())
        assert len(accounts) == len(STARTERS)
        by_user = {a["user_id"]: a for a in agents.values()}
        for u in accounts:
            assert u.email.endswith("@agents.momentum.invalid")
            assert str(u.agent_id) == by_user[str(u.id)]["id"]
            assert u.name == by_user[str(u.id)]["name"]
        # every install is audited and published, in the same transaction
        created = await s.scalar(
            select(func.count()).select_from(Activity).where(Activity.verb == "agent.created")
        )
        events = await s.scalar(
            select(func.count()).select_from(OutboxEvent).where(OutboxEvent.type == "agent.created")
        )
        assert created == events == len(STARTERS)
    # agents still don't show up as people (people pickers are for humans until S5.2.1)
    people = (await admin.get(f"{BASE}/users")).json()["data"]
    assert not any(p.get("is_agent") for p in people)
    # safe to re-run
    assert await _install(admin) == {k: "unchanged" for k in STARTERS}


async def test_reinstall_keeps_an_admins_edits_unless_forced(as_user: Clients) -> None:
    admin = await as_user("admin")
    await _install(admin, keys=["nudger"])
    nudger = (await _agents(admin))["nudger"]
    r = await admin.patch(f"{BASE}/agents/{nudger['id']}", json={"autonomy": "confirm"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["drifted"] is True
    assert await _install(admin, keys=["nudger"]) == {"nudger": "drifted"}
    assert (await _agents(admin))["nudger"]["autonomy"] == "confirm"
    assert await _install(admin, keys=["nudger"], force=True) == {"nudger": "forced"}
    after = (await _agents(admin))["nudger"]
    assert after["autonomy"] == "auto" and after["drifted"] is False


async def test_a_changed_definition_updates_an_untouched_agent(
    uow: UnitOfWork, settings: Settings, seeded: None
) -> None:
    ctx = await ctx_for(uow, settings, "admin")
    async with uow.transaction() as s:
        [r] = await service.install_definitions(s, ctx, [(_defn(), "host")], TOOLS)
        assert r.outcome == "installed" and r.agent.source == "host"
    async with uow.transaction() as s:
        newer = _defn(description="Now with a description", model_alias="fast")
        [r] = await service.install_definitions(s, ctx, [(newer, "host")], TOOLS)
        assert r.outcome == "updated"
        assert (r.agent.description, r.agent.model_alias, r.agent.version) == (
            "Now with a description",
            "fast",
            2,
        )
        assert r.agent.enabled is False


async def test_install_refuses_unknown_keys_and_unknown_tools(
    uow: UnitOfWork, settings: Settings, seeded: None
) -> None:
    ctx = await ctx_for(uow, settings, "admin")
    async with uow.transaction() as s:
        with pytest.raises(ValidationFailed, match="No agent definition for: ghost"):
            await service.install_definitions(s, ctx, [(_defn(), "host")], TOOLS, keys=["ghost"])
        with pytest.raises(ValidationFailed, match="Unknown tool"):
            await service.install_definitions(
                s, ctx, [(_defn(tools=["push_to_erp"]), "host")], TOOLS
            )


async def test_host_definition_dirs_reach_the_install_endpoint(
    app_factory: AppFactory, seeded: None, tmp_path: Path, settings: Settings
) -> None:
    from momentum.app import create_app

    (tmp_path / "contract_drafter.yaml").write_text(
        "key: contract_drafter\nname: Contract Drafter\ntools: [get_task, add_comment]\n"
    )
    app = create_app(settings, agent_definition_dirs=[tmp_path])
    async with app.router.lifespan_context(app):
        clients = Clients(app)
        admin = await clients("admin")
        result = await _install(admin, keys=["contract_drafter"])
        assert result == {"contract_drafter": "installed"}
        assert (await _agents(admin))["contract_drafter"]["source"] == "host"
        await clients.close()


# ---------- admin API ----------


async def test_only_admins_manage_agents_but_members_can_see_them(as_user: Clients) -> None:
    admin, ravi = await as_user("admin"), await as_user("ravi")
    assert (await ravi.post(f"{BASE}/agents/install", json={})).status_code == 403
    await _install(admin, keys=["teammate"])
    teammate = (await _agents(ravi))["teammate"]  # members can list
    assert (await ravi.get(f"{BASE}/agents/{teammate['id']}")).status_code == 200
    r = await ravi.patch(f"{BASE}/agents/{teammate['id']}", json={"enabled": True})
    assert r.status_code == 403
    r = await ravi.post(f"{BASE}/agents", json={"name": "Mine"})
    assert r.status_code == 403


async def test_guests_cannot_see_agents(uow: UnitOfWork, settings: Settings, seeded: None) -> None:
    ctx = await ctx_for(uow, settings, "ravi")
    guest = ctx.with_(actor=Actor(id=ctx.actor.id, workspace_id=ctx.workspace_id, role="guest"))
    async with uow.transaction() as s:
        with pytest.raises(Exception, match="Guests"):
            await service.list_agents(s, guest)


async def test_create_a_custom_agent(as_user: Clients) -> None:
    admin = await as_user("admin")
    body = {
        "name": "Release Notes Writer",
        "description": "Drafts release notes from completed tasks",
        "instructions": "Summarize what shipped.",
        "triggers": [{"type": "manual"}, {"type": "mentioned"}],
        "tools": ["search_tasks", "add_comment"],
        "autonomy": "suggest",
        "budget_monthly_usd": "2.50",
        "limits": {"max_steps": 6, "timeout_s": 120},
    }
    r = await admin.post(f"{BASE}/agents", json=body)
    assert r.status_code == 201, r.text
    a = r.json()["data"]
    assert (a["key"], a["source"], a["enabled"], a["drifted"]) == (
        "release_notes_writer",
        "custom",
        False,
        False,
    )
    assert a["budget_monthly_usd"] == "2.50" and a["budget_monthly_tokens"] == 2_000_000
    assert a["triggers"] == [{"type": "manual"}, {"type": "mentioned"}]
    # a second one with the same name gets its own key
    r = await admin.post(f"{BASE}/agents", json={"name": "Release Notes Writer"})
    assert r.json()["data"]["key"] == "release_notes_writer_2"
    assert r.json()["meta"]["activity_id"]
    # a one-letter name still gets a valid key
    r = await admin.post(f"{BASE}/agents", json={"name": "Q"})
    assert r.json()["data"]["key"] == "q_agent"
    # an explicit duplicate key is refused
    r = await admin.post(f"{BASE}/agents", json={"name": "X", "key": "release_notes_writer"})
    assert r.status_code == 409


@pytest.mark.parametrize(
    ("body", "status", "message"),
    [
        ({"name": "X", "tools": ["push_to_erp"]}, 422, "Unknown tool"),
        ({"name": "X", "tools": ["delete_task"]}, 422, "delete_task"),
        ({"name": "X", "tools": ["get_task", "get_task"]}, 422, "repeat"),
        ({"name": "X", "limits": {"max_steps": 16}}, 422, "at most 15"),
        ({"name": "X", "limits": {"timeout_s": 301}}, 422, "at most 300"),
        ({"name": "X", "autonomy": "yolo"}, 422, ""),
        ({"name": "X", "model_alias": "claude-opus"}, 422, ""),
        ({"name": "X", "kind": "handler", "handler": "acme:run"}, 422, "host application"),
        ({"name": "X", "budget_monthly_usd": "-1"}, 422, ""),
    ],
)
async def test_create_validation(
    as_user: Clients, body: dict[str, Any], status: int, message: str
) -> None:
    admin = await as_user("admin")
    r = await admin.post(f"{BASE}/agents", json=body)
    assert r.status_code == status, r.text
    assert message in r.text


async def test_ceilings_come_from_settings(uow: UnitOfWork, seeded: None) -> None:
    tight = make_settings(agent_max_steps=4)
    ctx = (await ctx_for(uow, tight, "admin")).with_(settings=tight)
    async with uow.transaction() as s:
        with pytest.raises(ValidationFailed, match="at most 4"):
            await service.install_definitions(
                s, ctx, [(_defn(limits={"max_steps": 5}), "host")], TOOLS
            )


async def test_edit_enable_and_version_conflicts(as_user: Clients, uow: UnitOfWork) -> None:
    admin = await as_user("admin")
    await _install(admin, keys=["teammate"])
    t = (await _agents(admin))["teammate"]
    r = await admin.patch(
        f"{BASE}/agents/{t['id']}",
        json={"enabled": True, "name": "Teammate Tess", "expected_version": t["version"]},
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["enabled"] is True and data["version"] == t["version"] + 1
    assert r.json()["meta"]["activity_id"]
    async with uow.transaction() as s:
        account = await s.get(User, data["user_id"])
        assert account is not None and account.name == "Teammate Tess"  # the account follows
    stale = await admin.patch(
        f"{BASE}/agents/{t['id']}", json={"enabled": False, "expected_version": t["version"]}
    )
    assert stale.status_code == 409
    # what an agent *is* can't change
    for body in ({"kind": "handler"}, {"key": "other"}, {"handler": "x:y"}):
        assert (await admin.patch(f"{BASE}/agents/{t['id']}", json=body)).status_code == 422
    assert (
        await admin.patch(f"{BASE}/agents/{t['id']}", json={"tools": ["delete_task"]})
    ).status_code == 422
    # a no-op patch records nothing
    same = await admin.patch(f"{BASE}/agents/{t['id']}", json={"enabled": True})
    assert same.json()["meta"]["activity_id"] is None


# ---------- access: explicit membership only (kickoff Q1) ----------


async def test_agent_access_is_explicit_project_membership(
    as_user: Clients, uow: UnitOfWork, settings: Settings
) -> None:
    admin, ravi = await as_user("admin"), await as_user("ravi")
    await _install(admin, keys=["teammate"])
    teammate = (await _agents(admin))["teammate"]
    website = await _project(ravi, "Website Revamp")  # team-visible, Product team, ravi admin
    async with uow.transaction() as s:
        agent = await s.get(Agent, teammate["id"])
        assert agent is not None
    agent_ctx = await _agent_ctx(uow, settings, agent)
    # a team-visible project is invisible to an agent that wasn't given it
    async with uow.transaction() as s:
        with pytest.raises(NotFound):
            await get_visible_project(s, agent_ctx, website)  # type: ignore[arg-type]

    # the project's admin gives it access, through the ordinary sharing path
    r = await ravi.post(f"{BASE}/agents/{teammate['id']}/projects", json={"project_id": website})
    assert r.status_code == 201, r.text
    activity_id = r.json()["meta"]["activity_id"]
    members = (await ravi.get(f"{BASE}/projects/{website}")).json()["members"]
    assert any(m["user"]["id"] == teammate["user_id"] and m["role"] == "editor" for m in members)
    async with uow.transaction() as s:
        _, role = await get_visible_project(s, agent_ctx, website)  # type: ignore[arg-type]
        assert role == "editor"
    detail = (await ravi.get(f"{BASE}/agents/{teammate['id']}")).json()
    assert [(p["name"], p["role"]) for p in detail["projects"]] == [("Website Revamp", "editor")]

    # undoable like any share
    assert (await ravi.post(f"{BASE}/undo", json={"activity_id": activity_id})).status_code == 200
    async with uow.transaction() as s:
        with pytest.raises(NotFound):
            await get_visible_project(s, agent_ctx, website)  # type: ignore[arg-type]


async def test_an_agent_is_never_a_project_admin_nor_a_team_member(as_user: Clients) -> None:
    admin, ravi = await as_user("admin"), await as_user("ravi")
    await _install(admin, keys=["teammate"])
    teammate = (await _agents(admin))["teammate"]
    website = await _project(ravi, "Website Revamp")
    r = await ravi.post(
        f"{BASE}/projects/{website}/members", json={"user_id": teammate["user_id"], "role": "admin"}
    )
    assert r.status_code == 422 and "project admins" in r.text
    r = await ravi.post(
        f"{BASE}/agents/{teammate['id']}/projects", json={"project_id": website, "role": "admin"}
    )
    assert r.status_code == 422
    await ravi.post(f"{BASE}/agents/{teammate['id']}/projects", json={"project_id": website})
    r = await ravi.patch(
        f"{BASE}/projects/{website}/members/{teammate['user_id']}", json={"role": "admin"}
    )
    assert r.status_code == 422
    teams = (await ravi.get(f"{BASE}/teams")).json()["data"]
    product = next(t["id"] for t in teams if t["name"] == "Product")
    r = await ravi.post(f"{BASE}/teams/{product}/members", json={"user_id": teammate["user_id"]})
    assert r.status_code == 422 and "project by project" in r.text


async def test_sharing_needs_admin_on_the_project(as_user: Clients) -> None:
    admin, ana, tom = await as_user("admin"), await as_user("ana"), await as_user("tom")
    await _install(admin, keys=["teammate"])
    teammate = (await _agents(admin))["teammate"]
    website = await _project(await as_user("ravi"), "Website Revamp")
    # ana is on the Product team: an editor, who can't share the project
    r = await ana.post(f"{BASE}/agents/{teammate['id']}/projects", json={"project_id": website})
    assert r.status_code == 403
    # tom isn't: for him the project doesn't exist
    r = await tom.post(f"{BASE}/agents/{teammate['id']}/projects", json={"project_id": website})
    assert r.status_code == 404


async def test_agent_detail_hides_private_projects_the_caller_cannot_see(
    as_user: Clients,
) -> None:
    admin, priya, tom = await as_user("admin"), await as_user("priya"), await as_user("tom")
    await _install(admin, keys=["teammate"])
    teammate = (await _agents(admin))["teammate"]
    mobile = await _project(priya, "Mobile App v2")  # private: priya (admin) and ravi
    r = await priya.post(f"{BASE}/agents/{teammate['id']}/projects", json={"project_id": mobile})
    assert r.status_code == 201, r.text
    mine = (await priya.get(f"{BASE}/agents/{teammate['id']}")).json()["projects"]
    theirs = (await tom.get(f"{BASE}/agents/{teammate['id']}")).json()["projects"]
    assert [p["name"] for p in mine] == ["Mobile App v2"]
    assert theirs == []


async def test_agent_accounts_never_sign_in(uow: UnitOfWork, as_user: Clients) -> None:
    admin = await as_user("admin")
    await _install(admin, keys=["teammate"])
    open_domains = make_settings(allowed_email_domains="")
    async with uow.transaction() as s:
        with pytest.raises(NotInvited):
            await resolve_user(
                s,
                open_domains,
                Principal(provider="dev", subject="x", email="teammate@agents.momentum.invalid"),
            )
    agent_user_id = (await _agents(admin))["teammate"]["user_id"]
    users = (await admin.get(f"{BASE}/dev/users")).json()
    assert agent_user_id not in {u["id"] for u in users}  # not offered as a dev login
    r = await admin.post(f"{BASE}/dev/login", json={"user_id": agent_user_id})
    assert r.status_code in (403, 404), r.text


async def test_workspace_admin_agents_have_no_admin_shortcut(
    uow: UnitOfWork, settings: Settings, seeded: None
) -> None:
    """Even an agent account somehow given the admin role sees only explicit projects."""
    ctx = await ctx_for(uow, settings, "admin")
    async with uow.transaction() as s:
        [r] = await service.install_definitions(s, ctx, [(_defn(), "host")], TOOLS)
        ws = await ensure_default_workspace(s, settings)
        agent_admin = Ctx(
            actor=Actor(id=r.agent.user_id, workspace_id=ws.id, role="admin", is_agent=True),
            settings=settings,
        )
        from momentum.domain.projects.service import list_projects

        assert await list_projects(s, agent_admin) == []
