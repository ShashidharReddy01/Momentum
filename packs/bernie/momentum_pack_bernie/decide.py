"""Waiting for a person's decision about one invoice (spec §9.3.18-19), as its own small job on the
invoice's task, so the invoice's job (and a batch's summary and catalogue) don't wait for it.

- **approval:** wait for ``approval.decided`` on the approval subtask; approved → the record is
  approved, rejected → rejected, changes requested → back to review.
- **hold:** ask the route (stewards for a bank change, the requester for a duplicate). A bank
  change confirmed with the vendor makes the new account the one on file and the invoice goes on
  to its approval; "reject" rejects the record; no answer leaves it in review."""

from __future__ import annotations

import uuid
from typing import Any

from momentum.sdk import Job, step
from momentum_pack_bernie import outputs, policy
from momentum_pack_bernie.checks_math import dec


@step
async def _set_status(
    job: Job,
    record_id: str,
    status: str,
    reason: str,
    authority: str | None,
    approval_task_id: str | None,
    ask_id: str | None,
) -> int:
    [rec] = await job.records.load([uuid.UUID(record_id)])
    return await job.effects.records.update(
        uuid.UUID(record_id),
        [{"op": "set_status", "status": status, "reason": reason[:1000]}],
        expected_version=rec.version,
        authority=authority,  # type: ignore[arg-type]
        approval_task_id=uuid.UUID(approval_task_id) if approval_task_id else None,
        ask_id=uuid.UUID(ask_id) if ask_id else None,
    )


@step
async def _status_field(job: Job, status: str) -> None:
    if job.task_id is not None:
        await job.effects.tasks.set_fields(
            job.task_id,
            {"Invoice status": outputs.STATUS_LABELS.get(status, "Needs review")},
            skip_missing=True,
        )


@step
async def _confirm_bank(job: Job, entity_id: str, last4: str) -> bool:
    return await job.effects.entities.confirm_bank(uuid.UUID(entity_id), last4)


@step
async def _redecide(
    job: Job, record_id: str, decision: dict[str, Any], checks: list[dict[str, Any]]
) -> int:
    [rec] = await job.records.load([uuid.UUID(record_id)])
    return await job.effects.records.update(
        uuid.UUID(record_id),
        [],
        expected_version=rec.version,
        checks=checks,
        decision=decision,
    )


@step
async def _comment(job: Job, text: str) -> None:
    if job.task_id is not None:
        await job.effects.comments.create(job.task_id, text)


@step
async def _request_approval(job: Job, data: dict[str, Any], description: str, approver: str) -> str:
    assert job.task_id is not None
    tid = await job.effects.tasks.request_approval(
        job.task_id,
        outputs.approval_title(data),
        approver_id=uuid.UUID(approver),
        description=description,
    )
    return str(tid)


async def run(job: Job) -> dict[str, Any]:
    inp = job.input
    record_id = str(inp["record_id"])
    if inp.get("kind") == "approval":
        return await _await_approval(job, record_id, str(inp["approval_task_id"]))
    return await _await_hold(job, record_id, inp)


async def _await_approval(job: Job, record_id: str, approval_task_id: str) -> dict[str, Any]:
    event = await job.wait_for_event(
        "approval", "approval.decided", task_id=uuid.UUID(approval_task_id)
    )
    state = str((event.get("data") or {}).get("state") or event.get("state") or "")
    if state == "approved":
        status, authority = "approved", "approval"
    elif state == "rejected":
        status, authority = "rejected", "approval"
    else:  # changes requested: back to review
        status, authority = "needs_review", None
    await job.step(
        "status",
        _set_status,
        job,
        record_id,
        status,
        f"Approval {state.replace('_', ' ') or 'decided'}",
        authority,
        approval_task_id if authority else None,
        None,
    )
    await job.step("status_field", _status_field, job, status)
    return {"record_id": record_id, "status": status}


async def _await_hold(job: Job, record_id: str, inp: dict[str, Any]) -> dict[str, Any]:
    decision = dict(inp.get("decision") or {})
    rec = await job.records.get("record", uuid.UUID(record_id))
    spec = outputs.hold_ask(rec.data, decision)
    settings = await job.settings()
    answer = await job.ask(
        "hold",
        kind="choice",
        title=spec["title"],
        body=spec["body"],
        options=spec["options"],
        route=decision.get("route") or "stewards",
        default_on_expiry={"action": "route_to_review"},
        expires_in_days=float(settings.ask_expiry_days),
        remind_in_hours=24,
    )
    if not answer.answered:
        await job.step(
            "left_in_review",
            _comment,
            job,
            "Nobody answered about the hold, so the invoice stays in review.",
        )
        return {"record_id": record_id, "status": "needs_review"}
    if answer.value == outputs.REJECT:
        await job.step(
            "status",
            _set_status,
            job,
            record_id,
            "rejected",
            "Rejected when asked about the hold",
            "ask",
            None,
            str(answer.ask_id),
        )
        await job.step("status_field", _status_field, job, "rejected")
        return {"record_id": record_id, "status": "rejected"}

    # confirmed (a bank change checked with the vendor, or not a duplicate): decide again
    rule = decision.get("rule_id")
    cleared = "bank_changed" if rule == "block_bank_change" else "duplicate"
    if rule == "block_bank_change" and inp.get("entity_id") and inp.get("bank_last4"):
        await job.step(
            "confirm_bank", _confirm_bank, job, str(inp["entity_id"]), str(inp["bank_last4"])
        )
    checks = [
        {**c, "passed": True, "detail": f"{c.get('detail')} Confirmed by a person."}
        if c["id"] == cleared and not c["passed"]
        else c
        for c in rec.checks
    ]
    pctx = policy.PolicyContext(
        checks=checks,
        settings=settings,
        vendor_is_new=bool(any(c["id"] == "first_invoice" and not c["passed"] for c in checks)),
        amount=dec(rec.data.get("stated_total")),
        currency=rec.data.get("currency"),
        confidence=float(_confidence(rec)),
        vendor=(rec.data.get("vendor") or {}).get("name") or "",
        invoice_number=rec.data.get("invoice_number") or "",
    )
    new = policy.decide(pctx).as_dict()
    if new["decision"] == "allow":  # never auto-approve after a hold: a person approves
        new = {
            **new,
            "decision": "require_human",
            "route": "approver",
            "rule_id": "after_hold",
            "reason": "It was on hold, so a person approves it.",
        }
    await job.step("redecide", _redecide, job, record_id, new, checks)
    if new["decision"] != "require_human":
        await job.step("still_held", _comment, job, f"Still needs a person: {new['reason']}")
        return {"record_id": record_id, "status": "needs_review"}
    people = await job.people("approvers", "approver")
    if not people:
        return {"record_id": record_id, "status": "needs_review"}
    description = outputs.approval_description(rec.data, checks, new, f"/records/{record_id}")
    approval = await job.step(
        "approval_task", _request_approval, job, rec.data, description, str(people[0])
    )
    return await _await_approval(job, record_id, approval)


def _confidence(rec: Any) -> float:
    try:
        return float(rec.confidence if rec.confidence is not None else 1.0)
    except (TypeError, ValueError):
        return 1.0
