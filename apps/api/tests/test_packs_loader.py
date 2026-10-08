"""Phase 7.6 S76-01 (spec §3): packs. The loader (entry points, the MOMENTUM_PACKS filter, the SDK
range, deployment ceilings, test packs), manifest validation, install / upgrade / drift through
the ordinary agents install, the project setup preview → apply → undo, and the pack-agent guards.
The test pack is ``tests/packs/echo`` (repo root), loaded only with MOMENTUM_TEST_PACKS=true."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from momentum.agents.packs.check import check_packs
from momentum.agents.packs.loader import TEST_PACKS_DIR, load_packs
from momentum.agents.packs.manifest import ManifestError, PackManifest, in_range, load_manifest
from momentum.agents.packs.pack import Pack, PackError
from momentum.agents.packs.registry import PackRegistry
from momentum.agents.packs.setup import Section, TaskField
from momentum.app import create_app
from tests.conftest import make_settings
from tests.helpers import Clients

B = "/api/v1"
ECHO = TEST_PACKS_DIR / "echo"


def _manifest(**changes: Any) -> dict[str, Any]:
    raw: dict[str, Any] = yaml.safe_load((ECHO / "manifest.yaml").read_text(encoding="utf-8"))
    raw.update(changes)
    return raw


def _echo_types() -> Any:
    """Echo's record types (its manifest declares records effects for them, S76-04)."""
    from momentum.agents.packs.loader import _load_test_pack

    pack = _load_test_pack(ECHO)
    return getattr(pack, "record_types", ())


def _pack_in(tmp_path: Path, **changes: Any) -> Pack:
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(_manifest(**changes)), encoding="utf-8")
    return Pack(manifest_path=path, record_types=_echo_types())


# ---------- loader ----------


def test_test_packs_load_only_when_asked_and_bernie_is_refused_until_built() -> None:
    off = load_packs(make_settings())
    assert "echo" not in off.packs
    on = load_packs(make_settings(test_packs=True))
    assert "echo" in on.packs and "echo" in on.test_keys
    # the S76-00 skeleton isn't a Pack yet: refused with a reason, never half-loaded
    assert any("bernie" in e.source and "not a momentum.sdk.Pack" in e.reason for e in on.errors)
    assert "bernie" not in on.packs


def test_filter_and_kill_switch() -> None:
    only_other = load_packs(make_settings(test_packs=True, packs="something_else"))
    assert only_other.packs == {}
    assert load_packs(make_settings(test_packs=True, packs="echo")).packs.keys() == {"echo"}
    assert load_packs(make_settings(test_packs=True, packs_enabled=False)).packs == {}


def test_sdk_range_and_ceilings_refuse_a_pack(tmp_path: Path) -> None:
    assert in_range("1.0", ">=1.0,<2") and not in_range("1.0", ">=2")
    assert in_range("1.4", ">1.3") and not in_range("2.0", "<2")
    from momentum.agents.packs.loader import check_pack

    with pytest.raises(PackError, match=r"needs momentum\.sdk >=2"):
        check_pack(_pack_in(tmp_path, sdk=">=2"), make_settings())
    limits = {**_manifest()["limits"], "concurrency": 9}
    with pytest.raises(PackError, match=r"concurrency 9 > 4"):
        check_pack(_pack_in(tmp_path, limits=limits), make_settings())
    # a pack that fits passes
    check_pack(_pack_in(tmp_path), make_settings())


def test_manifest_validation_is_strict(tmp_path: Path) -> None:
    good = _manifest()
    PackManifest.model_validate(good)
    for bad, message in [
        ({**good, "colour": "red"}, "Extra inputs"),
        ({**good, "effects": ["tasks.delete"]}, "Unknown effect"),
        ({**good, "effects": ["records.create"]}, "needs its types"),
        ({**good, "effects": [{"comments.create": ["x"]}]}, "takes no types"),
        ({**good, "network": ["api.example.com"]}, "at most 0"),
        ({**good, "autonomy": "auto"}, "Input should be"),
        ({**good, "sdk": "one point oh"}, "operator and a version"),
        ({**good, "version": "1.0"}, "String should match"),
        ({**good, "capabilities": []}, "at least 1"),
    ]:
        with pytest.raises(ValueError, match=message):
            PackManifest.model_validate(bad)
    (tmp_path / "manifest.yaml").write_text("key: [unclosed", encoding="utf-8")
    with pytest.raises(ManifestError, match=r"manifest\.yaml"):
        load_manifest(tmp_path / "manifest.yaml")
    declared = PackManifest.model_validate(
        {**good, "effects": ["comments.create", {"records.create": ["invoice"]}]}
    )
    assert declared.declares("comments.create")
    assert declared.declares("records.create", "invoice")
    assert not declared.declares("records.create", "receipt")
    assert not declared.declares("tasks.rename")


