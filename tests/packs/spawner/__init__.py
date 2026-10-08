"""Spawner: a test pack that fans out to child jobs and gathers them (S76-02)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from momentum.sdk import Job, Pack, step


@step
async def _square(x: int) -> int:
    return x * x


@step
async def _total(values: list[int]) -> int:
    return sum(values)


async def batch(job: Job) -> dict[str, Any]:
    n = int(job.input.get("n", 20))
    children = [
        await job.spawn("square", {"x": i}, title=f"Square {i}", key=f"item:{i}") for i in range(n)
    ]
    results = await job.gather(children)
    failed = [r.key for r in results if not r.ok]
    total = await job.step("total", _total, [int(r.output) for r in results if r.ok])
    await job.progress(len(results), n, "Squared")
    return {"total": total, "failed": failed}


async def square(job: Job) -> int:
    return await job.step("square", _square, int(job.input["x"]))


async def ask_model(job: Job) -> str:
    return await job.llm.complete("ask", prompt=str(job.input.get("question") or "Hello?"))


pack = Pack(
    manifest_path=Path(__file__).parent / "manifest.yaml",
    run=batch,
    capabilities={"square": square, "ask_model": ask_model},
)
