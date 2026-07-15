from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from trading_desk.backtest.metrics import calculate_drawdowns, calculate_metrics
from trading_desk.backtest.models import EquityPoint
from trading_desk.strategy.models import StrategyVariant


def _equity(values: tuple[float, ...]) -> tuple[EquityPoint, ...]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return tuple(
        EquityPoint(
            index=index,
            timestamp=start + timedelta(days=index),
            equity=value,
            cash=value,
            unrealized_pnl=0.0,
            gross_exposure=0.0,
            accumulated_costs=0.0,
        )
        for index, value in enumerate(values)
    )


def test_drawdown_and_duration_are_calculated_from_equity() -> None:
    equity = _equity((100.0, 120.0, 90.0, 96.0, 130.0))
    drawdowns = calculate_drawdowns(equity)
    metrics = calculate_metrics(StrategyVariant.BASELINE_ONLY, 100.0, equity, (), 252.0)

    assert drawdowns[2].drawdown == pytest.approx(0.25)
    assert metrics.maximum_drawdown == pytest.approx(0.25)
    assert metrics.drawdown_duration_bars == 2


def test_zero_volatility_and_no_trade_metrics_are_typed_unavailable() -> None:
    equity = _equity((100.0, 100.0, 100.0))
    metrics = calculate_metrics(StrategyVariant.BASELINE_ONLY, 100.0, equity, (), 252.0)

    assert metrics.sharpe_ratio.available is False
    assert metrics.sortino_ratio.available is False
    assert metrics.profit_factor.available is False
    assert metrics.win_rate.available is False


def test_annualization_uses_explicit_resolution_factor() -> None:
    equity = _equity((100.0, 101.0, 102.0, 103.0))
    daily = calculate_metrics(StrategyVariant.BASELINE_ONLY, 100.0, equity, (), 252.0)
    hourly = calculate_metrics(StrategyVariant.BASELINE_ONLY, 100.0, equity, (), 6048.0)

    assert daily.annualized_return.available
    assert hourly.annualized_return.available
    assert daily.annualized_return.value != hourly.annualized_return.value
