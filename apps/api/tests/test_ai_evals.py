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
from momentum.ai.evals.scorers import _close, _query_matches, score
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


def test_leak_check_ignores_words_the_asker_typed_but_not_citations() -> None:
    said = Observation(text="I found no task about Zenith Corp.")
    expect = {"mentions_exclude": ["Zenith"]}
    assert names(score(said, expect, today=TODAY, asked="Mark the Zenith task done"))[
        "mentions_exclude:Zenith"
    ]
    # the same words in an answer to a question that never mentioned them are a leak
    assert not names(score(said, expect, today=TODAY, asked="What is blocked?"))[
        "mentions_exclude:Zenith"
    ]
    cited = Observation(text="ok", citations=[{"title": "Zenith Corp", "valid": True}])
    assert not names(score(cited, expect, today=TODAY, asked="Zenith"))["mentions_exclude:Zenith"]


def test_clarifies_accepts_a_question_in_words_only_when_nothing_is_proposed() -> None:
    words = Observation(text="Which pricing task do you mean?")
    assert names(score(words, {"clarifies": True}, today=TODAY))["clarifies"]
    listed = Observation(text="Which do you mean?\n- [T-1] A\n- [T-2] B")  # question first
    assert names(score(listed, {"clarifies": True}, today=TODAY))["clarifies"]
    acted = Observation(text="Which one?", operations=[{"tool": "update_task"}])
    assert not names(score(acted, {"clarifies": True}, today=TODAY))["clarifies"]
    assert not names(score(Observation(text="Done."), {"clarifies": True}, today=TODAY))[
        "clarifies"
    ]


def _case(id: str, passed: bool, error: str | None = None) -> runner.CaseResult:
    return runner.CaseResult(feature="f", id=id, passed=passed, checks=[], error=error)


def test_an_outage_is_not_a_quality_failure_and_makes_the_run_incomplete() -> None:
    results = [
        _case("a", True),
        _case("b", True),
        _case("c", False, "ai_unavailable:connection"),
    ]
    summary = runner.summarize("f", results, 0.9, None)
    assert summary.rate == 1.0 and summary.unavailable == 1  # left out of the rate
    assert not summary.ok  # but never a clean pass
    report = runner.Report(mode="live", started_at="", models={}, prompts={}, features=[summary])
    assert report.incomplete and "INCOMPLETE" in render(report)
    # a case that failed for another reason still counts against the rate
    assert (
        runner.summarize("f", [_case("a", True), _case("b", False, "boom")], 0.5, None).rate == 0.5
    )
    # a case that expected the outage and got it passed, so it is not "lost"
    assert not _case("x", True, "ai_unavailable:connection").unavailable


def test_partial_and_incomplete_reports_are_never_the_baseline(tmp_path: Path) -> None:
    def write(name: str, *, partial: bool = False, unavailable: int = 0, rate: float = 1.0) -> None:
        feature = runner.FeatureSummary(
            feature="f",
            cases=4,
            passed=4,
            rate=rate,
            threshold=0.9,
            ok=True,
            unavailable=unavailable,
        )
        report = runner.Report(
            mode="live", started_at=name, models={}, prompts={}, features=[feature], partial=partial
        )
        (tmp_path / f"live-{name}.json").write_text(
            __import__("json").dumps(runner.asdict(report)), encoding="utf-8"
        )

    write("1-full", rate=0.8)
    write("2-outage", unavailable=3)
    write("3-partial", partial=True)
    baseline = latest(tmp_path, "live")
    assert baseline is not None and baseline.started_at == "1-full"
    assert latest(tmp_path / "missing", "live") is None


def test_regression_compares_only_the_cases_both_runs_have() -> None:
    def prev(passed: dict[str, bool]) -> runner.Report:
        cases = [_case(i, ok) for i, ok in passed.items()]
        feature = runner.summarize("f", cases, 0.5, None)
        return runner.Report(
            mode="live", started_at="", models={}, prompts={}, features=[feature], cases=cases
        )

    before = prev({"a": True, "b": True})  # 100% on two cases
    # ten cases now, two new ones fail: the shared cases still pass, so no regression
    now = [_case(i, True) for i in "abcdefgh"] + [_case("x", False), _case("y", False)]
    summary = runner.summarize("f", now, 0.5, before)
    assert summary.rate == 0.8 and summary.regression == 0.0 and summary.ok
    # a shared case that used to pass and now fails is one
    worse = runner.summarize("f", [_case("a", True), _case("b", False)], 0.1, before)
    assert worse.regression == 50.0 and not worse.ok


def test_grounded_needs_a_source_that_bears_on_the_question() -> None:
    """Round 2 of the Phase 5 live run: an honest "found nothing" that cites unrelated projects
    for context isn't grounded; a real answer with a valid citation is."""
    admits = Observation(
        text="I couldn't find anything about that. Related: [P:Launch Plan].", grounded=True
    )
    assert names(score(admits, {"grounded": False}, today=TODAY))["grounded"] is True
    answer = Observation(text="The launch waits on [T-32] Sign vendor contract.", grounded=True)
    assert names(score(answer, {"grounded": True}, today=TODAY))["grounded"] is True
    uncited = Observation(text="The launch waits on the contract.", grounded=False)
    assert names(score(uncited, {"grounded": True}, today=TODAY))["grounded"] is False


def test_agent_tools_any_accepts_either_tool() -> None:
    drafted = Observation(data={"tools": ["get_task", "semantic_search"]})
    expect = {"agent_tools_any": ["search_tasks", "semantic_search"]}
    assert names(score(drafted, expect, today=TODAY))["agent_tools_any"] is True
    assert (
        names(score(Observation(data={"tools": ["get_task"]}), expect, today=TODAY))[
            "agent_tools_any"
        ]
        is False
    )


def test_numbers_round_half_up_and_yes_no_match_booleans() -> None:
    """Live run 2026-10-08: 765.625 written as 765.63 (the way people round) is the tool's number,
    and a filter on paid = false is the same query as paid = "no"."""
    assert _close(765.63, {765.625})
    assert _close(2.6, {2.45}) is False
    assert _close(57.7, {0.577})
    want = {"filters": [{"column": "paid", "op": "eq", "value": "no"}]}
    assert _query_matches(want, {"filters": [{"column": "Paid", "op": "eq", "value": False}]})
    assert not _query_matches(want, {"filters": [{"column": "Paid", "op": "eq", "value": True}]})


def test_numbers_from_tools_allows_row_counts_and_asides_in_brackets() -> None:
    """Live run 2026-10-08: "these 5 customers" (five rows came back) and "Total (12,735.43)"
    are numbers the tool gave; 999 is not."""
    out = {"data": {"rows": [["a", 1], ["b", 2], ["c", 3], ["d", 4], ["e", 12735.43]]}}
    calls = [{"name": "query_table", "ok": True, "args": {}, "output": out}]
    for text, ok in (("These 5 customers; Total (12,735.43)", True), ("About 999 rows", False)):
        obs = Observation(text=text, data={"tool_calls": calls})
        checks = score(obs, {"numbers_from_tools": True}, today=date(2026, 10, 8))
        (check,) = [c for c in checks if c.name == "numbers_from_tools"]
        assert check.passed is ok, (text, check.detail)
