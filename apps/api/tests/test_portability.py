"""S7.5.1 export / import: a populated database exported to a bundle, imported into a freshly
migrated empty schema, and exported again gives byte-identical table files and checksums (ids,
subtasks, comments, files and all); a bundle refuses to load into a database that isn't empty,
at another migration, or when its contents were changed."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from momentum.core.db import UnitOfWork, create_engine, create_session_factory
from momentum.core.settings import Settings
from momentum.core.storage import LocalStorageBackend
from momentum.migrations_runner import upgrade_head
from momentum.portability import PortabilityError, export_to, import_from, zip_bundle
from tests.conftest import make_settings
from tests.helpers import Clients

OTHER_SCHEMA = "momentum_test_import"


async def _populate(as_user: Any) -> None:
    ravi = await as_user("ravi")
    pid = next(
        p["id"]
        for p in (await ravi.get("/api/v1/projects")).json()["data"]
        if p["name"] == "Website Revamp"
    )
    t = (await ravi.post(f"/api/v1/projects/{pid}/tasks", json={"title": "Exported"})).json()[
        "data"
    ]
    await ravi.post(f"/api/v1/tasks/{t['id']}/subtasks", json={"title": "Child"})
    doc = {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "hi"}]}],
    }
    await ravi.post(f"/api/v1/tasks/{t['id']}/comments", json={"body": doc})
    r = await ravi.post(
        f"/api/v1/tasks/{t['id']}/attachments",
        files={"file": ("note.txt", b"exported file\n", "text/plain")},
    )
    assert r.status_code == 201, r.text


@pytest.fixture
async def empty_schema() -> Any:
    other = make_settings(db_schema=OTHER_SCHEMA)
    eng = create_engine(other)
    async with eng.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{OTHER_SCHEMA}" CASCADE'))
    await asyncio.to_thread(upgrade_head, other)
    yield other, create_session_factory(eng)
    async with eng.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{OTHER_SCHEMA}" CASCADE'))
    await eng.dispose()


def _files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*.jsonl"))}


async def test_export_import_round_trip(
    as_user: Clients, uow: UnitOfWork, settings: Settings, tmp_path: Path, empty_schema: Any
) -> None:
    await _populate(as_user)
    source = LocalStorageBackend(settings.storage_local_dir)
    async with uow.transaction() as s:
        first = await export_to(s, tmp_path / "a", storage=source, with_files=True)
    assert first.tables["tasks"].rows > 10 and first.files == 1
    bundle = zip_bundle(tmp_path / "a", tmp_path / "a.zip")

    _, factory = empty_schema
    target = LocalStorageBackend(str(tmp_path / "files-b"))
    async with UnitOfWork(factory()).transaction() as s:
        loaded = await import_from(s, bundle, storage=target)
    assert loaded.tables == first.tables
    async with UnitOfWork(factory()).transaction() as s:
        again = await export_to(s, tmp_path / "b")
    assert again.tables == first.tables  # counts and checksums, every table
    assert _files(tmp_path / "a") == _files(tmp_path / "b")
    stored = next(p for p in (tmp_path / "a" / "files").rglob("*") if p.is_file())
    key = stored.relative_to(tmp_path / "a" / "files")
    assert await target.read(key.as_posix()) == b"exported file\n"

    # loading again into the now-full database is refused
    async with UnitOfWork(factory()).transaction() as s:
        with pytest.raises(PortabilityError, match="isn't empty"):
            await import_from(s, tmp_path / "a")
    # the outbox sequence continues after the imported ids
    async with UnitOfWork(factory()).transaction() as s:
        top = (await s.execute(text("select coalesce(max(id), 0) from events_outbox"))).scalar_one()
        nxt = (
            await s.execute(text("select nextval(pg_get_serial_sequence('events_outbox', 'id'))"))
        ).scalar_one()
        assert nxt > top


async def test_a_changed_or_mismatched_bundle_is_refused(
    as_user: Clients, uow: UnitOfWork, tmp_path: Path, empty_schema: Any
) -> None:
    await _populate(as_user)
    async with uow.transaction() as s:
        await export_to(s, tmp_path / "a")
    _, factory = empty_schema

    tasks = tmp_path / "a" / "tables" / "tasks.jsonl"
    lines = tasks.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[0])
    row["title"] = "Tampered"
    tasks.write_text("\n".join([json.dumps(row), *lines[1:]]) + "\n", encoding="utf-8")
    async with UnitOfWork(factory()).transaction() as s:
        with pytest.raises(PortabilityError, match="tasks"):
            await import_from(s, tmp_path / "a")

    manifest = tmp_path / "a" / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["revision"] = "0001"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    async with UnitOfWork(factory()).transaction() as s:
        with pytest.raises(PortabilityError, match="migration"):
            await import_from(s, tmp_path / "a")


async def test_an_admin_downloads_the_bundle(as_user: Clients) -> None:
    import io
    import zipfile

    admin, ravi = await as_user("admin"), await as_user("ravi")
    assert (await ravi.get("/api/v1/admin/export")).status_code == 403
    r = await admin.get("/api/v1/admin/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "momentum-export-" in r.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        manifest = json.loads(z.read("manifest.json"))
        assert manifest["tables"]["users"]["rows"] >= 2
        assert "tables/tasks.jsonl" in z.namelist()


async def test_the_cli_exports_a_zip(
    as_user: Clients, settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zipfile

    from typer.testing import CliRunner

    from momentum.cli import cli

    await as_user("ravi")
    monkeypatch.setenv("MOMENTUM_DATABASE_URL", settings.database_url)
    monkeypatch.setenv("MOMENTUM_DB_SCHEMA", settings.db_schema)
    target = tmp_path / "out.zip"
    result = await asyncio.to_thread(CliRunner().invoke, cli, ["export", "--out", str(target)])
    assert result.exit_code == 0, result.output
    assert "exported" in result.output and target.exists()
    with zipfile.ZipFile(target) as z:
        assert "manifest.json" in z.namelist()
