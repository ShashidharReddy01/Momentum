"""Errors raised by the AI layer; rendered as problem+json like every other DomainError."""

from __future__ import annotations

from momentum.ai.types import FailureKind
from momentum.core.errors import DomainError


class AIUnavailable(DomainError):
    """The gateway could not produce a result (after retries, or on a non-retryable error).

    Callers degrade gracefully: the non-AI path keeps working (Phase 3 exit criterion)."""

    status, code, title = 503, "ai_unavailable", "AI is temporarily unavailable"

    def __init__(self, *, reason: str, internal_detail: str = "") -> None:
        # ``reason`` (a failure kind) reaches the client; ``internal_detail`` (a gateway error
        # excerpt, which can echo request content) stays server-side, e.g. for llm-check.
        super().__init__(reason=reason)
        self.reason = reason
        self.internal_detail = internal_detail


class AIDisabled(DomainError):
    status, code, title = 503, "ai_disabled", "AI is turned off for this workspace"


class BudgetExceeded(DomainError):
    status, code, title = 429, "ai_budget_exceeded", "The monthly AI budget has been used up"


class TransportError(Exception):
    """Raised by transports; the gateway decides whether to retry based on ``kind``."""

    def __init__(self, kind: FailureKind, message: str, *, retry_after: float | None = None):
        super().__init__(message)
        self.kind: FailureKind = kind
        self.retry_after = retry_after
