"""Bernie end to end through the real job engine (mock model answers built from each synthetic
invoice's ground truth): one invoice → one checked record that matches the truth; a zip → one
child job and record per invoice; a Factur-X invoice → no model call at all; the 300-line invoice
→ all 300 lines through the chunked path; a scan → OCR (when Tesseract is here)."""

from __future__ import annotations

import shutil
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.agents.extensions import attach_file
from momentum.core.db import UnitOfWork
from momentum.domain.agents.models import AgentRunStep
from momentum.domain.attachments import service as attachments_service
from momentum.domain.comments.models import Comment
from momentum.domain.entities.models import Entity
from momentum.domain.records.models import Record
from tests.ai_fixtures import World, world
from tests.jobs_env import JobsEnv

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packs" / "bernie" / "tests"))
from synth import build as B

_ = world
S = B.specs()
_WINDOWS = Path("C:/Program Files/Tesseract-OCR/tesseract.exe")
TESSERACT = shutil.which("tesseract") or (str(_WINDOWS) if _WINDOWS.is_file() else None)


@pytest.fixture
def make_env(
    uow: UnitOfWork,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    world: World,
) -> Callable[..., JobsEnv]:
    return lambda **kw: JobsEnv(uow, session_factory, tmp_path, world, **kw)


def fixtures(tmp: Path, entries: list[tuple[str, dict[str, Any]]]) -> None:
    """Mock answers for Bernie's model calls: each matches a phrase only that call's document
    holds."""
    (tmp / "agent__bernie.yaml").write_text(
        yaml.safe_dump(
            {
                "responses": [
                    {
                        "match": {"contains": phrase},
                        "tool_calls": [{"name": "answer", "arguments": answer}],
                    }
                    for phrase, answer in entries
                ]
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )


async def upload(
    env: JobsEnv, world: World, name: str, data: bytes, mime: str = "application/pdf"
) -> uuid.UUID:
    async with env.uow.transaction() as s:
        return await attach_file(s, world.ravi, env.settings, world.copy.id, name, data, mime)


async def records(env: JobsEnv) -> list[Record]:
    async with env.uow.transaction() as s:
        return list((await s.execute(select(Record).order_by(Record.created_at))).scalars())


async def llm_steps(env: JobsEnv) -> int:
    async with env.uow.transaction() as s:
        return len(
            list(
                (await s.execute(select(AgentRunStep).where(AgentRunStep.kind == "llm"))).scalars()
            )
        )


def same_as_truth(r: Record, key: str) -> None:
    t = B.truth(S[key])
    d = r.data
    assert d["invoice_number"] == t["invoice_number"]
    assert d["invoice_date"] == t["invoice_date"]
    assert d["currency"] == t["currency"]
    assert d["stated_total"] == t["stated_total"]
    assert [li["amount"] for li in d["lines"]] == [li["amount"] for li in t["lines"]]
    assert [li["description"] for li in d["lines"]] == [li["description"] for li in t["lines"]]


async def test_one_invoice_becomes_one_checked_record(
    make_env: Callable[..., JobsEnv], world: World, tmp_path: Path
) -> None:
    env = make_env()
    spec = S["northwind_simple"]
    fixtures(tmp_path, [("NW-2041", B.extraction_answer(spec))])
    await env.install("bernie")
    await upload(env, world, "northwind.pdf", B.pdf(spec))
    await env.start(task=world.copy)
    assert await env.drain() == ["succeeded"]
    [r] = await records(env)
    same_as_truth(r, "northwind_simple")
    assert r.status == "ready" and r.type == "invoice" and r.task_id == world.copy.id
    assert [c["id"] for c in r.checks if not c["passed"]] == []
    assert (
        r.provenance["stated_total"]["page"] == 1 and len(r.provenance["stated_total"]["bbox"]) == 4
    )
    assert r.data["extraction"]["method"] == "text"
    assert r.data["bank"]["last4"] == "5555" and "GB33" not in str(r.data)
    async with env.uow.transaction() as s:
        vendor = await s.get(Entity, uuid.UUID(r.data["vendor"]["entity_id"]))
        assert vendor is not None and vendor.name == "Northwind Data Ltd"
        assert vendor.attributes["tax_ids"] == ["GB123456789"]
        assert "5555" in str(vendor.attributes.get("bank"))


async def test_a_zip_becomes_one_child_and_one_record_per_invoice(
    make_env: Callable[..., JobsEnv], world: World, tmp_path: Path
) -> None:
    env = make_env()
    keys = ["northwind_simple", "adatum_qty1", "litware_wrapped"]
    fixtures(tmp_path, [(S[k].number, B.extraction_answer(S[k])) for k in keys])
    await env.install("bernie")
    z = B.zip_with_folders({f"{S[k].vendor['name']}/{k}.pdf": B.pdf(S[k]) for k in keys})
    await upload(env, world, "invoices.zip", z, "application/zip")
    await env.start(task=world.copy)
    statuses = await env.drain()
    from momentum.domain.agents.models import AgentRun

    async with env.uow.transaction() as s:
        errors = [r.error for r in (await s.execute(select(AgentRun))).scalars() if r.error]
    assert statuses.count("succeeded") == 4, errors  # the parent and three children
    got = {r.data["invoice_number"]: r for r in await records(env)}
    assert set(got) == {S[k].number for k in keys}
    for k in keys:
        same_as_truth(got[S[k].number], k)
        assert got[S[k].number].status == "ready", (k, got[S[k].number].checks)
        assert got[S[k].number].task_id != world.copy.id  # each on its own subtask
    async with env.uow.transaction() as s:
        comments = list(
            (await s.execute(select(Comment).where(Comment.task_id == world.copy.id))).scalars()
        )
        files = await attachments_service.list_for_task(s, world.ravi, world.copy.id)
    assert any("I read 3 invoices" in str(c.body) for c in comments)
    assert sum(1 for f in files if f.source == "agent") == 3  # the unpacked invoices, attached


async def test_factur_x_needs_no_model_call(
    make_env: Callable[..., JobsEnv], world: World, tmp_path: Path
) -> None:
    env = make_env()
    fixtures(tmp_path, [])
    await env.install("bernie")
    await upload(env, world, "contoso.pdf", B.facturx_pdf(S["contoso_facturx"]))
    await env.start(task=world.copy)
    assert await env.drain() == ["succeeded"]
    [r] = await records(env)
    same_as_truth(r, "contoso_facturx")
    assert r.data["extraction"]["method"] == "einvoice" and r.status == "ready"
    assert r.provenance["stated_total"]["method"] == "einvoice"
    assert await llm_steps(env) == 0


async def test_an_e_invoice_that_disagrees_with_its_page_is_flagged(
    make_env: Callable[..., JobsEnv], world: World, tmp_path: Path
) -> None:
    from decimal import Decimal

    env = make_env()
    fixtures(tmp_path, [])
    await env.install("bernie")
    await upload(
        env, world, "contoso.pdf", B.facturx_pdf(S["contoso_facturx"], xml_total=Decimal("9999.99"))
    )
    await env.start(task=world.copy)
    await env.drain()
    [r] = await records(env)
    mismatch = next(c for c in r.checks if c["id"] == "einvoice_mismatch")
    assert not mismatch["passed"] and "9999.99" in mismatch["detail"]


async def test_the_300_line_invoice_keeps_every_line(
    make_env: Callable[..., JobsEnv], world: World, tmp_path: Path
) -> None:
    env = make_env()
    spec = S["tailspin_long"]
    groups = [list(range(s, min(s + 4, 19))) for s in range(1, 19, 4)]
    entries = []
    for g in groups:
        first = (g[0] - 1) * spec.lines_per_page + 1
        entries.append((f"Research report #{first:03d}", B.extraction_answer(spec, pages=g)))
    fixtures(tmp_path, entries)
    await env.install("bernie")
    await upload(env, world, "tailspin.pdf", B.pdf(spec))
    await env.start(task=world.copy)
    assert await env.drain() == ["succeeded"]
    [r] = await records(env)
    assert len(r.data["lines"]) == 300
    assert r.data["extraction"]["method"] == "chunked" and r.data["extraction"]["chunks"] == 5
    same_as_truth(r, "tailspin_long")
    assert r.status == "ready", [c for c in r.checks if not c["passed"]]


@pytest.mark.skipif(TESSERACT is None, reason="Tesseract isn't installed here")
async def test_a_scan_is_read_with_ocr_and_its_hostile_footer_is_flagged(
    make_env: Callable[..., JobsEnv], world: World, tmp_path: Path
) -> None:
    env = make_env(tesseract_cmd=TESSERACT)
    spec = S["woodgrove_scan"]
    fixtures(tmp_path, [("INV-0041", B.extraction_answer(spec))])
    await env.install("bernie")
    await upload(env, world, "scan.pdf", B.pdf(spec))
    await env.start(task=world.copy)
    assert await env.drain() == ["succeeded"]
    [r] = await records(env)
    same_as_truth(r, "woodgrove_scan")
    assert (
        r.data["extraction"]["ocr_pages"] == [1] and r.provenance["stated_total"]["method"] == "ocr"
    )
    injection = next(c for c in r.checks if c["id"] == "instruction_text_found")
    assert not injection["passed"]


async def test_no_file_says_so(
    make_env: Callable[..., JobsEnv], world: World, tmp_path: Path
) -> None:
    env = make_env()
    fixtures(tmp_path, [])
    await env.install("bernie")
    await env.start(task=world.copy)
    assert await env.drain() == ["succeeded"]
    async with env.uow.transaction() as s:
        comments = list(
            (await s.execute(select(Comment).where(Comment.task_id == world.copy.id))).scalars()
        )
    assert any("couldn't find an invoice file" in str(c.body) for c in comments)
    assert await records(env) == []
