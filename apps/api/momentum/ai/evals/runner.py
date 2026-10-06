"""The eval runner (S3.5.1, testing-strategy §6): loads the cases, runs each through the real
feature code on the eval workspace (each in its own rolled-back transaction), scores it, and
writes a report (``<report dir>/<mode>-<timestamp>.json``) plus a printed table.

Modes: **mock** (default) runs the cases that have mock fixtures (``mock: true``) and checks the
plumbing and the scorers; **live** (``--live``, ``EVALS_LIVE=1 make evals``) runs every case
against the configured gateway, adds the LLM-as-judge checks, and is what the thresholds are
for. A feature fails when its pass rate is under its threshold, or drops more than 5 points
from the previous report of the same mode.
"""

from __future__ import annotations

import contextlib
import json
import re
import statistics
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.ai import prompts
from momentum.ai.evals.features import FEATURES, Observation, run_case
from momentum.ai.evals.scorers import KNOWN, Check, score
from momentum.ai.evals.workspace import EvalWorld
from momentum.ai.llm import LLM
from momentum.ai.models import LlmCall
from momentum.ai.structured import extract
from momentum.ai.tools.registry import ToolRegistry
from momentum.core.settings import Settings

CASES = Path(__file__).parent / "cases"
THRESHOLDS = Path(__file__).parent / "thresholds.yaml"
REGRESSION_POINTS = 5.0
_SLOT = re.compile(r"\{\{(key|today)([:+-])([^}]*)\}\}")


@dataclass
class CaseResult:
    feature: str
    id: str
    passed: bool
    checks: list[dict[str, Any]]
    text: str = ""
    error: str | None = None
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0

    @property
    def unavailable(self) -> bool:
        """Failed only because the AI could not be reached: says nothing about quality."""
        return not self.passed and (self.error or "").startswith("ai_unavailable")


@dataclass
class FeatureSummary:
    feature: str
    cases: int
    passed: int
    rate: float
    threshold: float
    ok: bool
    regression: float | None = None
    tokens: int = 0
    cost_usd: float = 0.0
    p50_ms: int = 0
    unavailable: int = 0  # cases lost to an AI outage, left out of the rate


@dataclass
class Report:
    mode: str
    started_at: str
    models: dict[str, str]
    prompts: dict[str, str]
    features: list[FeatureSummary] = field(default_factory=list)
    cases: list[CaseResult] = field(default_factory=list)
    partial: bool = False  # only some features/cases ran: never a regression baseline

    @property
    def incomplete(self) -> bool:
        return any(f.unavailable for f in self.features)

    @property
    def ok(self) -> bool:
        return all(f.ok for f in self.features)


def load_cases(features: list[str] | None = None) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(CASES.glob("*.yaml")):
        spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        feature = str(spec.get("feature", path.stem))
        if feature not in FEATURES:
            raise ValueError(f"{path.name}: unknown feature {feature!r}")
        if features and feature not in features:
            continue
        ids = [str(c["id"]) for c in spec.get("cases", [])]
        for c in spec.get("cases", []):
            unknown = set(c.get("expect") or {}) - KNOWN
            if unknown:  # a typo would silently check nothing
                raise ValueError(f"{path.name}/{c['id']}: unknown expect keys {sorted(unknown)}")
        if len(ids) != len(set(ids)):
            raise ValueError(f"{path.name}: duplicate case ids")
        out.setdefault(feature, []).extend(spec.get("cases", []))
    return out


def fill(value: Any, world: EvalWorld, today: date) -> Any:
    """``{{key:Task title}}`` → that task's key; ``{{today+3}}`` → an ISO date."""
    if isinstance(value, str):

        def one(m: re.Match[str]) -> str:
            kind, sep, arg = m.groups()
            if kind == "key":
                if arg not in world.keys:
                    raise KeyError(f"no eval task titled {arg!r}")
                return world.keys[arg]
            days = int(arg or 0) * (-1 if sep == "-" else 1)
            return (today + timedelta(days=days)).isoformat()

        return _SLOT.sub(one, value)
    if isinstance(value, list):
        return [fill(v, world, today) for v in value]
    if isinstance(value, dict):
        return {k: fill(v, world, today) for k, v in value.items()}
    return value


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    score: int = Field(ge=1, le=5)
    reason: str = Field(max_length=500)


# An agent's source (the task context plus every tool result) runs longer than a feature's facts
SOURCE_CHARS = 16000
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


