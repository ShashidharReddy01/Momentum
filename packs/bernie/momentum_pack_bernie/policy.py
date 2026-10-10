"""Bernie's policy (spec §8.4, §9.3.17): deterministic rules over the checks, the vendor and the
settings; the first rule that fires decides, every rule's result is kept on the record.

Auto-approval is off by default; even when it's on, it never covers a new vendor, changed bank
details, a material amount, low confidence or any failed check (blocking or warning)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from momentum.sdk.policy import Decision, Policy, Rule


@dataclass
class PolicyContext:
    checks: list[dict[str, Any]]
    settings: Any
    vendor_is_new: bool
    amount: Decimal | None
    currency: str | None
    confidence: float
    vendor: str = ""
    invoice_number: str = ""
    bank_last4_old: str = "?"
    bank_last4_new: str = "?"
    extra: dict[str, Any] = field(default_factory=dict)

    def failed(self, cid: str) -> dict[str, Any] | None:
        return next((c for c in self.checks if c["id"] == cid and not c["passed"]), None)

    def check_failed(self, cid: str) -> bool:
        return self.failed(cid) is not None

    @property
    def blocking_checks(self) -> list[str]:
        return [c["id"] for c in self.checks if not c["passed"] and c["severity"] == "block"]

    @property
    def warnings(self) -> list[str]:
        return [c["id"] for c in self.checks if not c["passed"] and c["severity"] == "warn"]

    @property
    def material(self) -> bool:
        """At or above the currency's materiality; any other currency (or no amount) is."""
        limits = {k.upper(): v for k, v in (self.settings.materiality or {}).items()}
        cur = (self.currency or "").upper()
        if self.amount is None or cur not in limits:
            return True
        return abs(self.amount) >= Decimal(str(limits[cur]))

    @property
    def duplicate_of(self) -> str:
        c = self.failed("duplicate")
        return str(c.get("detail") or "") if c else ""

    @property
    def amount_text(self) -> str:
        return f"{self.currency or ''} {self.amount if self.amount is not None else '?'}".strip()

    @property
    def blocking_text(self) -> str:
        return ", ".join(c.replace("_", " ") for c in self.blocking_checks)

    @property
    def warning_text(self) -> str:
        return ", ".join(c.replace("_", " ") for c in self.warnings)


POLICY = Policy(
    "bernie.invoice",
    rules=[
        Rule(
            "block_bank_change",
            when=lambda c: c.check_failed("bank_changed"),
            decide="hold",
            route="stewards",
            reason="Bank details differ from the ones on file (•••• {bank_last4_old} → "
            "•••• {bank_last4_new}).",
        ),
        Rule(
            "duplicate",
            when=lambda c: c.check_failed("duplicate"),
            decide="hold",
            route="requester",
            reason="Looks like a duplicate: {duplicate_of}",
        ),
        Rule(
            "not_reconciled",
            when=lambda c: bool(c.blocking_checks),
            decide="require_human",
            route="requester",
            reason="Some checks didn't pass: {blocking_text}.",
        ),
        Rule(
            "new_vendor",
            when=lambda c: c.vendor_is_new,
            decide="require_human",
            route="approver",
            reason="The first invoice from {vendor}.",
        ),
        Rule(
            "material",
            when=lambda c: c.material,
            decide="require_human",
            route="approver",
            reason="{amount_text} is at or above the amount that needs a person.",
        ),
        Rule(
            "low_confidence",
            when=lambda c: c.confidence < float(c.settings.confidence_floor),
            decide="require_human",
            route="approver",
            reason="Bernie isn't sure enough of what it read ({confidence:.0%}).",
        ),
        Rule(
            "anomaly",
            when=lambda c: c.check_failed("amount_anomaly"),
            decide="require_human",
            route="approver",
            reason="The total is outside this vendor's usual range.",
        ),
        Rule(
            "warnings",
            when=lambda c: bool(c.warnings),
            decide="require_human",
            route="approver",
            reason="Worth a look: {warning_text}.",
        ),
        Rule(
            "auto_ok",
            when=lambda c: bool(c.settings.auto_approve),
            decide="allow",
            reason="Auto-approval is on, and this invoice is small, clean and from a known vendor.",
        ),
    ],
    default=Decision(
        "require_human",
        route="approver",
        rule_id="default_human",
        reason="Auto-approval is off for this workspace.",
    ),
)


def decide(context: PolicyContext) -> Decision:
    return POLICY.evaluate(context)
