from __future__ import annotations

from tests.backtest_helpers import bars, configuration

from trading_desk.backtest.execution import (
    fill_pending_order,
    protective_stop_fill,
    resolve_intrabar_ambiguity,
)
from trading_desk.backtest.models import (
    FillPriceMode,
    FillSide,
    IntrabarAmbiguityPolicy,
    SimulatedOrder,
)
from trading_desk.strategy.models import StrategyVariant


def _entry(mode: FillPriceMode):
    values = bars(4)
    config = configuration(
        entry_fill_mode=mode,
        protective_stop_bps=10.0,
        slippage_bps=0.0,
    )
    order = SimulatedOrder(
        signal_index=0,
        earliest_fill_index=1,
        side=FillSide.ENTRY,
        variant=StrategyVariant.BASELINE_ONLY,
        reason="chronology regression",
    )
    fill, rejection = fill_pending_order(order, values[:2], config)
    assert fill is not None and rejection is None
    return values, config, fill


def test_next_close_entry_ignores_entry_bar_low_then_starts_stop_on_following_bar() -> None:
    values, config, entry = _entry(FillPriceMode.NEXT_CLOSE)

    assert protective_stop_fill(entry, values[1], 1, config) is None
    assert protective_stop_fill(entry, values[2], 2, config) is not None
    assert entry.fill_index == 1
    assert entry.commission_cost >= 0


def test_next_close_entry_ignores_entry_bar_high_then_starts_target_on_following_bar() -> None:
    values, _, entry = _entry(FillPriceMode.NEXT_CLOSE)
    stop = entry.fill_price * 0.999
    target = entry.fill_price * 1.001

    entry_bar = resolve_intrabar_ambiguity(
        values[1].low_bid,
        values[1].high_bid,
        stop,
        target,
        IntrabarAmbiguityPolicy.ADVERSE_FIRST,
        entry_fill=entry,
        bar_index=1,
    )
    following_bar = resolve_intrabar_ambiguity(
        values[2].low_bid,
        values[2].high_bid,
        stop,
        target,
        IntrabarAmbiguityPolicy.ADVERSE_FIRST,
        entry_fill=entry,
        bar_index=2,
    )

    assert entry_bar is None
    assert following_bar == "STOP"


def test_next_open_intrabar_stop_behavior_remains_active_on_entry_bar() -> None:
    values, config, entry = _entry(FillPriceMode.NEXT_OPEN)

    assert protective_stop_fill(entry, values[1], 1, config) is not None


def test_close_entry_chronology_is_deterministic() -> None:
    first = _entry(FillPriceMode.NEXT_CLOSE)
    second = _entry(FillPriceMode.NEXT_CLOSE)

    assert first[2] == second[2]
    assert protective_stop_fill(first[2], first[0][1], 1, first[1]) is None
    assert protective_stop_fill(second[2], second[0][1], 1, second[1]) is None