async def judge(
    llm: LLM,
    settings: Settings,
    world: EvalWorld,
    case: dict[str, Any],
    obs: Observation,
    today: date,
) -> Check:
    """LLM-as-judge (live only, ``smart`` alias): scores the output 1 to 5 by the rubric. It is
    told today's date (relative deadlines, "half the period gone") and sees people by name, not
    id (S7.3.2: without these it marked correct plans and check-ins down)."""
    spec = case["judge"]
    prompt = prompts.load("judge")
    cited = ", ".join(
        f"{c.get('ref')} {c.get('title') or ''}".strip() for c in obs.citations if c.get("valid")
    )
    # Breakdown and brief answer with a previewed action, not text: show what it would change.
    names = {str(u.id): u.name for u in world.users.values()}
    changes = _UUID.sub(
        lambda m: names.get(m.group(0), m.group(0)),
        "\n".join(
            f"{op.get('tool')}: {json.dumps(op.get('args') or {}, ensure_ascii=False)}"
            for op in obs.operations
        ),
    )[:6000]
    # A plan is judged against its dates, which live outside the operations' text.
    plan_facts = (
        [
            f"Plan ends: {obs.data['end_on']} "
            f"(requested end: {obs.data.get('requested_end') or 'none'})"
        ]
        if "end_on" in obs.data
        else []
    )
    # Claims are checked against what the feature was given (inbox notifications, status facts).
    source = obs.data.get("source") or obs.data.get("facts")
    source_block = (
        [
            "Source material the output must be true to:\n"
            + json.dumps(source, ensure_ascii=False, default=str)[:SOURCE_CHARS]
        ]
        if source
        else []
    )
    body = "\n".join(
        [
            f"Today: {today.isoformat()} ({today:%A})",
            f"Request: {case.get('input') or case.get('task') or case.get('project') or ''}",
            f"Output:\n{obs.text or '(none)'}",
            f"Proposed changes:\n{changes or '(none)'}",
            *plan_facts,
            *source_block,
            f"Valid citations: {cited or '(none)'}",
            f"Notes from the server: {'; '.join(obs.notes) or '(none)'}",
            f"Rubric: {spec['rubric']}",
        ]
    )
    ctx = world.ctx(case.get("user", "ravi"), settings)
    v = await extract(
        llm,
        ctx,
        prompt=prompt,
        system=prompt.body,
        user=f'<data source="eval">\n{body.replace("<", "&lt;")}\n</data>',
        schema=Verdict,
        description="Submit the score.",
    )
    minimum = int(spec.get("min", 4))
    return Check("judge", v.score >= minimum, f"{v.score}/5: {v.reason}")


async def run_evals(
    session_factory: async_sessionmaker[AsyncSession],
    llm: LLM,
    registry: ToolRegistry,
    settings: Settings,
    world: EvalWorld,
    *,
    live: bool,
    features: list[str] | None = None,
    case_filter: str | None = None,
    previous: Report | None = None,
    log: Any = None,
    all_cases: bool = False,
) -> Report:
    thresholds: dict[str, dict[str, float]] = yaml.safe_load(THRESHOLDS.read_text(encoding="utf-8"))
    mode = "live" if live else "mock"
    report = Report(
        mode=mode,
        started_at=datetime.now(UTC).isoformat(),
        models={a: llm.model_for(a) for a in ("fast", "default", "smart", "embed")},
        prompts={},
        partial=bool(features or case_filter),
    )
    for feature, cases in load_cases(features).items():
        results: list[CaseResult] = []
        for case in cases:
            if case_filter and case_filter not in str(case["id"]):
                continue
            if not live and not all_cases and not case.get("mock"):
                continue  # mock mode runs only the cases with handwritten fixtures
            if live and case.get("live") is False:
                continue  # checks our own code against a fixture's scripted bad output
            user = world.users[case.get("user", "ravi")]
            today = datetime.now(UTC).astimezone(ZoneInfo(user.timezone)).date()
            filled = fill(case, world, today)
            since = datetime.now(UTC)
            async with session_factory() as session:
                await session.begin()
                try:
                    obs = await run_case(session, llm, registry, settings, world, filled, feature)
                    checks = score(
                        obs,
                        filled.get("expect") or {},
                        today=today,
                        asked=str(filled.get("input") or ""),
                    )
                    if live and filled.get("judge") and obs.error is None:
                        checks.append(await judge(llm, settings, world, filled, obs, today))
                finally:
                    await session.rollback()
            tokens_in, tokens_out, cost = await _usage(session_factory, since)
            result = CaseResult(
                feature=feature,
                id=str(case["id"]),
                passed=all(c.passed for c in checks),
                checks=[asdict(c) for c in checks],
                text=(obs.text or "")[:600],
                error=obs.error,
                latency_ms=obs.latency_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=float(cost),
            )
            results.append(result)
            if log:
                log(f"{'PASS' if result.passed else 'FAIL'} {feature}/{result.id}")
        if not results:
            continue
        report.cases += results
        threshold = float((thresholds.get(mode) or {}).get(feature, 1.0))
        report.features.append(summarize(feature, results, threshold, previous))
    for feature in {r.feature for r in report.cases}:
        with contextlib.suppress(LookupError):
            report.prompts[feature] = prompts.load(_prompt_name(feature)).version
    return report


