"""S6.5.3: the Monte Carlo core of a project forecast, pure and deterministic (no database).

A run replays the future one week at a time: each week takes one of the project's own past
weeks at random (a bootstrap: the team's real good and bad weeks, in any order), finishing what
was finished that week and adding what was added to the project that week (scope growth, paired
with the same week so busy weeks stay busy), until the remaining work is done. Many runs give a
distribution of finish days; P50/P80/P95 are its percentiles. Dependencies are respected
roughly: no run can finish before the longest chain of open dependent work (the critical chain)
could, however fast the team is.

Pure Python on purpose (kickoff: ``numpy`` only if measured too slow): 10,000 runs over a
typical project take a few hundred milliseconds.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

MAX_WEEKS = 520  # ten years: a run that hasn't finished by then is reported as that


@dataclass(frozen=True)
class Percentiles:
    p50: int  # days from the forecast date until the work is done
    p80: int
    p95: int


def weekly_throughput(done_days: Sequence[tuple[int, float]], weeks: int) -> list[float]:
    """Throughput per week, oldest first, from ``(days_before_as_of, amount)`` completions:
    week 0 is the ``weeks``-th week back, the last one is the seven days ending at the forecast
    date. Weeks with nothing done count as zero (they happened too)."""
    out = [0.0] * weeks
    for ago, amount in done_days:
        if ago < 0:
            continue
        i = ago // 7
        if i < weeks:
            out[weeks - 1 - i] += amount
    return out


def simulate(
    remaining: float,
    samples: Sequence[float],
    *,
    runs: int,
    rng: random.Random,
    floor_days: int = 0,
    added: Sequence[float] | None = None,
) -> list[int] | None:
    """Finish day of each run, sorted; ``None`` when the history never finished anything.
    ``added`` (same length as ``samples``) is the work added in each of those weeks."""
    if remaining <= 0:
        return [max(0, floor_days)] * runs
    pool = list(samples)
    if not pool or max(pool) <= 0:
        return None
    n = len(pool)
    grow = list(added) if added is not None else [0.0] * n
    days: list[int] = []
    for _ in range(runs):
        left = remaining
        week = 0
        while True:
            i = rng.randrange(n)
            t = pool[i]
            left += grow[i]
            if t >= left:
                # part of the last week: finished on the day that week's pace gets there
                d = week * 7 + max(1, math.ceil(7 * left / t))
                break
            left -= t
            week += 1
            if week >= MAX_WEEKS:
                d = MAX_WEEKS * 7
                break
        days.append(max(d, floor_days))
    days.sort()
    return days


def percentiles(days: Sequence[int]) -> Percentiles:
    """Nearest-rank percentiles of sorted finish days."""

    def at(q: float) -> int:
        return days[max(0, math.ceil(q * len(days)) - 1)]

    return Percentiles(p50=at(0.5), p80=at(0.8), p95=at(0.95))


def longest_chain(durations: dict[str, int], edges: Sequence[tuple[str, str]]) -> int:
    """Total days along the longest chain of dependent tasks (``(task, blocker)`` edges between
    open tasks; cycles, which the app prevents, are ignored rather than looped over)."""
    blockers: dict[str, list[str]] = {}
    for task, blocker in edges:
        if task in durations and blocker in durations:
            blockers.setdefault(task, []).append(blocker)
    memo: dict[str, int] = {}
    visiting: set[str] = set()

    def length(t: str) -> int:
        if t in memo:
            return memo[t]
        if t in visiting:
            return 0
        visiting.add(t)
        best = max((length(b) for b in blockers.get(t, [])), default=0)
        visiting.discard(t)
        memo[t] = best + durations[t]
        return memo[t]

    return max((length(t) for t in durations), default=0)
