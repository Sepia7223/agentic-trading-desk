"""Simple one-position long-only simulated portfolio accounting."""

from __future__ import annotations

from dataclasses import dataclass

from trading_desk.backtest.models import BacktestBar, BacktestTrade, EquityPoint, SimulatedFill
from trading_desk.strategy.models import Regime


@dataclass(slots=True)
class OpenSimulatedPosition:
    entry_fill: SimulatedFill
    signal_regime: Regime
    entry_cost: float


@dataclass(slots=True)
class BacktestPortfolio:
    initial_capital: float
    cash: float
    realized_pnl: float = 0.0
    accumulated_costs: float = 0.0
    position: OpenSimulatedPosition | None = None

    @classmethod
    def create(cls, initial_capital: float) -> BacktestPortfolio:
        return cls(initial_capital=initial_capital, cash=initial_capital)

    def open(self, fill: SimulatedFill, regime: Regime) -> None:
        if self.position is not None:
            raise ValueError("duplicate simulated entry while already holding")
        spread_cost = max(fill.quote_price - fill.midpoint_price, 0.0) * fill.quantity
        entry_cost = spread_cost + fill.slippage_cost + fill.commission_cost
        self.position = OpenSimulatedPosition(
            entry_fill=fill,
            signal_regime=regime,
            entry_cost=entry_cost,
        )
        self.accumulated_costs += entry_cost

    def close(self, trade: BacktestTrade) -> None:
        if self.position is None:
            raise ValueError("cannot close a missing simulated position")
        self.realized_pnl += trade.net_pnl
        self.cash = self.initial_capital + self.realized_pnl
        self.accumulated_costs += trade.total_cost - self.position.entry_cost
        self.position = None

    def equity_point(self, bar: BacktestBar, index: int) -> EquityPoint:
        unrealized = 0.0
        exposure = 0.0
        if self.position is not None:
            fill = self.position.entry_fill
            unrealized = (bar.close_bid - fill.fill_price) * fill.quantity - fill.commission_cost
            exposure = bar.close_bid * fill.quantity
        return EquityPoint(
            index=index,
            timestamp=bar.timestamp,
            equity=self.cash + unrealized,
            cash=self.cash,
            unrealized_pnl=unrealized,
            gross_exposure=exposure,
            accumulated_costs=self.accumulated_costs,
        )
