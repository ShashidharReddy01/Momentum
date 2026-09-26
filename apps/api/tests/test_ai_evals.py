"""S3.5.1 eval harness: the mock suite passes end to end on a seeded database with the eval
workspace; every case file loads (typos in expectations are refused); placeholders resolve;
the scorers catch what they claim to; thresholds and regressions fail a report; reports
round-trip."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.ai.evals import runner
from momentum.ai.evals.features import Observation
from momentum.ai.evals.main import evals_url, reset_database
from momentum.ai.evals.runner import fill, latest, load_cases, render, run_evals, save
from momentum.ai.evals.scorers import score
from momentum.ai.evals.workspace import build_workspace
from momentum.ai.llm import build_llm
from momentum.ai.tools.catalog import build_registry
from momentum.core.db import UnitOfWork
from momentum.core.settings import Settings
from tests.conftest import make_settings

TODAY = date(2026, 9, 26)


def names(checks: list) -> dict[str, bool]:  # type: ignore[type-arg]
    return {c.name: c.passed for c in checks}


async def test_mock_suite_passes_end_to_end(
    uow: UnitOfWork,
    settings: Settings,
    seeded: None,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    async with uow.transaction() as s:
        world = await build_workspace(s, settings)
    assert "Sign vendor contract" in world.keys and "Launch Plan" in world.projects
    async with uow.transaction() as s:  # building twice changes nothing (idempotent)
        again = await build_workspace(s, settings)
    assert again.keys == world.keys
    llm = build_llm(make_settings())
    from momentum.ai.embeddings import reindex

    async with uow.transaction() as s:
        await reindex(s, llm)
    report = await run_evals(session_factory, llm, build_registry(), settings, world, live=False)
    failed = [
        (c.feature, c.id, [ch for ch in c.checks if not ch["passed"]])
        for c in report.cases
        if not c.passed
    ]
    assert not failed, failed
    assert report.ok and len(report.cases) == sum(
        1 for cases in load_cases().values() for c in cases if c.get("mock")
    )
    assert {f.feature for f in report.features} == set(load_cases())
    text = render(report)
    assert "RESULT: PASS" in text and "command" in text
    # a case's rolled-back transaction leaves nothing behind (e.g. no proposed actions)
    from sqlalchemy import func, select

    from momentum.ai.models import AiAction, AiConversation

    async with uow.transaction() as s:
        assert (await s.execute(select(func.count()).select_from(AiAction))).scalar_one() == 0
        assert (await s.execute(select(func.count()).select_from(AiConversation))).scalar_one() == 0
    path = save(report, tmp_path)
    back = latest(tmp_path, "mock")
    assert back is not None and path.name.startswith("mock-")
    assert [(f.feature, f.rate) for f in back.features] == [
        (f.feature, f.rate) for f in report.features
    ]


def test_all_case_files_load_and_typos_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases = load_cases()
    assert sum(len(v) for v in cases.values()) >= 100
    assert all(
        any(c.get("mock") for c in v) for v in cases.values()
    )  # every feature has a mock case
    (tmp_path / "command.yaml").write_text(
        "feature: command\ncases:\n  - id: x\n    input: y\n    expect: {propses: [z]}\n"
    )
    monkeypatch.setattr(runner, "CASES", tmp_path)
    with pytest.raises(ValueError, match="unknown expect keys"):
        load_cases()


def test_placeholders() -> None:
    from momentum.ai.evals.workspace import EvalWorld

    world = EvalWorld(keys={"QA the checkout flow": "T-7"})
    out = fill(
        {"input": "Complete {{key:QA the checkout flow}} by {{today+3}}", "x": ["{{today-1}}"]},
        world,
        TODAY,
    )
    assert out == {"input": "Complete T-7 by 2026-09-29", "x": ["2026-09-25"]}
    with pytest.raises(KeyError):
        fill("{{key:No such task}}", world, TODAY)


def test_scorers_catch_what_they_claim() -> None:
    obs = Observation(
        text="Launch is blocked by [T-1]. I couldn't find anything about Zenith.",
        tools=["semantic_search"],
        operations=[
            {
                "tool": "update_task",
                "args": {"task": "T-1"},
                "diff": [{"label": "T-1 Sign vendor contract"}],
            }
        ],
        risk="low",
        citations=[
            {"ref": "[T-1]", "valid": True, "title": "Sign vendor contract"},
            {"ref": "[T-9]", "valid": False, "title": None},
        ],
        grounded=True,
    )
    checks = names(
        score(
            obs,
            {
                "tools_include": ["semantic_search"],
                "tools_exclude": ["delete_task"],
                "proposes": ["update_task"],
                "risk": "low",
                "targets_include": ["Sign vendor contract"],
                "targets_exclude": ["Press kit"],
                "citations_valid": True,
                "cites_include": ["vendor contract"],
                "mentions_exclude": ["Zenith"],
                "uncertain": True,
                "grounded": True,
            },
            today=TODAY,
        )
    )
    assert checks["no_error"] and checks["tools_include:semantic_search"]
    assert (
        checks["proposes:update_task"]
        and checks["risk"]
        and checks["targets_include:Sign vendor contract"]
    )
    assert checks["citations_valid"] is False  # [T-9] didn't resolve
    assert checks["cites_include:vendor contract"] and checks["uncertain"]
    assert checks["mentions_exclude:Zenith"] is False  # the name leaked into the text
    assert names(score(Observation(error="not_found"), {"error": "not_found"}, today=TODAY)) == {
        "error": True
    }
    assert names(score(Observation(error="not_found"), {}, today=TODAY))["no_error"] is False
    plan = Observation(data={"today": ["T-2", "T-1"]})
    assert names(score(plan, {"today_first_any": ["T-1"]}, today=TODAY))["today_first_any"] is False
    qa = Observation(
        data={"due_on": "2026-09-27", "assignee": {"name": "Ana Souza"}, "priority": "high"}
    )
    got = names(
        score(
            qa,
            {"fields": {"due_in_days": 1, "assignee": "Ana Souza", "priority": "low"}},
            today=TODAY,
        )
    )
    assert got == {
        "no_error": True,
        "fields:due_in_days": True,
        "fields:assignee": True,
        "fields:priority": False,
    }
    brief = Observation(
        operations=[
            {
                "tool": "create_project_from_plan",
                "args": {"sections": [{"tasks": [{"due_on": "2026-11-02"}]}]},
            }
        ],
        data={"requested_end": "2026-11-01"},
    )
    assert names(score(brief, {"due_before_end": True}, today=TODAY))["due_before_end"] is False
    status = Observation(data={"items": ["Done [T-1]", "Vague claim"]})
    assert (
        names(score(status, {"items_cite_tasks": True}, today=TODAY))["items_cite_tasks"] is False
    )
    write = Observation(text="short", data={"input": "a much longer original text"})
    assert names(score(write, {"shorter_than": 0.5}, today=TODAY))["shorter_than"]


def test_thresholds_and_regressions_fail_a_report() -> None:
    from momentum.ai.evals.runner import FeatureSummary, Report

    report = Report(mode="live", started_at="", models={}, prompts={})
    report.features = [
        FeatureSummary("command", 10, 9, 0.9, 0.9, True),
        FeatureSummary("chat", 10, 8, 0.8, 0.85, False),
    ]
    assert not report.ok and "FAIL" in render(report)


def test_feature_verdicts() -> None:
    from momentum.ai.evals.runner import CaseResult, FeatureSummary, Report, summarize

    def results(passed: int, total: int) -> list[CaseResult]:
        return [CaseResult("chat", str(i), i < passed, [], latency_ms=10 * i) for i in range(total)]

    assert summarize("chat", results(9, 10), 0.9, None).ok
    assert not summarize("chat", results(8, 10), 0.9, None).ok  # under the threshold
    before = Report(mode="live", started_at="", models={}, prompts={})
    before.features = [FeatureSummary("chat", 10, 10, 1.0, 0.5, True)]
    dropped = summarize("chat", results(9, 10), 0.5, before)
    assert dropped.regression == 10.0 and not dropped.ok  # more than 5 points down
    small = summarize("chat", results(19, 20), 0.5, before)
    assert small.regression == 5.0 and small.ok
    assert summarize("chat", results(1, 3), 0.0, None).p50_ms == 10


def test_eval_database_is_always_a_throwaway() -> None:
    s = make_settings(database_url="postgresql+psycopg://u:p@db:5432/momentum")
    assert evals_url(s) == "postgresql+psycopg://u:p@db:5432/momentum_evals"
    assert evals_url(make_settings(database_url="postgresql+psycopg://u:p@db/x_evals")).endswith(
        "/x_evals"
    )
    with pytest.raises(SystemExit):
        reset_database("postgresql+psycopg://u:p@db:5432/momentum")  # refuses before connecting
