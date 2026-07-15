"""Deterministic performance and drawdown calculations."""

from __future__ import annotations

import math

import numpy as np

from trading_desk.backtest.models import (
    BacktestTrade,
    DrawdownPoint,
    EquityPoint,
    MetricValue,
    PerformanceMetrics,
)
from trading_desk.strategy.models import StrategyVariant


def calculate_drawdowns(equity: tuple[EquityPoint, ...]) -> tuple[DrawdownPoint, ...]:
    peak = -math.inf
    points: list[DrawdownPoint] = []
    for point in equity:
        peak = max(peak, point.equity)
        drawdown = 0.0 if peak <= 0 else max((peak - point.equity) / peak, 0.0)
        points.append(
            DrawdownPoint(
                index=point.index,
                timestamp=point.timestamp,
                equity=point.equity,
                peak_equity=peak,
                drawdown=drawdown,
            )
        )
    return tuple(points)


def calculate_metrics(
    variant: StrategyVariant,
    initial_capital: float,
    equity: tuple[EquityPoint, ...],
    trades: tuple[BacktestTrade, ...],
    annualization_factor: float,
    *,
    unresolved_position_count: int = 0,
) -> PerformanceMetrics:
    ending = equity[-1].equity if equity else initial_capital
    gross_pnl = sum(trade.gross_pnl for trade in trades)
    net_pnl = sum(trade.net_pnl for trade in trades)
    drawdowns = calculate_drawdowns(equity)
    maximum_drawdown = max((point.drawdown for point in drawdowns), default=0.0)
    current_duration = max_duration = 0
    for point in drawdowns:
        current_duration = current_duration + 1 if point.drawdown > 0 else 0
        max_duration = max(max_duration, current_duration)

    net_wins = [trade.net_pnl for trade in trades if trade.net_pnl > 0]
    net_losses = [trade.net_pnl for trade in trades if trade.net_pnl < 0]
    gross_wins = [trade.gross_pnl for trade in trades if trade.gross_pnl > 0]
    gross_losses = [trade.gross_pnl for trade in trades if trade.gross_pnl < 0]
    returns = np.asarray(
        [
            current.equity / previous.equity - 1.0
            for previous, current in zip(equity, equity[1:], strict=False)
            if previous.equity > 0
        ],
        dtype=np.float64,
    )
    volatility = float(np.std(returns, ddof=1)) if len(returns) >= 2 else None
    mean_return = float(np.mean(returns)) if len(returns) else None
    downside = returns[returns < 0]
    downside_deviation = float(np.std(downside, ddof=1)) if len(downside) >= 2 else None
    years = len(returns) / annualization_factor if annualization_factor > 0 else 0
    annualized = (
        (ending / initial_capital) ** (1 / years) - 1
        if years > 0 and ending > 0 and len(returns) >= 2
        else None
    )
    sharpe = (
        mean_return / volatility * math.sqrt(annualization_factor)
        if mean_return is not None and volatility is not None and volatility > 0
        else None
    )
    sortino = (
        mean_return / downside_deviation * math.sqrt(annualization_factor)
        if mean_return is not None and downside_deviation is not None and downside_deviation > 0
        else None
    )
    calmar = (
        annualized / maximum_drawdown if annualized is not None and maximum_drawdown > 0 else None
    )
    total_gains = sum(net_wins)
    total_losses = abs(sum(net_losses))
    payoff = (
        (sum(net_wins) / len(net_wins)) / abs(sum(net_losses) / len(net_losses))
        if net_wins and net_losses
        else None
    )
    exposure_bars = sum(point.gross_exposure > 0 for point in equity)
    turnover = sum(
        (trade.entry_fill.fill_price + trade.exit_fill.fill_price) * trade.entry_fill.quantity
        for trade in trades
    )
    return PerformanceMetrics(
        variant=variant,
        starting_equity=initial_capital,
        ending_equity=ending,
        gross_return=gross_pnl / initial_capital,
        net_return=net_pnl / initial_capital,
        realized_net_pnl=net_pnl,
        unresolved_position_count=unresolved_position_count,
        annualized_return=_metric(annualized, "insufficient observations for annualization"),
        peak_equity=max((point.equity for point in equity), default=initial_capital),
        maximum_drawdown=maximum_drawdown,
        drawdown_duration_bars=max_duration,
        trade_count=len(trades),
        winning_trades=len(net_wins),
        losing_trades=len(net_losses),
        win_rate=_metric(len(net_wins) / len(trades) if trades else None, "no completed trades"),
        average_gross_win=_average(gross_wins, "no gross winning trades"),
        average_gross_loss=_average(gross_losses, "no gross losing trades"),
        average_net_win=_average(net_wins, "no net winning trades"),
        average_net_loss=_average(net_losses, "no net losing trades"),
        largest_win=_metric(max(net_wins) if net_wins else None, "no net winning trades"),
        largest_loss=_metric(min(net_losses) if net_losses else None, "no net losing trades"),
        expectancy=_average([trade.net_pnl for trade in trades], "no completed trades"),
        payoff_ratio=_metric(payoff, "both winning and losing trades are required"),
        profit_factor=_metric(
            total_gains / total_losses if total_losses > 0 else None, "no losses"
        ),
        average_holding_period=_average(
            [float(trade.holding_bars) for trade in trades], "no completed trades"
        ),
        maximum_holding_period=max((trade.holding_bars for trade in trades), default=0),
        turnover=turnover,
        exposure_time=exposure_bars / len(equity) if equity else 0.0,
        sharpe_ratio=_metric(sharpe, "zero or insufficient return volatility"),
        sortino_ratio=_metric(sortino, "zero or insufficient downside deviation"),
        calmar_ratio=_metric(calmar, "annualized return or drawdown unavailable"),
        downside_deviation=_metric(downside_deviation, "insufficient downside observations"),
        volatility=_metric(volatility, "insufficient return observations"),
    )


def _average(values: list[float], reason: str) -> MetricValue:
    return _metric(sum(values) / len(values) if values else None, reason)


def _metric(value: float | None, reason: str) -> MetricValue:
    if value is None or not math.isfinite(value):
        return MetricValue(available=False, reason=reason)
    return MetricValue(available=True, value=value)
