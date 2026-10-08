"""Echo: the simplest test pack (S76-01). Imports only momentum.sdk, like any pack."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from momentum.sdk import Pack, PackSettings, Section, TaskField


class EchoSettings(PackSettings):
    """No settings yet; settings forms are exercised from S76-05."""


async def run(job: Any) -> None:  # the durable job lands in S76-02
    raise NotImplementedError("Echo runs as a durable job from S76-02")


pack = Pack(
    manifest_path=Path(__file__).parent / "manifest.yaml",
    run=run,
    settings=EchoSettings,
    setup=(
        TaskField(name="Echo status", type="single_select", options=("Waiting", "Done")),
        Section(name="Echo inbox", unless=("Inbox",)),
    ),
)
