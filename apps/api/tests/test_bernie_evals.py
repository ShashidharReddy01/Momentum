"""The `bernie_extract` eval cases (packs/bernie/momentum_pack_bernie/evals/bernie_extract.yaml),
mock mode: every synthetic invoice through the whole job, scored against its ground truth with
`momentum_pack_bernie.quality`. The bar is the product owner's: every field and every line right
(field accuracy and line recall 1.0 on the mock set; the live run measures the model itself)."""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from momentum_pack_bernie import ask_gap, quality
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.agents.extensions import attach_file
from momentum.core.db import UnitOfWork
from momentum.domain.agents.models import AgentRunStep
from momentum.domain.asks import service as asks
from momentum.domain.asks.models import Ask
from momentum.domain.records.models import Record
from tests.ai_fixtures import World, world
from tests.jobs_env import JobsEnv

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packs" / "bernie" / "tests"))
from synth import build as B

_ = world
S = B.specs()
EVALS = Path(quality.__file__).parent / "evals" / "bernie_extract.yaml"
CASES = [c for c in yaml.safe_load(EVALS.read_text(encoding="utf-8"))["cases"] if c.get("mock")]
_WINDOWS = Path("C:/Program Files/Tesseract-OCR/tesseract.exe")
TESSERACT = shutil.which("tesseract") or (str(_WINDOWS) if _WINDOWS.is_file() else None)
SCORES: list[quality.Score] = []


@pytest.fixture
def make_env(
    uow: UnitOfWork,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    world: World,
) -> Callable[..., JobsEnv]:
    return lambda **kw: JobsEnv(uow, session_factory, tmp_path, world, **kw)


def write_fixtures(tmp: Path, entries: list[tuple[str, dict[str, Any]]]) -> None:
    (tmp / "agent__bernie.yaml").write_text(
        yaml.safe_dump(
            {
                "responses": [
                    {"match": {"contains": p}, "tool_calls": [{"name": "answer", "arguments": a}]}
                    for p, a in entries
                ]
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
async def test_extract_case(
    case: dict[str, Any], make_env: Callable[..., JobsEnv], world: World, tmp_path: Path
) -> None:
    if case.get("needs") == "tesseract" and TESSERACT is None:
        pytest.skip("Tesseract isn't installed here")
    spec = S[case["synth"]]
    env = make_env(tesseract_cmd=TESSERACT) if TESSERACT else make_env()
    write_fixtures(tmp_path, B.mock_entries(spec, answer=case.get("answer", "truth")))
    await env.install("bernie")
    name, data, mime = B.file_for(spec, case.get("file"))
    async with env.uow.transaction() as s:
        await attach_file(s, world.ravi, env.settings, world.copy.id, name, data, mime)
    await env.start(task=world.copy)
    statuses = await env.drain()
    async with env.uow.transaction() as s:  # a total that doesn't add up: Bernie asks once
        open_asks = list((await s.execute(select(Ask).where(Ask.status == "open"))).scalars())
        for ask in open_asks:
            await asks.answer_ask(s, world.ravi, ask.id, {"action": ask_gap.REVIEW})
    if open_asks:
        statuses = await env.drain()
    assert statuses[0] == "succeeded"
    assert statuses.count("waiting") <= 1  # the decision job waits for the approval
    async with env.uow.transaction() as s:
        [r] = list((await s.execute(select(Record))).scalars())
        model_calls = len(
            list(
                (await s.execute(select(AgentRunStep).where(AgentRunStep.kind == "llm"))).scalars()
            )
        )
    failing = [c["id"] for c in r.checks if not c["passed"]]
    assert r.data["extraction"]["method"] == case["method"]
    assert r.status == case["status"], failing
    for cid in case.get("failing_include", []):
        assert cid in failing
    if "model_calls" in case:
        assert model_calls == case["model_calls"]
    if case.get("score", True):
        score = quality.compare(case["id"], r.data, B.truth(spec))
        SCORES.append(score)
        assert score.exact, score.misses


def test_the_mock_set_is_perfect() -> None:
    """Runs after the cases (same module): the aggregate the phase report quotes."""
    if not SCORES:
        pytest.skip("no case ran")
    totals = quality.aggregate(SCORES)
    assert totals.field_accuracy == 1.0 and totals.line_recall == 1.0
    assert totals.line_precision == 1.0 and totals.exact == totals.invoices
    assert len(CASES) >= 10
