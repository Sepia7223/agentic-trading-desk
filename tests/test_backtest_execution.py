from __future__ import annotations

import pytest
from tests.backtest_helpers import bars, configuration

from trading_desk.backtest.execution import (
    create_trade,
    fill_pending_order,
    protective_stop_fill,
    resolve_intrabar_ambiguity,
)
from trading_desk.backtest.models import (
    ExitReason,
    FillPriceMode,
    FillSide,
    IntrabarAmbiguityPolicy,
    SimulatedOrder,
)
from trading_desk.strategy.models import Regime, StrategyVariant


def _order(side: FillSide = FillSide.ENTRY) -> SimulatedOrder:
    return SimulatedOrder(
        signal_index=0,
        earliest_fill_index=1,
        side=side,
        variant=StrategyVariant.BASELINE_ONLY,
        reason="test",
    )


def test_long_entry_uses_next_ask_and_adverse_slippage() -> None:
    values = bars(3)
    config = configuration(slippage_bps=2.0)
    fill, rejection = fill_pending_order(_order(), values, config)

    assert rejection is None and fill is not None
    assert fill.fill_index == 1
    assert fill.fill_index > fill.signal_index
    assert fill.quote_price == values[1].open_ask
    assert fill.fill_price == pytest.approx(values[1].open_ask * 1.0002)


def test_long_exit_uses_bid_and_slippage_is_adverse() -> None:
    values = bars(3)
    config = configuration(slippage_bps=2.0)
    fill, _ = fill_pending_order(_order(FillSide.EXIT), values, config)
    assert fill is not None
    assert fill.quote_price == values[1].open_bid
    assert fill.fill_price == pytest.approx(values[1].open_bid * 0.9998)


def test_research_next_close_mode_still_uses_a_future_bar_quote() -> None:
    values = bars(3)
    config = configuration(entry_fill_mode=FillPriceMode.NEXT_CLOSE)
    fill, _ = fill_pending_order(_order(), values, config)
    assert fill is not None
    assert fill.fill_index == 1
    assert fill.quote_price == values[1].close_ask


def test_missing_or_nontradeable_next_bar_rejects_fill() -> None:
    config = configuration(maximum_execution_delay_bars=1)
    missing, reason = fill_pending_order(_order(), bars(1), config)
    assert missing is None and reason == "NEXT_BAR_UNAVAILABLE"
    values = list(bars(2))
    values[1] = values[1].model_copy(update={"market_status": "CLOSED"})
    closed, reason = fill_pending_order(_order(), tuple(values), config)
    assert closed is None and "NON_TRADEABLE" in str(reason)


def test_costs_are_itemized_without_double_counting_spread() -> None:
    values = bars(3)
    config = configuration(
        slippage_bps=1.0,
        fixed_commission_per_side=2.0,
        proportional_commission_bps=1.0,
        overnight_funding_bps_per_day=1.0,
    )
    entry, _ = fill_pending_order(_order(), values, config)
    exit_fill, _ = fill_pending_order(_order(FillSide.EXIT), values, config)
    assert entry is not None and exit_fill is not None
    exit_fill = exit_fill.model_copy(
        update={
            "fill_index": 2,
            "timestamp": values[2].timestamp,
            "quote_price": values[2].open_bid,
        }
    )
    trade = create_trade(
        values[0].epic,
        Regime.UNKNOWN,
        entry,
        exit_fill,
        ExitReason.MAXIMUM_HOLDING_PERIOD,
        config,
    )
    assert trade.total_cost == pytest.approx(
        trade.spread_impact
        + trade.slippage_cost
        + trade.commission_cost
        + trade.funding_cost
        + trade.guaranteed_stop_premium
    )
    assert trade.net_pnl == pytest.approx(trade.gross_pnl - trade.total_cost)
    assert trade.funding_cost > 0


def test_protective_stop_uses_conservative_bid_side_fill() -> None:
    values = list(bars(3))
    config = configuration(protective_stop_bps=10.0, slippage_bps=1.0)
    entry, _ = fill_pending_order(_order(), tuple(values), config)
    assert entry is not None
    stop = protective_stop_fill(entry, values[2], 2, config)
    assert stop is not None
    assert stop.fill_price < stop.quote_price
    assert stop.side is FillSide.EXIT


def test_intrabar_ambiguity_defaults_to_adverse_first() -> None:
    result = resolve_intrabar_ambiguity(
        low_bid=90,
        high_bid=110,
        stop_level=95,
        target_level=105,
        policy=IntrabarAmbiguityPolicy.ADVERSE_FIRST,
    )
    assert result == "STOP"
