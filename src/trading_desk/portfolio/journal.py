"""Journal-compatible output boundary without storage or AI coupling."""

from __future__ import annotations

from typing import Protocol

from trading_desk.portfolio.models import ClosedTradeRecord, PortfolioEvent, PortfolioState


class PortfolioJournal(Protocol):
    def record_event(self, event: PortfolioEvent) -> None: ...

    def record_trade(self, trade: ClosedTradeRecord) -> None: ...

    def record_snapshot(self, state: PortfolioState) -> None: ...


class NullPortfolioJournal:
    def record_event(self, event: PortfolioEvent) -> None:
        del event

    def record_trade(self, trade: ClosedTradeRecord) -> None:
        del trade

    def record_snapshot(self, state: PortfolioState) -> None:
        del state
