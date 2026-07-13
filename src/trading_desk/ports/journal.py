"""Trade journal protocol."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol, TypedDict


class JournalEntry(TypedDict):
    timestamp: datetime
    symbol: str
    action: str
    deterministic_decision: str
    model_summary: str | None
    risk_accepted: bool
    notional: Decimal | None


class TradeJournal(Protocol):
    """Persistent journal boundary."""

    async def record(self, entry: JournalEntry) -> None:
        """Persist an analysis or trading decision record."""

    async def list_recent(self, limit: int = 50) -> list[JournalEntry]:
        """Return recent journal entries."""
