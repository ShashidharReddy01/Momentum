"""Phase 7.6 S76-06 (spec §8.4): the policy engine (``momentum.sdk.policy``).

A pack's policy is a list of rules evaluated **in order, deterministically: no model, no I/O**.
The first rule that fires decides; **every** rule's result (fired or not) is kept in the trace,
so "why?" is always answerable. Rules are code (reviewed); thresholds are settings.

Decisions: ``allow`` · ``require_human`` · ``hold`` · ``deny``. A rule that raises is never
silently skipped: the outcome falls back to ``require_human`` with the error in the trace.

    POLICY = Policy("bernie.invoice", rules=[
        Rule("duplicate", when=lambda c: c.check_failed("duplicate"), decide="hold",
             route="requester", reason="Looks like a duplicate of {duplicate_of}."),
        Rule("material", when=lambda c: c.amount >= c.settings.materiality(c.currency),
             decide="require_human", route="approver", reason="{amount} {currency} is material."),
    ], default=Decision("require_human", route="approver", rule_id="default_human",
                        reason="Auto-approval is off for this workspace."))
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

Verdict = Literal["allow", "require_human", "hold", "deny"]
VERDICTS = ("allow", "require_human", "hold", "deny")


class _Fields(dict[str, Any]):
    """Formats a reason from the context's attributes; a missing one shows as ``?``."""

    def __init__(self, context: Any) -> None:
        super().__init__()
        self._context = context

    def __missing__(self, key: str) -> Any:
        if isinstance(self._context, dict):
            return self._context.get(key, "?")
        return getattr(self._context, key, "?")


def _format(template: str, context: Any) -> str:
    try:
        return template.format_map(_Fields(context))
    except (ValueError, AttributeError, IndexError):
        return template


@dataclass(frozen=True)
class Decision:
    decision: Verdict
    route: str | None = None
    rule_id: str | None = None
    reason: str = ""
    evaluated: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if self.decision not in VERDICTS:
            raise ValueError(f"A decision is one of {', '.join(VERDICTS)}")

    def as_dict(self) -> dict[str, Any]:
        """What a record's ``decision`` column holds."""
        return {
            "decision": self.decision,
            "route": self.route,
            "rule_id": self.rule_id,
            "reason": self.reason,
            "evaluated": list(self.evaluated),
        }


@dataclass(frozen=True)
class Rule:
    id: str
    when: Callable[[Any], Any]
    decide: Verdict
    reason: str = ""
    route: str | None = None

    def __post_init__(self) -> None:
        if self.decide not in VERDICTS:
            raise ValueError(f"Rule {self.id}: a decision is one of {', '.join(VERDICTS)}")


@dataclass(frozen=True)
class Policy:
    key: str
    rules: list[Rule] = field(default_factory=list)
    default: Decision = field(
        default_factory=lambda: Decision("require_human", rule_id="default", reason="No rule fired")
    )

    def __post_init__(self) -> None:
        ids = [r.id for r in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Policy {self.key}: rule ids must be unique")

    def evaluate(self, context: Any) -> Decision:
        evaluated: list[dict[str, Any]] = []
        chosen: Decision | None = None
        for rule in self.rules:
            try:
                fired = bool(rule.when(context))
            except Exception as e:  # never a silent skip: a person looks instead
                evaluated.append({"rule_id": rule.id, "fired": None, "error": type(e).__name__})
                if chosen is None:
                    chosen = Decision(
                        "require_human",
                        route=rule.route or self.default.route,
                        rule_id=rule.id,
                        reason=f"The {rule.id} check couldn't run, so a person decides",
                    )
                continue
            evaluated.append({"rule_id": rule.id, "fired": fired})
            if fired and chosen is None:
                chosen = Decision(
                    rule.decide,
                    route=rule.route,
                    rule_id=rule.id,
                    reason=_format(rule.reason, context),
                )
        base = chosen or Decision(
            self.default.decision,
            route=self.default.route,
            rule_id=self.default.rule_id,
            reason=_format(self.default.reason, context),
        )
        return Decision(
            base.decision,
            route=base.route,
            rule_id=base.rule_id,
            reason=base.reason,
            evaluated=tuple(evaluated),
        )
