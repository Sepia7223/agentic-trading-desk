from __future__ import annotations

from types import SimpleNamespace

import pytest
from tests.backtest_helpers import bars, configuration, dataset

from trading_desk.backtest.engine import BacktestEngine
from trading_desk.backtest.execution import end_of_data_fill, fill_pending_order
from trading_desk.backtest.models import FillPriceMode, FillSide, SimulatedOrder
from trading_desk.strategy.models import Regime, StrategyAction, StrategyVariant


def _entry(mode: FillPriceMode = FillPriceMode.NEXT_OPEN):
    values = bars(4)
    config = configuration(entry_fill_mode=mode)
    order = SimulatedOrder(
        signal_index=0,
        earliest_fill_index=1,
        side=FillSide.ENTRY,
        variant=StrategyVariant.BASELINE_ONLY,
        reason="end-of-data regression",
    )
    fill, _ = fill_pending_order(order, values[:2], config)
    assert fill is not None
    return values, config, fill


def _always_long(self: object, data: object, context: object) -> SimpleNamespace:
    return SimpleNamespace(
        action=StrategyAction.LONG_CANDIDATE,
        current_regime=Regime.BULL_LOW_VOL,
        configuration_fingerprint="f" * 64,
        rejection_reasons=(),
    )


def test_nontradeable_final_bar_uses_most_recent_eligible_tradeable_quote() -> None:
    values, config, entry = _entry()
    with_closed_final = (*values[:-1], values[-1].model_copy(update={"market_status": "CLOSED"}))

    fill = end_of_data_fill(entry, with_closed_final, 3, config)

    assert fill is not None
    assert fill.fill_index == 2
    assert fill.timestamp == values[2].timestamp


def test_no_tradeable_quote_after_close_entry_produces_no_fabricated_fill() -> None:
    values, config, entry = _entry(FillPriceMode.NEXT_CLOSE)
    closed = tuple(bar.model_copy(update={"market_status": "CLOSED"}) for bar in values)

    assert end_of_data_fill(entry, closed, entry.fill_index, config) is None


def test_engine_records_unresolved_position_without_realized_pnl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "trading_desk.strategy.pipeline.RegimeAwareStrategyPipeline.analyze_latest",
        _always_long,
    )
    data = dataset()
    validation_start = 220
    changed = list(data.bars)
    for index in range(validation_start, 235):
        changed[index] = changed[index].model_copy(update={"market_status": "CLOSED"})
    changed[validation_start] = data.bars[validation_start]
    changed[validation_start + 1] = data.bars[validation_start + 1]
    unresolved_data = data.model_copy(update={"bars": tuple(changed)})
    config = configuration(
        entry_fill_mode=FillPriceMode.NEXT_CLOSE,
        maximum_holding_bars=1000,
        protective_stop_bps=9000,
    )

    first = BacktestEngine(config).run(unresolved_data)
    second = BacktestEngine(config).run(unresolved_data)

    assert first == second
    assert first.trades == ()
    assert len(first.unresolved_positions) == 1
    assert first.forced_end_of_data_closures == 0
    assert first.metrics.trade_count == 0
    assert first.metrics.realized_net_pnl == 0
    assert first.metrics.net_return == 0
    assert first.metrics.unresolved_position_count == 1
