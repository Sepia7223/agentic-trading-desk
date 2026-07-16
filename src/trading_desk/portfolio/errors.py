"""Typed fail-closed errors for the paper portfolio."""


class PortfolioError(Exception):
    """Base class for safe local portfolio failures."""


class IntentRejectedError(PortfolioError):
    """Raised when an approval cannot be consumed safely."""


class PortfolioStateError(PortfolioError):
    """Raised when state or lifecycle invariants are violated."""


class LedgerValidationError(PortfolioError):
    """Raised when an append-only event chain cannot be trusted."""
