"""Typed errors for the advisory AI boundary."""


class AIAnalystError(Exception):
    """Base error for safe advisory-analysis failures."""


class AISanitizationError(AIAnalystError):
    """Unsafe or malformed input was rejected before provider invocation."""


class AIPolicyViolation(AIAnalystError):
    """A request or response attempted to exceed advisory authority."""


class AIProviderError(AIAnalystError):
    """The configured provider failed without affecting deterministic systems."""
