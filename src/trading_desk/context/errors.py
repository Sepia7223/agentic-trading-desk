"""Typed context classification failures."""


class MarketContextError(Exception):
    """Base context failure."""


class MarketContextConfigurationError(MarketContextError):
    """Session or classification policy is invalid."""


class MarketContextDataError(MarketContextError):
    """Required cutoff-safe market data is unavailable."""
