"""Failer: a test pack whose last step fails, crashes or succeeds on command (S76-02).

``SWITCH`` and ``CALLS`` are test controls: a test sets ``SWITCH["fail"]`` / ``SWITCH["crash"]``
and reads ``CALLS`` to prove that finished steps never run twice."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from momentum.sdk import Job, Pack, step

SWITCH: dict[str, bool] = {"fail": False, "crash": False}
CALLS: Counter[str] = Counter()


class Crash(BaseException):
    """Not an Exception: it escapes the engine like a killed process would."""


@step
async def _comment(job: Job, text: str) -> str:
    CALLS["comment"] += 1
    assert job.task_id is not None
    comment_id = await job.effects.comments.create(job.task_id, text)
    return str(comment_id)


@step
async def _rename(job: Job) -> None:
    CALLS["rename"] += 1
    if SWITCH["crash"]:
        raise Crash  # the worker "dies" after the comment step committed
    assert job.task_id is not None
    await job.effects.tasks.rename(job.task_id, "Checked by Failer")


@step
async def _subtask(job: Job) -> str:
    CALLS["subtask"] += 1
    assert job.task_id is not None
    return str(await job.effects.tasks.create_subtask(job.task_id, "Failer's follow-up"))


@step
async def _last(job: Job) -> int:
    CALLS["last"] += 1
    if SWITCH["fail"]:
        raise RuntimeError("the last step failed on purpose")
    return 42


async def run(job: Job) -> dict[str, Any]:
    comment = await job.step("comment", _comment, job, "Failer was here")
    await job.step("rename", _rename, job)
    subtask = await job.step("subtask", _subtask, job)
    answer = await job.step("last", _last, job)
    job.log(f"Finished with {answer}")
    return {"comment": comment, "subtask": subtask, "answer": answer}


pack = Pack(manifest_path=Path(__file__).parent / "manifest.yaml", run=run)
