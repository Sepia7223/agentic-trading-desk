"""Provider-neutral read-only broker protocol."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol, TypedDict


class PortfolioState(TypedDict):
    account_id: str
    currency: str
    cash_available: Decimal
    market_value: Decimal
    open_position_count: int
    is_known: bool


class Broker(Protocol):
    """Minimal read-only broker boundary without order authority."""

    async def get_portfolio_state(self) -> PortfolioState:
        """Return known account state or an explicit unknown state."""
