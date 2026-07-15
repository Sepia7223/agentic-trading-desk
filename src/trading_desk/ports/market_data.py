"""Market data provider protocol."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Protocol, TypedDict


class MarketSnapshot(TypedDict):
    symbol: str
    as_of: date
    close: list[Decimal]
    currency: str
    is_known: bool


class MarketDataProvider(Protocol):
    """Provides market data without exposing broker credentials to AI providers."""

    async def get_daily_closes(self, symbol: str, lookback_bars: int) -> MarketSnapshot:
        """Return daily closes old-to-new or an explicit unknown state."""
