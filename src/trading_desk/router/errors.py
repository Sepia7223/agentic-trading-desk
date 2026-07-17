"""Typed strategy-router failures."""


class StrategyRouterError(RuntimeError):
    """Base deterministic router error."""


class DuplicateStrategyError(StrategyRouterError):
    """Raised when a registry contains duplicate strategy identifiers."""
