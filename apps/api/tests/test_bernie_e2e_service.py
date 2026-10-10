"""Bernie's checking, asking and deciding end to end (spec §9.3.11-19), through the real job
engine with mock model answers built from the synthetic invoices:

- a clean invoice → `ready`, an approval subtask for the approver, and approving it approves the
  record (the agent never approves on its own: auto-approval is off by default);
- a VAT row read as a line → the critic's correction makes it add up;
- a total that still doesn't add up → one form ask; the person's answer fixes it;
- a changed bank account → held for the stewards, never replacing the one on file until a
  person confirms it with the vendor;
- INV-0041 then INV41 from the same vendor → the second is held as a duplicate;
- a hostile footer changes nothing and is flagged `instruction_text_found`."""

from __future__ import annotations

import copy
import dataclasses
import sys
import uuid
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.agents.extensions import attach_file
from momentum.core.db import UnitOfWork
from momentum.domain.asks import service as asks
from momentum.domain.asks.models import Ask
from momentum.domain.attachments import service as attachments_service
from momentum.domain.entities.models import Entity
from momentum.domain.records.models import Record
from momentum.domain.tasks.models import Task
from momentum.domain.tasks.service import decide_approval
from tests.ai_fixtures import World, world
from tests.jobs_env import JobsEnv

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packs" / "bernie" / "tests"))
from momentum_pack_bernie import ask_gap, outputs
from synth import build as B

_ = world
S = B.specs()
NW = S["northwind_simple"]


@pytest.fixture
def make_env(
    uow: UnitOfWork,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    world: World,
) -> Callable[..., JobsEnv]:
    return lambda **kw: JobsEnv(uow, session_factory, tmp_path, world, **kw)


def fixtures(tmp: Path, entries: list[dict[str, Any]]) -> None:
    (tmp / "agent__bernie.yaml").write_text(
        yaml.safe_dump({"responses": entries}, allow_unicode=True), encoding="utf-8"
    )


def answer(phrase: str, value: dict[str, Any], turn: int | None = None) -> dict[str, Any]:
    match: dict[str, Any] = {"contains": phrase}
    if turn is not None:
        match["turn"] = turn
    return {"match": match, "tool_calls": [{"name": "answer", "arguments": value}]}


async def upload_and_run(
    env: JobsEnv, world: World, task_id: uuid.UUID, name: str, data: bytes
) -> list[str]:
    async with env.uow.transaction() as s:
        await attach_file(s, world.ravi, env.settings, task_id, name, data, "application/pdf")
        task = await s.get(Task, task_id)
    assert task is not None
    await env.start(task=task)
    return await env.drain()


async def records(env: JobsEnv) -> list[Record]:
    async with env.uow.transaction() as s:
        return list((await s.execute(select(Record).order_by(Record.created_at))).scalars())


async def open_asks(env: JobsEnv) -> list[Ask]:
    async with env.uow.transaction() as s:
        return list(
            (
                await s.execute(select(Ask).where(Ask.status == "open").order_by(Ask.created_at))
            ).scalars()
        )


async def approvals(env: JobsEnv) -> list[Task]:
    async with env.uow.transaction() as s:
        return list((await s.execute(select(Task).where(Task.type == "approval"))).scalars())


