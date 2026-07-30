from __future__ import annotations

from types import SimpleNamespace

import pytest
from tests.backtest_helpers import configuration, dataset

from trading_desk.backtest.engine import BacktestEngine
from trading_desk.backtest.models import ExitReason
from trading_desk.backtest.portfolio import BacktestPortfolio
from trading_desk.strategy.models import Regime, StrategyAction, StrategyVariant


def _always_long(self: object, data: object, context: object) -> SimpleNamespace:
    return SimpleNamespace(
        action=StrategyAction.LONG_CANDIDATE,
        current_regime=Regime.BULL_LOW_VOL,
        configuration_fingerprint="f" * 64,
        rejection_reasons=(),
    )


def test_engine_enters_next_bar_rejects_duplicates_and_forces_final_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "trading_desk.strategy.pipeline.RegimeAwareStrategyPipeline.analyze_latest",
        _always_long,
    )
    config = configuration(maximum_holding_bars=1000, protective_stop_bps=9000)
    run = BacktestEngine(config).run(dataset())

    assert run.fills
    assert run.fills[0].fill_index > run.fills[0].signal_index
    assert run.fills[0].side.value == "ENTRY"
    assert run.trades[-1].exit_reason is ExitReason.FORCED_END_OF_DATA_LIQUIDATION
    assert run.forced_end_of_data_closures == 1
    assert run.unresolved_positions == ()
    assert len([fill for fill in run.fills if fill.side.value == "ENTRY"]) == 1
    assert run.metrics.trade_count == 1
    assert run.metrics.turnover > 0
    assert run.metrics.exposure_time > 0
    assert run.metrics.gross_return != run.metrics.net_return


def test_duplicate_portfolio_entry_is_rejected() -> None:
    portfolio = BacktestPortfolio.create(1000.0)
    data = dataset().bars
    config = configuration()
    from trading_desk.backtest.execution import fill_pending_order
    from trading_desk.backtest.models import FillSide, SimulatedOrder

    order = SimulatedOrder(
        signal_index=0,
        earliest_fill_index=1,
        side=FillSide.ENTRY,
        variant=StrategyVariant.BASELINE_ONLY,
        reason="test",
    )
    fill, _ = fill_pending_order(order, data, config)
    assert fill is not None
    portfolio.open(fill, Regime.UNKNOWN)
    with pytest.raises(ValueError, match="duplicate"):
        portfolio.open(fill, Regime.UNKNOWN)


def test_backtest_run_contains_cash_and_executable_buy_hold_benchmarks() -> None:
    run = BacktestEngine(configuration()).run(dataset())
    names = {benchmark.name.value for benchmark in run.benchmarks}
    assert names == {"CASH", "BUY_AND_HOLD"}
    buy_hold = next(item for item in run.benchmarks if item.name.value == "BUY_AND_HOLD")
    assert buy_hold.total_cost >= 0


def test_strategy_rejections_are_aggregated() -> None:
    run = BacktestEngine(configuration()).run(dataset())
    assert all(item.count > 0 for item in run.rejections)
    assert tuple(item.reason for item in run.rejections) == tuple(
        sorted(item.reason for item in run.rejections)
    )


def test_profit_target_logic_is_invoked_by_the_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Milestone 12 correctness requirement: the configured profit target must
    be exercised by the actual engine path, not merely defined."""

    monkeypatch.setattr(
        "trading_desk.strategy.pipeline.RegimeAwareStrategyPipeline.analyze_latest",
        _always_long,
    )
    config = configuration(
        maximum_holding_bars=1000, protective_stop_bps=9000, profit_target_bps=15.0
    )
    run = BacktestEngine(config).run(dataset())
    assert any(trade.exit_reason is ExitReason.PROFIT_TARGET for trade in run.trades)


def test_intrabar_ambiguity_resolution_is_invoked_by_the_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When one bar breaches both stop and target, the configured ambiguity
    policy decides the outcome inside the real engine loop."""

    monkeypatch.setattr(
        "trading_desk.strategy.pipeline.RegimeAwareStrategyPipeline.analyze_latest",
        _always_long,
    )
    adverse = configuration(
        maximum_holding_bars=1000, protective_stop_bps=5.0, profit_target_bps=5.0
    )
    adverse_run = BacktestEngine(adverse).run(dataset())
    assert adverse_run.trades[0].exit_reason is ExitReason.PROTECTIVE_STOP

    from trading_desk.backtest.models import IntrabarAmbiguityPolicy

    favorable = configuration(
        maximum_holding_bars=1000,
        protective_stop_bps=5.0,
        profit_target_bps=5.0,
        ambiguity_policy=IntrabarAmbiguityPolicy.FAVORABLE_FIRST,
    )
    favorable_run = BacktestEngine(favorable).run(dataset())
    assert favorable_run.trades[0].exit_reason is ExitReason.PROFIT_TARGET