def test_pack_validation_rules(tmp_path: Path) -> None:
    pack = Pack(
        manifest_path=_pack_in(tmp_path).manifest_path,
        capabilities={"nope": _noop},
        record_types=_echo_types(),
    )
    with pytest.raises(PackError, match=r"undeclared capabilities: nope"):
        pack.validate()
    twice = Pack(
        manifest_path=pack.manifest_path,
        setup=(Section(name="Inbox"), Section(name="inbox")),
        record_types=_echo_types(),
    )
    with pytest.raises(PackError, match=r"same item twice"):
        twice.validate()


async def _noop(job: Any) -> None:
    return None


def test_packs_check_reports_problems_and_the_contract_rule(tmp_path: Path) -> None:
    problems = check_packs(make_settings(test_packs=True))
    # Bernie isn't built yet (S76-09); its import-linter contract already exists
    assert any("bernie" in p and "not a momentum.sdk.Pack" in p for p in problems)
    assert not any("no import-linter contract" in p for p in problems)
    # a pyproject without the contract is reported
    empty = tmp_path / "pyproject.toml"
    empty.write_text("[tool.importlinter]\nroot_packages = ['momentum']\n", encoding="utf-8")
    problems = check_packs(make_settings(), pyproject=empty)
    assert any("no import-linter contract keeps momentum_pack_bernie" in p for p in problems)


def test_registry_definitions_only_seed_display_fields() -> None:
    registry = PackRegistry.load(make_settings(test_packs=True))
    ((definition, source),) = [d for d in registry.definitions() if d[0].key == "echo"]
    assert source == "pack"
    assert (definition.kind, definition.pack_key, definition.pack_version) == (
        "pack",
        "echo",
        "1.0.0",
    )
    assert definition.name == "Echo" and definition.model_alias == "fast"
    # pack triggers and tools are read from code at run time, never copied onto the row
    assert definition.triggers == [] and definition.tools == []
    assert registry.capability("echo", "echo").title == "Echo the input"


# ---------- install, upgrade, drift (spec §3.3) ----------


