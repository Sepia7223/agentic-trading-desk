"""Safe exception hierarchy for the read-only IG adapter."""

from __future__ import annotations

import re

_SAFE_FIELD_PATH = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z][A-Za-z0-9]*)*\Z")
_SAFE_VALIDATION_REASONS = {
    "invalid time-of-day",
    "missing or invalid object",
    "missing required value",
    "invalid value",
}


class IGError(Exception):
    """Base class for errors that expose safe diagnostics only."""


class IGConfigurationError(IGError):
    """The local IG configuration is missing or unsafe."""


class IGSessionMissingError(IGError):
    """An authenticated operation was requested without a session."""


class ReadOnlyPolicyViolation(IGError):
    """A method or path is outside the read-only allowlist."""


class IGAPIError(IGError):
    """An IG response reported an API error using safe metadata."""

    def __init__(
        self,
        message: str,
        *,
        operation: str,
        http_status: int | None = None,
        error_code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        self.operation = operation
        self.http_status = http_status
        self.error_code = error_code
        self.request_id = request_id
        details = [f"operation={operation}"]
        if http_status is not None:
            details.append(f"status={http_status}")
        if error_code:
            details.append(f"error_code={error_code}")
        if request_id:
            details.append(f"request_id={request_id}")
        super().__init__(f"{message} ({', '.join(details)})")


class IGAuthenticationError(IGAPIError):
    """Authentication failed or the login response was unsafe."""


class IGAuthorizationError(IGAPIError):
    """The authenticated session is not authorized for an operation."""


class IGRateLimitError(IGAuthorizationError):
    """An IG API allowance was exhausted."""


class IGResponseValidationError(IGAPIError):
    """An IG response could not be normalized safely."""

    def __init__(
        self,
        message: str,
        *,
        operation: str,
        http_status: int | None = None,
        error_code: str | None = None,
        request_id: str | None = None,
        field: str | None = None,
        reason: str | None = None,
    ) -> None:
        safe_message = message
        if field is not None:
            safe_field = field if _SAFE_FIELD_PATH.fullmatch(field) else "unknown"
            safe_reason = reason if reason in _SAFE_VALIDATION_REASONS else "invalid value"
            safe_message = f"{message}; field={safe_field}; reason={safe_reason}"
        super().__init__(
            safe_message,
            operation=operation,
            http_status=http_status,
            error_code=error_code,
            request_id=request_id,
        )


class IGOAuthResponseValidationError(IGResponseValidationError):
    """An OAuth session response was missing required safe fields."""


class IGOAuthTokenExpiredError(IGAuthenticationError):
    """The in-memory OAuth access token is no longer safe to use."""
