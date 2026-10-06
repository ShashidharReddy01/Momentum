"""Phase 7.5 S75-02 (spec §4.3): a file is parsed the first time it's needed, then reused until
the parser version changes; its rows live in storage; deleting the file drops its parse."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from momentum.core.db import UnitOfWork
from momentum.core.settings import Settings
from momentum.core.storage import build_storage
from momentum.domain.attachments import service as attachments
from momentum.files import cache
from momentum.files import model as file_model
from momentum.files.models import FileParse
from momentum.files.tables import TableQuery, run_query
from tests.fixtures.files import build
from tests.helpers import Clients, ctx_for


async def _upload(c, name: str, data: bytes) -> dict:  # type: ignore[no-untyped-def]
    pid = next(
        p["id"]
        for p in (await c.get("/api/v1/projects")).json()["data"]
        if p["name"] == "Website Revamp"
    )
    r = await c.post(
        f"/api/v1/projects/{pid}/files", files={"file": (name, data, "application/octet-stream")}
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def test_parse_once_then_reuse(
    as_user: Clients, uow: UnitOfWork, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    ravi = await as_user("ravi")
    att = await _upload(ravi, "invoices.xlsx", build.xlsx_invoices(300))
    ctx = await ctx_for(uow, settings, "ravi")
    storage = build_storage(settings)

    async with uow.transaction() as s:
        a = await attachments.get_visible_attachment(s, ctx, att["id"])
        src = cache.FileSource(
            workspace_id=a.workspace_id,
            storage_key=a.storage_key,
            filename=a.filename,
            mime=a.mime,
            size=a.size_bytes,
            attachment_id=a.id,
        )
        first = await cache.get_or_parse(s, src, storage=storage, settings=settings)
    assert first.status == "ok" and first.rows_key
    assert first.model.file.attachment_id == a.id

    calls = 0

    def boom(*_a: object, **_k: object) -> None:
        nonlocal calls
        calls += 1
        raise AssertionError("parsed again")

    monkeypatch.setattr(cache, "parse_bytes", boom)
    async with uow.transaction() as s:
        again = await cache.get_or_parse(s, src, storage=storage, settings=settings)
        assert (await s.execute(select(func.count()).select_from(FileParse))).scalar_one() == 1
    assert calls == 0
    sheet = again.model.sheets[0]
    rows = await again.rows(sheet.data_ref)  # read back from storage, gzipped JSON
    assert len(rows) == 301
    res = run_query(sheet, rows, TableQuery(aggregates=[{"fn": "count"}]))  # type: ignore[list-item]
    assert res.rows == [[300]]

    # a new parser version parses again
    monkeypatch.undo()
    monkeypatch.setattr(cache, "PARSER_VERSION", file_model.PARSER_VERSION + 1)
    async with uow.transaction() as s:
        assert await cache.cached(s, src, storage) is None

    # deleting the file drops its parse; undo restores the file, which is parsed again on demand
    monkeypatch.undo()
    r = await ravi.delete(f"/api/v1/attachments/{att['id']}")
    assert r.status_code == 200
    async with uow.transaction() as s:
        assert (await s.execute(select(func.count()).select_from(FileParse))).scalar_one() == 0


async def test_failed_and_unsupported_parses_are_cached_too(
    as_user: Clients, uow: UnitOfWork, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    att = await _upload(ravi, "old.doc", b"\xd0\xcf\x11\xe0 legacy")
    ctx = await ctx_for(uow, settings, "ravi")
    async with uow.transaction() as s:
        a = await attachments.get_visible_attachment(s, ctx, att["id"])
        src = cache.FileSource(
            workspace_id=a.workspace_id,
            storage_key=a.storage_key,
            filename=a.filename,
            mime=a.mime,
            size=a.size_bytes,
            attachment_id=a.id,
        )
        r = await cache.get_or_parse(s, src, storage=build_storage(settings), settings=settings)
    assert r.status == "unsupported" and r.rows_key is None
    assert any(".docx" in w for w in r.model.file.warnings)
