from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from portfolio_helpers import approval, configured_portfolio, later
from risk_helpers import EPIC, NOW
from trading_desk.portfolio import EndOfDataPolicy, IntrabarPolicy, MarketBar, MarketQuote
from trading_desk.portfolio.errors import PortfolioStateError
from trading_desk.portfolio.models import FillReason, PositionStatus


def open_portfolio(**configuration: object):  # type: ignore[no-untyped-def]
    portfolio = configured_portfolio(**configuration)
    decision, candidate, quote = approval(portfolio)
    result = portfolio.open_position(decision, candidate, quote, NOW)
    assert result.position is not None
    return portfolio, result.position, quote


def quote_at(price: str, minute: int = 1, *, status: str = "TRADEABLE") -> MarketQuote:
    return MarketQuote(
        snapshot_id=f"mark-{minute}",
        timestamp=later(minute),
        epic=EPIC,
        bid=Decimal(price),
        ask=Decimal(price) + Decimal("0.1"),
        market_status=status,
    )


def test_bid_side_mark_reconciles_unrealized_equity_exposure_mfe_and_mae() -> None:
    portfolio, position, _ = open_portfolio()
    state = portfolio.mark(quote_at("105"), later())
    expected = (Decimal("105") - position.entry_price) * position.quantity
    assert state.unrealized_pnl == expected
    assert state.equity == state.cash + state.unrealized_pnl
    assert state.gross_exposure == Decimal("105") * position.quantity
    marked = next(item for item in state.positions if item.status is PositionStatus.OPEN)
    assert marked.maximum_favorable_excursion == expected

    loss_state = portfolio.mark(quote_at("90", 2), later(2))
    marked = next(item for item in loss_state.positions if item.status is PositionStatus.OPEN)
    assert marked.maximum_adverse_excursion > Decimal("0")


@pytest.mark.parametrize(
    "quote",
    [
        MarketQuote(
            snapshot_id="bad",
            timestamp=later(),
            epic=EPIC,
            bid=None,
            ask=Decimal("1"),
            market_status="TRADEABLE",
        ),
        quote_at("100", status="CLOSED"),
        quote_at("100", 1).model_copy(update={"bid": Decimal("101"), "ask": Decimal("100")}),
    ],
)
def test_invalid_marks_fail_without_mutation(quote: MarketQuote) -> None:
    portfolio, _, _ = open_portfolio()
    before = portfolio.state
    with pytest.raises(PortfolioStateError):
        portfolio.mark(quote, later())
    assert portfolio.state == before


def test_stale_or_backward_mark_rejected() -> None:
    portfolio, _, _ = open_portfolio()
    with pytest.raises(PortfolioStateError):
        portfolio.mark(
            quote_at("100").model_copy(update={"timestamp": NOW - timedelta(seconds=1)}), later()
        )


@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        (IntrabarPolicy.ADVERSE_FIRST, FillReason.STOP),
        (IntrabarPolicy.FAVORABLE_FIRST, FillReason.TARGET),
        (IntrabarPolicy.REJECT_AMBIGUOUS, None),
    ],
)
def test_same_bar_ambiguity_is_deterministic(
    policy: IntrabarPolicy, expected: FillReason | None
) -> None:
    portfolio, position, _ = open_portfolio(intrabar_policy=policy)
    bar = MarketBar(
        snapshot_id="bar-1",
        timestamp=later(),
        epic=EPIC,
        low_bid=Decimal("94"),
        high_bid=Decimal("111"),
        close_bid=Decimal("100"),
        close_ask=Decimal("100.1"),
        market_status="TRADEABLE",
    )
    result = portfolio.process_bar(bar, later())
    if expected is None:
        assert result is None
        assert portfolio.state.open_position_count == 1
    else:
        assert result is not None and result.fill.fill_reason is expected
        assert result.position.position_id == position.position_id


@pytest.mark.parametrize(
    ("low", "high", "reason"),
    [("94", "109", FillReason.STOP), ("96", "111", FillReason.TARGET)],
)
def test_stop_and_target_use_bid_side(low: str, high: str, reason: FillReason) -> None:
    portfolio, _, _ = open_portfolio()
    bar = MarketBar(
        snapshot_id="bar",
        timestamp=later(),
        epic=EPIC,
        low_bid=Decimal(low),
        high_bid=Decimal(high),
        close_bid=Decimal("100"),
        close_ask=Decimal("100.1"),
        market_status="TRADEABLE",
    )
    result = portfolio.process_bar(bar, later())
    assert result is not None and result.trade.exit_reason is reason


