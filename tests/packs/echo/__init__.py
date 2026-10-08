"""Echo: the simplest test pack. Imports only momentum.sdk, like any pack."""

from __future__ import annotations

from pathlib import Path

from momentum.sdk import Job, Pack, PackSettings, Section, TaskField, step


class EchoSettings(PackSettings):
    """No settings yet; settings forms are exercised from S76-05."""


@step
async def _reply(job: Job, text: str) -> str:
    if job.task_id is not None:
        await job.effects.comments.create(job.task_id, f"Echo: {text}")
    return text


async def run(job: Job) -> str:
    text = str(job.input.get("text") or "nothing to echo")
    return await job.step("reply", _reply, job, text)


pack = Pack(
    manifest_path=Path(__file__).parent / "manifest.yaml",
    run=run,
    settings=EchoSettings,
    setup=(
        TaskField(name="Echo status", type="single_select", options=("Waiting", "Done")),
        Section(name="Echo inbox", unless=("Inbox",)),
    ),
)