def summarize(
    feature: str, results: list[CaseResult], threshold: float, previous: Report | None
) -> FeatureSummary:
    """A feature's pass rate against its threshold and against the previous report."""
    lost = sum(r.unavailable for r in results)
    counted = len(results) - lost
    passed = sum(r.passed for r in results)
    rate = passed / counted if counted else 0.0
    regression = None
    if previous is not None:
        # Compare on the cases both runs have: a feature that gained cases isn't a regression.
        then = {
            c.id: c.passed for c in previous.cases if c.feature == feature and not c.unavailable
        }
        now = {r.id: r.passed for r in results if not r.unavailable}
        common = then.keys() & now.keys()
        before = next((f for f in previous.features if f.feature == feature), None)
        if common:
            drop = sum(then[i] for i in common) / len(common) - sum(now[i] for i in common) / len(
                common
            )
            regression = round(drop * 100, 1)
        elif before is not None and not previous.cases:  # an old report without per-case results
            regression = round((before.rate - rate) * 100, 1)
    ok = lost == 0 and rate >= threshold and (regression is None or regression <= REGRESSION_POINTS)
    return FeatureSummary(
        feature=feature,
        cases=len(results),
        passed=passed,
        rate=rate,
        threshold=threshold,
        ok=ok,
        regression=regression,
        tokens=sum(r.tokens_in + r.tokens_out for r in results),
        cost_usd=round(sum(r.cost_usd for r in results), 6),
        p50_ms=int(statistics.median(r.latency_ms for r in results)),
        unavailable=lost,
    )


def _prompt_name(feature: str) -> str:
    return {"from_brief": "project_brief"}.get(feature, feature)


async def _usage(
    session_factory: async_sessionmaker[AsyncSession], since: datetime
) -> tuple[int, int, Decimal]:
    async with session_factory() as s:
        row = (
            await s.execute(
                select(
                    func.coalesce(func.sum(LlmCall.tokens_in), 0),
                    func.coalesce(func.sum(LlmCall.tokens_out), 0),
                    func.coalesce(func.sum(LlmCall.cost_usd), 0),
                ).where(LlmCall.created_at >= since)
            )
        ).one()
    return int(row[0]), int(row[1]), Decimal(row[2])


def render(report: Report) -> str:
    lines = [
        f"Evals ({report.mode}) · models: "
        + ", ".join(f"{k}={v}" for k, v in report.models.items()),
        f"{'feature':<18} {'pass':>9} {'rate':>6} {'need':>6} {'Δ':>6} {'tokens':>8} "
        f"{'cost $':>8} {'p50 ms':>7}  result",
    ]
    for f in report.features:
        delta = "" if f.regression is None else f"{-f.regression:+.1f}"
        cost = "n/a" if f.cost_usd == 0 and f.tokens else f"{f.cost_usd:.4f}"
        lines.append(
            f"{f.feature:<18} {f.passed:>4}/{f.cases:<4} {f.rate * 100:>5.0f}% "
            f"{f.threshold * 100:>5.0f}% {delta:>6} {f.tokens:>8} {cost:>8} "
            f"{f.p50_ms:>7}  {'INCOMPLETE' if f.unavailable else 'ok' if f.ok else 'FAIL'}"
        )
    failed = [c for c in report.cases if not c.passed and not c.unavailable]
    if failed:
        lines.append("")
        lines.append("Failed cases:")
        for c in failed:
            why = "; ".join(f"{ch['name']} ({ch['detail']})" for ch in c.checks if not ch["passed"])
            lines.append(f"- {c.feature}/{c.id}: {why}"[:400])
    lost = sum(f.unavailable for f in report.features)
    if lost:
        lines.append("")
        lines.append(
            f"{lost} case(s) could not reach the AI (outage, not a quality result) and are left "
            "out of the rates. Rerun."
        )
    lines.append("")
    lines.append(
        "RESULT: " + ("INCOMPLETE" if report.incomplete else "PASS" if report.ok else "FAIL")
    )
    return "\n".join(lines)


def save(report: Report, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    path = directory / f"{report.mode}-{stamp}.json"
    path.write_text(json.dumps(asdict(report), indent=2, default=str), encoding="utf-8")
    return path


def latest(directory: Path, mode: str) -> Report | None:
    """The newest report that is a fair baseline: a full run that no outage cut short."""
    for path in sorted(directory.glob(f"{mode}-*.json"), reverse=True):
        raw = json.loads(path.read_text(encoding="utf-8"))
        features = [FeatureSummary(**f) for f in raw.get("features", [])]
        if raw.get("partial") or any(f.unavailable for f in features):
            continue
        return Report(
            mode=raw["mode"],
            started_at=raw["started_at"],
            models=raw.get("models", {}),
            prompts=raw.get("prompts", {}),
            features=features,
            cases=[CaseResult(**c) for c in raw.get("cases", [])],
        )
    return None


def elapsed(started: float) -> str:
    return f"{time.monotonic() - started:.0f}s"