def test_non_tradeable_or_missing_bar_never_fabricates_fill() -> None:
    portfolio, _, _ = open_portfolio()
    bar = MarketBar(
        snapshot_id="bar",
        timestamp=later(),
        epic=EPIC,
        low_bid=None,
        high_bid=Decimal("111"),
        close_bid=Decimal("100"),
        close_ask=Decimal("100.1"),
        market_status="CLOSED",
    )
    assert portfolio.process_bar(bar, later()) is None
    assert portfolio.state.open_position_count == 1


def test_same_timestamp_bar_cannot_trigger_pre_entry_exit() -> None:
    portfolio, _, _ = open_portfolio()
    bar = MarketBar(
        snapshot_id="entry-bar",
        timestamp=NOW,
        epic=EPIC,
        low_bid=Decimal("94"),
        high_bid=Decimal("111"),
        close_bid=Decimal("100"),
        close_ask=Decimal("100.1"),
        market_status="TRADEABLE",
    )
    with pytest.raises(PortfolioStateError):
        portfolio.process_bar(bar, NOW)
    assert portfolio.state.open_position_count == 1


def test_manual_exit_reconciles_commissions_cash_and_realized_pnl() -> None:
    portfolio, position, _ = open_portfolio()
    result = portfolio.close_position(position.position_id, quote_at("105"), later())
    expected_net = (
        result.trade.gross_pnl - result.trade.entry_commission - result.trade.exit_commission
    )
    assert result.trade.net_pnl == expected_net
    assert result.trade.slippage_cost > Decimal("0")
    assert portfolio.state.cash == portfolio.state.initial_cash + expected_net
    assert portfolio.state.realized_pnl == expected_net
    assert portfolio.state.open_position_count == 0


def test_funding_applies_once_per_utc_day() -> None:
    portfolio, position, _ = open_portfolio()
    day_two = NOW + timedelta(days=1)
    first = portfolio.apply_funding(position.position_id, day_two)
    event_count = len(portfolio.events)
    second = portfolio.apply_funding(position.position_id, day_two + timedelta(hours=1))
    assert second.cash == first.cash
    assert len(portfolio.events) == event_count
    funded = next(item for item in second.positions if item.status is PositionStatus.OPEN)
    assert funded.accrued_funding > Decimal("0")


def test_utc_day_rollover_resets_daily_only_and_preserves_losses() -> None:
    portfolio, position, _ = open_portfolio()
    close_time = NOW + timedelta(days=1)
    market = quote_at("90").model_copy(update={"timestamp": close_time})
    portfolio.close_position(position.position_id, market, close_time)
    assert portfolio.state.daily.trading_day == close_time.date().isoformat()
    assert portfolio.state.daily.realized_daily_pnl < Decimal("0")
    assert portfolio.state.daily.consecutive_losses == 1


def test_end_of_data_without_valid_quote_is_unresolved_not_realized() -> None:
    portfolio, position, _ = open_portfolio(end_of_data_policy=EndOfDataPolicy.UNRESOLVED)
    before_realized = portfolio.state.realized_pnl
    market = quote_at("100", status="CLOSED")
    assert portfolio.end_of_data(position.position_id, market, later()) is None
    unresolved = next(
        item for item in portfolio.state.positions if item.position_id == position.position_id
    )
    assert unresolved.status is PositionStatus.UNRESOLVED
    assert portfolio.state.realized_pnl == before_realized


def test_valid_forced_end_of_data_liquidation() -> None:
    portfolio, position, _ = open_portfolio(
        end_of_data_policy=EndOfDataPolicy.LIQUIDATE_IF_TRADEABLE
    )
    result = portfolio.end_of_data(position.position_id, quote_at("101"), later())
    assert result is not None
    assert result.trade.exit_reason is FillReason.FORCED_END_OF_DATA_LIQUIDATION


@pytest.mark.parametrize(
    ("reason", "event_type"),
    [
        (FillReason.STOP, "STOP_TRIGGERED"),
        (FillReason.TARGET, "TARGET_TRIGGERED"),
        (FillReason.SCHEDULED_EXIT, "SCHEDULED_EXIT"),
    ],
)
def test_exit_trigger_events_are_itemized(reason: FillReason, event_type: str) -> None:
    portfolio, position, _ = open_portfolio()
    portfolio.close_position(position.position_id, quote_at("100"), later(), reason=reason)
    assert event_type in {event.event_type.value for event in portfolio.events}