async def test_install_upgrade_and_drift(seeded: None, tmp_path: Path) -> None:
    app = create_app(make_settings(test_packs=True))
    async with app.router.lifespan_context(app):
        clients = Clients(app)
        admin = await clients("admin")
        r = await admin.post(f"{B}/agents/install", json={})
        assert r.status_code == 200, r.text
        outcomes = {row["key"]: row["outcome"] for row in r.json()["results"]}
        assert outcomes["echo"] == "installed"
        # adding packs doesn't make any starter agent look edited (the hash ignores unset packs)
        assert all(o == "installed" for o in outcomes.values())
        again = await admin.post(f"{B}/agents/install", json={})
        assert {row["outcome"] for row in again.json()["results"]} == {"unchanged"}

        agents = (await admin.get(f"{B}/agents")).json()["data"]
        echo = next(a for a in agents if a["key"] == "echo")
        assert echo["kind"] == "pack" and echo["source"] == "pack"
        assert (echo["pack_key"], echo["pack_version"]) == ("echo", "1.0.0")
        assert echo["enabled"] is False  # installed disabled, like every agent

        # a new pack version installs over the old one when nobody edited the agent
        copy = tmp_path / "echo"
        shutil.copytree(ECHO, copy)
        raw = yaml.safe_load((copy / "manifest.yaml").read_text(encoding="utf-8"))
        raw["version"] = "1.1.0"
        (copy / "manifest.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
        runtime = app.state.momentum
        runtime.packs.packs["echo"] = Pack(
            manifest_path=copy / "manifest.yaml", record_types=_echo_types()
        )
        up = await admin.post(f"{B}/agents/install", json={"keys": ["echo"]})
        assert up.json()["results"][0]["outcome"] == "updated"
        after = (await admin.get(f"{B}/agents/{echo['id']}")).json()
        assert after["pack_version"] == "1.1.0"

        # an admin's edit is kept: the next version reports drift instead of overwriting it
        r = await admin.patch(f"{B}/agents/{echo['id']}", json={"name": "Echo (ours)"})
        assert r.status_code == 200, r.text
        raw["version"] = "1.2.0"
        (copy / "manifest.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
        runtime.packs.packs["echo"] = Pack(
            manifest_path=copy / "manifest.yaml", record_types=_echo_types()
        )
        drift = await admin.post(f"{B}/agents/install", json={"keys": ["echo"]})
        assert drift.json()["results"][0]["outcome"] == "drifted"
        forced = await admin.post(f"{B}/agents/install", json={"keys": ["echo"], "force": True})
        assert forced.json()["results"][0]["outcome"] == "forced"
        final = (await admin.get(f"{B}/agents/{echo['id']}")).json()
        assert (final["name"], final["pack_version"]) == ("Echo", "1.2.0")
        await clients.close()


async def test_pack_agents_cant_be_made_by_hand_or_run_the_old_way(seeded: None) -> None:
    app = create_app(make_settings(test_packs=True))
    async with app.router.lifespan_context(app):
        clients = Clients(app)
        admin = await clients("admin")
        r = await admin.post(
            f"{B}/agents",
            json={"name": "Fake", "kind": "pack", "pack_key": "echo", "pack_version": "1.0.0"},
        )
        assert r.status_code == 422 and "installed from their pack" in r.text
        await admin.post(f"{B}/agents/install", json={"keys": ["echo"]})
        echo = next(
            a for a in (await admin.get(f"{B}/agents")).json()["data"] if a["key"] == "echo"
        )
        pid = next(p["id"] for p in (await admin.get(f"{B}/projects")).json()["data"])
        test_run = await admin.post(f"{B}/agents/{echo['id']}/test-run", json={"project_id": pid})
        assert test_run.status_code == 422 and "model-driven agents" in test_run.text
        await clients.close()


# ---------- project setup (spec §3.4) ----------


async def _echo_in_project(admin: httpx.AsyncClient) -> tuple[str, str]:
    await admin.post(f"{B}/agents/install", json={})  # the starters too
    echo = next(a for a in (await admin.get(f"{B}/agents")).json()["data"] if a["key"] == "echo")
    projects = (await admin.get(f"{B}/projects")).json()["data"]
    pid = next(p["id"] for p in projects if p["name"] == "Website Revamp")
    return echo["id"], pid


async def test_setup_preview_apply_and_undo(seeded: None) -> None:
    app = create_app(make_settings(test_packs=True))
    async with app.router.lifespan_context(app):
        clients = Clients(app)
        admin = await clients("admin")
        agent_id, pid = await _echo_in_project(admin)

        # the agent has to be in the project first
        r = await admin.get(f"{B}/agents/{agent_id}/setup", params={"project_id": pid})
        assert r.status_code == 409 and r.json()["code"] == "not_member"
        r = await admin.post(
            f"{B}/agents/{agent_id}/projects", json={"project_id": pid, "role": "editor"}
        )
        assert r.status_code in (200, 201), r.text

        preview = await admin.get(f"{B}/agents/{agent_id}/setup", params={"project_id": pid})
        assert preview.status_code == 200, preview.text
        assert [(c["kind"], c["name"], c["action"]) for c in preview.json()["changes"]] == [
            ("task_field", "Echo status", "create"),
            ("section", "Echo inbox", "create"),
        ]
        fields_before = await _field_names(admin, pid)
        sections_before = await _section_names(admin, pid)

        applied = await admin.post(f"{B}/agents/{agent_id}/setup", json={"project_id": pid})
        assert applied.status_code == 200, applied.text
        batch_id = applied.json()["batch_id"]
        assert batch_id is not None
        assert "Echo status" in await _field_names(admin, pid)
        assert "Echo inbox" in await _section_names(admin, pid)

        # applying again changes nothing: what exists is reused
        again = await admin.post(f"{B}/agents/{agent_id}/setup", json={"project_id": pid})
        assert again.json()["batch_id"] is None
        assert {c["action"] for c in again.json()["changes"]} == {"exists"}  # both items

        # one undo reverts the whole setup
        undo = await admin.post(f"{B}/undo", json={"batch_id": batch_id})
        assert undo.status_code == 200, undo.text
        assert await _field_names(admin, pid) == fields_before
        assert await _section_names(admin, pid) == sections_before
        await clients.close()


async def test_setup_reuses_a_library_field_and_skips_a_covered_section(seeded: None) -> None:
    app = create_app(make_settings(test_packs=True))
    async with app.router.lifespan_context(app):
        clients = Clients(app)
        admin = await clients("admin")
        agent_id, pid = await _echo_in_project(admin)
        await admin.post(
            f"{B}/agents/{agent_id}/projects", json={"project_id": pid, "role": "editor"}
        )
        projects = (await admin.get(f"{B}/projects")).json()["data"]
        other = next(p["id"] for p in projects if p["id"] != pid)
        # a library field with the same name and type lives on another project
        r = await admin.post(
            f"{B}/projects/{other}/fields",
            json={"name": "Echo status", "type": "single_select", "options": [{"label": "Done"}]},
        )
        assert r.status_code == 201, r.text
        r = await admin.post(f"{B}/projects/{pid}/sections", json={"name": "Inbox"})
        assert r.status_code == 201, r.text
        preview = (
            await admin.get(f"{B}/agents/{agent_id}/setup", params={"project_id": pid})
        ).json()["changes"]
        assert [(c["name"], c["action"]) for c in preview] == [
            ("Echo status", "attach"),
            ("Echo inbox", "skip"),
        ]
        applied = await admin.post(f"{B}/agents/{agent_id}/setup", json={"project_id": pid})
        batch_id = applied.json()["batch_id"]
        assert "Echo status" in await _field_names(admin, pid)
        await admin.post(f"{B}/undo", json={"batch_id": batch_id})
        # undo takes it off this project but keeps the library field the other project uses
        assert "Echo status" not in await _field_names(admin, pid)
        assert "Echo status" in await _field_names(admin, other)
        await clients.close()


async def test_setup_is_for_pack_agents_and_respects_project_access(seeded: None) -> None:
    app = create_app(make_settings(test_packs=True))
    async with app.router.lifespan_context(app):
        clients = Clients(app)
        admin = await clients("admin")
        agent_id, pid = await _echo_in_project(admin)
        await admin.post(
            f"{B}/agents/{agent_id}/projects", json={"project_id": pid, "role": "editor"}
        )
        starter = next(
            a for a in (await admin.get(f"{B}/agents")).json()["data"] if a["kind"] == "llm"
        )
        r = await admin.get(f"{B}/agents/{starter['id']}/setup", params={"project_id": pid})
        assert r.status_code == 422 and "isn't a pack agent" in r.text
        # a project editor can preview, but applying is the project admin's call (spec §3.4)
        editor = await clients("mei")
        r = await editor.get(f"{B}/agents/{agent_id}/setup", params={"project_id": pid})
        assert r.status_code == 200, r.text
        r = await editor.post(f"{B}/agents/{agent_id}/setup", json={"project_id": pid})
        assert r.status_code == 403, r.text
        await clients.close()


async def _field_names(c: httpx.AsyncClient, pid: str) -> list[str]:
    r = await c.get(f"{B}/projects/{pid}/fields")
    assert r.status_code == 200, r.text
    return sorted(f["field"]["name"] for f in r.json()["data"])


async def _section_names(c: httpx.AsyncClient, pid: str) -> list[str]:
    r = await c.get(f"{B}/projects/{pid}/sections")
    assert r.status_code == 200, r.text
    return sorted(s["name"] for s in r.json()["data"])


def test_setup_items_are_typed() -> None:
    with pytest.raises(ValueError):
        TaskField(name="", type="text")
    with pytest.raises(ValueError):
        TaskField(name="X", type="colour")  # type: ignore[arg-type]
