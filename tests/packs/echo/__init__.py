"""Echo: the simplest test pack. Imports only momentum.sdk, like any pack."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import Field

from momentum.sdk import (
    EntityModel,
    EntityType,
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


class EchoVendorAttributes(EntityModel):
    """A test entity type (S76-05)."""

    tax_ids: list[str] = []
    country: str | None = None
    bank: dict[str, Any] | None = None  # fingerprint + last4 only, set through set_bank


def _vendor_profile(entity: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    totals = sorted(Decimal(r["total"]) for r in records if r.get("total"))
    return {
        "records": len(records),
        "median_total": str(totals[len(totals) // 2]) if totals else None,
    }


ECHO_VENDOR = EntityType(
    key="echo_vendor",
    model=EchoVendorAttributes,
    label="Echo vendor",
    profile_fn=_vendor_profile,
)


class EchoSettings(PackSettings):
    """Settings forms, stewards and approvers are exercised by S76-05's tests."""

    stewards: list[str] = Field(
        default_factory=list,
        title="Stewards",
        description="People who look after Echo: review its skills, change its settings",
        json_schema_extra={"ui": "people"},
    )
    approvers: list[str] = Field(
        default_factory=list,
        title="Approvers",
        description="Who approves what Echo prepares",
        json_schema_extra={"ui": "people"},
    )
    threshold: int = Field(
        default=100,
        ge=0,
        title="Threshold",
        description="A number",
        json_schema_extra={"ui": "int"},
    )
    watch_uploads: bool = Field(
        default=False,
        title="Watch uploads",
        description="Run on every file uploaded to the project (a consent switch, S76-06)",
        json_schema_extra={"ui": "bool"},
    )
    tone: str = Field(
        default="plain",
        title="Tone",
        description="How Echo writes",
        json_schema_extra={"ui": "enum", "options": ["plain", "friendly"]},
    )


@step
async def _reply(job: Job, text: str) -> str:
    if job.task_id is not None:
        await job.effects.comments.create(job.task_id, f"Echo: {text}")
    return text


async def tryout(job: Job) -> str:
    """A canned tryout: the skill fixed one field and broke nothing."""
    skill_id = str(job.input["skill_id"])

    @step
    async def _record() -> None:
        import uuid

        await job.effects.skills.record_tryout(
            uuid.UUID(skill_id),
            {"status": "done", "before": {"wrong": 1}, "after": {"wrong": 0}, "regressions": []},
        )

    await job.step("record", _record)
    return skill_id


async def run(job: Job) -> str:
    text = str(job.input.get("text") or "nothing to echo")
    return await job.step("reply", _reply, job, text)


pack = Pack(
    manifest_path=Path(__file__).parent / "manifest.yaml",
    run=run,
    settings=EchoSettings,
    record_types=(ECHO_BILL,),
    entity_types=(ECHO_VENDOR,),
    capabilities={"tryout": tryout},
    setup=(
        TaskField(name="Echo status", type="single_select", options=("Waiting", "Done")),
        Section(name="Echo inbox", unless=("Inbox",)),
    ),
)
