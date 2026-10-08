"""Asker: a test pack that asks one question of a given kind (S76-03), waits for instructions, and
talks about its work when @mentioned (a conversation run)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from momentum.sdk import Job, Pack, step

GUESS = "Asker's guess"
SPECS: dict[str, dict[str, Any]] = {
    "choice": {
        "kind": "choice",
        "title": "Which vendor sent this invoice?",
        "options": [
            {"value": "acme", "label": "Acme Ltd", "description": GUESS},
            {"value": "globex", "label": "Globex"},
        ],
        "default_on_expiry": {"value": "acme"},
    },
    "confirm": {
        "kind": "confirm",
        "title": "Post this invoice?",
        "default_on_expiry": {"action": "route_to_review"},
    },
    "form": {
        "kind": "form",
        "title": "The total doesn't add up",
        "body": "Lines add up to 1,200.00 but the total says 1,250.00.",
        "form": [
            {"name": "amount", "label": "Amount", "type": "money"},
            {"name": "due", "label": "Due date", "type": "date", "required": False},
        ],
        "default_on_expiry": {"action": "fail"},
    },
    "text": {
        "kind": "text",
        "title": "What's the PO number?",
        "default_on_expiry": {"action": "escalate"},
    },
    "pick_entity": {
        "kind": "pick_entity",
        "title": "Which vendor is this?",
        "options": [{"value": "e1", "label": "Northwind"}, {"value": "e2", "label": "Contoso"}],
        "default_on_expiry": {"action": "route_to_review"},
    },
    "pick_record": {
        "kind": "pick_record",
        "title": "Is this a duplicate of one of these?",
        "options": [{"value": "r1", "label": "INV-1"}, {"value": "r2", "label": "INV-2"}],
        "default_on_expiry": {"value": "r1"},
    },
}


@step
async def _say(job: Job, text: str) -> None:
    assert job.task_id is not None
    await job.effects.comments.create(job.task_id, text)


async def run(job: Job) -> Any:
    what = str(job.input.get("text") or "choice")
    if what == "wait":
        instruction = await job.wait_for_instruction("instruction")
        await job.step("said", _say, job, f"Told to: {instruction.get('action')}")
        return instruction
    answer = await job.ask("question", **SPECS[what])
    await job.step("said", _say, job, f"Got {answer.value!r} ({answer.status})")
    return answer.model_dump(mode="json")


async def converse(job: Job) -> str:
    intent = await job.classify()
    if intent.kind == "question":
        jobs = await job.jobs_on_task()
        await job.step("reply", _say, job, f"I have {len(jobs)} job(s) on this task.")
        return "answered"
    ok = await job.ask(
        "confirm",
        kind="confirm",
        title=f"Shall I {intent.command}?",
        default_on_expiry={"value": False},
    )
    if not ok.value:
        return "declined"
    if intent.command == "skip":
        waiting = [j for j in await job.jobs_on_task("waiting") if j.waiting_on == "instruction"]
        await job.send_instruction("send", waiting[0].run_id, {"action": "skip"})
        return "sent"
    new = await job.start_job("start", {"text": "confirm"})
    return str(new)


pack = Pack(manifest_path=Path(__file__).parent / "manifest.yaml", run=run, converse=converse)
