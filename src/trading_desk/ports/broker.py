"""Broker protocol.

Concrete IG clients are intentionally out of scope for Milestone 1.
"""

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


class OrderPreview(TypedDict):
    symbol: str
    side: str
    quantity: Decimal
    notional: Decimal
    accepted_by_risk: bool
    reason: str


class Broker(Protocol):
    """Read-only broker boundary for Milestone 1."""

    async def get_portfolio_state(self) -> PortfolioState:
        """Return known account state or an explicit unknown state."""

    async def preview_order(self, symbol: str, side: str, quantity: Decimal) -> OrderPreview:
        """Preview only. Implementations must not place orders."""
