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


class Broker(Protocol):
    """Read-only broker boundary for Milestone 1."""

    async def get_portfolio_state(self) -> PortfolioState:
        """Return known account state or an explicit unknown state."""