async def test_a_clean_invoice_waits_for_a_person_and_their_approval_approves_it(
    make_env: Callable[..., JobsEnv], world: World, tmp_path: Path
) -> None:
    env = make_env()
    fixtures(tmp_path, [answer(NW.number, B.extraction_answer(NW))])
    await env.install("bernie")
    assert await upload_and_run(env, world, world.copy.id, "nw.pdf", B.pdf(NW)) == [
        "succeeded",
        "waiting",  # the decision job, waiting for the approval
    ]
    [r] = await records(env)
    assert r.status == "ready"
    assert r.decision is not None and r.decision["decision"] == "require_human"
    assert r.decision["rule_id"] == "new_vendor"  # the first invoice from Northwind
    assert {e["rule_id"] for e in r.decision["evaluated"]} >= {"block_bank_change", "auto_ok"}
    assert r.confidence is not None and Decimal(r.confidence) > Decimal("0.85")
    assert r.provenance["stated_total"]["signals"] == ["verbatim", "consistent"]
    [approval] = await approvals(env)
    total = outputs.money(B.truth(NW)["stated_total"], "GBP")
    assert approval.title == f"Approve Northwind Data Ltd NW-2041 ({total})"
    assert approval.parent_id == world.copy.id and approval.assignee_id == world.ravi.actor.id
    async with env.uow.transaction() as s:
        files = await attachments_service.list_for_task(s, world.ravi, world.copy.id)
    names = sorted(f.filename for f in files if f.source == "agent")
    assert names[0].startswith("invoices-") and names[0].endswith(".csv")
    assert names[1].endswith(".xlsx")

    async with env.uow.transaction() as s:
        await decide_approval(s, world.ravi, approval.id, "approved")
    assert await env.drain() == ["succeeded"], await errors(env)
    [r] = await records(env)
    assert r.status == "approved"


async def test_a_vat_row_in_the_lines_is_corrected_by_the_critic(
    make_env: Callable[..., JobsEnv], world: World, tmp_path: Path
) -> None:
    env = make_env()
    right = B.extraction_answer(NW)
    fixtures(
        tmp_path,
        [
            answer(
                "attempt_number: 1 of 3",
                {
                    "root_cause": "tax_row_in_line_items",
                    "diagnosis": "The VAT row was read as a line item.",
                    "corrected_fields": {"line_items": right["line_items"]},
                    "no_correction_possible": False,
                    "confidence": 0.9,
                },
            ),
            answer(NW.number, B.wrong(NW)),
        ],
    )
    await env.install("bernie")
    await upload_and_run(env, world, world.copy.id, "nw.pdf", B.pdf(NW))
    [r] = await records(env)
    assert r.status == "ready", r.checks
    assert [li["amount"] for li in r.data["lines"]] == [li["amount"] for li in right["line_items"]]
    assert r.data["extraction"]["attempts"] == 1
    assert any("tax row in line items" in n for n in r.data["notes"])
    assert await open_asks(env) == []


async def test_a_gap_nobody_could_fix_is_asked_once_and_the_answer_fixes_it(
    make_env: Callable[..., JobsEnv], world: World, tmp_path: Path
) -> None:
    env = make_env()
    spec = dataclasses.replace(NW, number="NW-2050", stated_total_override=Decimal("1600.00"))
    misread = copy.deepcopy(B.extraction_answer(spec))
    misread["stated_total"] = "1600.00"
    fixtures(
        tmp_path,
        [
            answer(
                "attempt_number: 1 of 3",
                {"no_correction_possible": True, "diagnosis": "The page says 1600.00."},
            ),
            {
                "match": {"contains": "Its extraction fails these checks"},
                "text": "The document doesn't let me fix it.",
            },
            answer(spec.number, misread),
        ],
    )
    await env.install("bernie")
    statuses = await upload_and_run(env, world, world.copy.id, "nw.pdf", B.pdf(spec))
    assert statuses == ["waiting"]
    [ask] = await open_asks(env)
    assert ask.kind == "form" and ask.title == "Total doesn't add up on Northwind Data Ltd NW-2050"
    assert "What I tried" in ask.body and ask.evidence
    assert ask.to_user_ids == [world.ravi.actor.id]
    truth = B.truth(NW)["stated_total"]
    async with env.uow.transaction() as s:
        await asks.answer_ask(s, world.ravi, ask.id, {"action": ask_gap.TOTAL, "total": truth})
    assert (await env.drain())[0] == "succeeded"
    [r] = await records(env)
    assert r.data["stated_total"] == truth and r.status == "ready", r.checks
    assert r.provenance["stated_total"]["method"] == "human"
    assert r.data["extraction"]["investigator_steps"] == 1


