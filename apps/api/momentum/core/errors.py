"""Domain errors, rendered as RFC 9457 problem+json by the app's exception handlers."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    status: int = 400
    code: str = "bad_request"
    title: str = "Bad request"

    def __init__(self, detail: str | None = None, *, code: str | None = None, **extra: Any) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        if code is not None:
            self.code = code
        self.extra = extra


class ValidationFailed(DomainError):
    status, code, title = 422, "validation_failed", "Validation failed"


class NotFound(DomainError):
    status, code, title = 404, "not_found", "Not found"


class Forbidden(DomainError):
    status, code, title = 403, "forbidden", "Forbidden"


class Conflict(DomainError):
    status, code, title = 409, "conflict", "Conflict"


class VersionConflict(Conflict):
    code, title = "version_conflict", "Version conflict"


class Unauthenticated(DomainError):
    status, code, title = 401, "unauthenticated", "Authentication required"


class NotInvited(DomainError):
    status, code, title = 403, "not_invited", "You do not have access to this workspace"


class AccountDisabled(DomainError):
    status, code, title = 403, "account_disabled", "This account is disabled"


class CsrfFailed(DomainError):
    status, code, title = 403, "csrf_failed", "Missing CSRF header"
