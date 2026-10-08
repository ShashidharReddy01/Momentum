"""Echo: the simplest test pack. Imports only momentum.sdk, like any pack."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from momentum.sdk import (
    Job,
    Money,
    Pack,
    PackSettings,
    RecordModel,
    RecordType,
    Section,
    TaskField,
    step,
)


class Vendor(RecordModel):
    name: str
    entity_id: str | None = None


class Line(RecordModel):
    description: str
    amount: Money


class EchoBill(RecordModel):
    """A test record type (S76-04): money, a currency, dates, an array, an entity link."""

    vendor: Vendor
    number: str
    total: Money
    currency: str
    dated: date
    lines: list[Line] = []


def _recheck(data: dict[str, Any]) -> list[dict[str, Any]]:
    lines = sum((Decimal(x["amount"]) for x in data.get("lines") or []), Decimal(0))
    ok = not data.get("lines") or lines == Decimal(data["total"])
    return [
        {
            "id": "lines_add_up",
            "severity": "block",
            "passed": ok,
            "title": "Lines add up to the total",
            "detail": f"Lines {lines} vs total {data['total']}",
            "fields": ["total", "lines"],
        }
    ]


ECHO_BILL = RecordType(
    key="echo_bill",
    version=1,
    model=EchoBill,
    label="Echo bill",
    title="{vendor.name} {number}",
    identity=("vendor.name", "number"),
    money=("total", "lines[].amount"),
    currency_field="currency",
    dates=("dated",),
    arrays={"lines": "Lines"},
    columns=("vendor.name", "number", "dated", "total", "currency"),
    task_fields={"Vendor": "vendor.name", "Amount": "total"},
    classification="financial",
    search=("vendor.name", "number", "lines[].description"),
    recheck_fn=_recheck,
)


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
    record_types=(ECHO_BILL,),
    setup=(
        TaskField(name="Echo status", type="single_select", options=("Waiting", "Done")),
        Section(name="Echo inbox", unless=("Inbox",)),
    ),
)