async def test_a_changed_bank_account_is_held_for_the_stewards(
    make_env: Callable[..., JobsEnv], world: World, tmp_path: Path
) -> None:
    env = make_env()
    second = dataclasses.replace(NW, number="NW-2042", iban="GB33BUKB20201599999999")
    fixtures(
        tmp_path,
        [
            answer(NW.number, B.extraction_answer(NW)),
            answer(second.number, B.extraction_answer(second)),
        ],
    )
    await env.install("bernie")
    await upload_and_run(env, world, world.copy.id, "nw1.pdf", B.pdf(NW))
    await upload_and_run(env, world, world.faq.id, "nw2.pdf", B.pdf(second))
    first, held = await records(env)
    assert held.status == "needs_review"
    assert held.decision is not None
    assert (held.decision["decision"], held.decision["route"]) == ("hold", "stewards")
    assert "5555" in held.decision["reason"] and "9999" in held.decision["reason"]
    async with env.uow.transaction() as s:
        vendor = await s.get(Entity, uuid.UUID(held.data["vendor"]["entity_id"]))
        assert vendor is not None
        assert vendor.attributes["bank"]["last4"] == "5555"  # not replaced by the invoice
        assert vendor.attributes["bank"]["pending"]["last4"] == "9999"
    [hold] = [a for a in await open_asks(env) if a.task_id == world.faq.id]
    assert hold.title == "Bank details changed for Northwind Data Ltd"
    assert len(await approvals(env)) == 1  # only the first invoice's
    async with env.uow.transaction() as s:
        await asks.answer_ask(s, world.ravi, hold.id, outputs.BANK_CONFIRMED)
    await env.drain()
    async with env.uow.transaction() as s:
        vendor = await s.get(
            Entity, uuid.UUID(held.data["vendor"]["entity_id"]), populate_existing=True
        )
        assert vendor is not None and vendor.attributes["bank"]["last4"] == "9999"
    second_approval = [t for t in await approvals(env) if t.parent_id == world.faq.id]
    assert len(second_approval) == 1
    async with env.uow.transaction() as s:
        await decide_approval(s, world.ravi, second_approval[0].id, "rejected")
    await env.drain()
    _first, held = await records(env)
    assert held.status == "rejected"
    assert first.status == "ready"


async def test_inv_0041_then_inv41_is_held_as_a_duplicate_and_a_hostile_footer_is_flagged(
    make_env: Callable[..., JobsEnv], world: World, tmp_path: Path
) -> None:
    env = make_env()
    hostile = dataclasses.replace(S["woodgrove_scan"], scanned=False)
    dup = S["woodgrove_dup"]
    fixtures(
        tmp_path,
        [
            answer(hostile.number, B.extraction_answer(hostile)),
            answer(dup.number, B.extraction_answer(dup)),
        ],
    )
    await env.install("bernie")
    await upload_and_run(env, world, world.copy.id, "wg.pdf", B.pdf(hostile))
    [first] = await records(env)
    flagged = next(c for c in first.checks if c["id"] == "instruction_text_found")
    assert not flagged["passed"] and flagged["severity"] == "warn"
    assert first.status == "ready" and first.decision is not None
    assert first.decision["decision"] == "require_human"  # nothing the footer said happened
    assert first.data["stated_total"] == B.truth(hostile)["stated_total"]

    await upload_and_run(env, world, world.faq.id, "wg-again.pdf", B.pdf(dup))
    _first, second = await records(env)
    duplicate = next(c for c in second.checks if c["id"] == "duplicate")
    assert duplicate["duplicate_of"] == str(first.id)
    assert second.decision is not None and second.decision["decision"] == "hold"
    assert second.decision["route"] == "requester" and second.status == "needs_review"
    [ask] = [a for a in await open_asks(env) if a.task_id == world.faq.id]
    async with env.uow.transaction() as s:
        await asks.answer_ask(s, world.ravi, ask.id, outputs.REJECT)
    await env.drain()
    _first, second = await records(env)
    assert second.status == "rejected"


async def errors(env: JobsEnv) -> list[str]:
    from momentum.domain.agents.models import AgentRun

    async with env.uow.transaction() as s:
        return [r.error for r in (await s.execute(select(AgentRun))).scalars() if r.error]
