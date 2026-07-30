"""Donchian channel breakout trend-following evaluator (long-only, no fixed target)."""

from __future__ import annotations

from datetime import timedelta

from m12_helpers import evaluation, portfolio_data, updated_snapshot
from trading_desk.context.models import BreakoutState, TrendState, VolatilityState
from trading_desk.strategy.contracts import StrategyDecision
from trading_desk.strategy.donchian_breakout import DonchianBreakoutEvaluator
from trading_desk.strategy.invalidation import (
    InvalidationDecision,
    PositionEntryContext,
    evaluate_invalidation,
)
from trading_desk.strategy.portfolio_configuration import DonchianBreakoutConfiguration


def _bull_context():  # type: ignore[no-untyped-def]
    return updated_snapshot(
        trend_state=TrendState.STRONG_BULL_TREND,
        breakout_state=BreakoutState.CONFIRMED_UP,
        volatility_state=VolatilityState.EXPANSION,
    )


def test_channel_breakout_is_a_long_candidate_with_no_fixed_target() -> None:
    result = DonchianBreakoutEvaluator().evaluate(
        context=evaluation(portfolio_data("breakout"), _bull_context())
    )
    assert result.decision is StrategyDecision.CANDIDATE
    assert result.direction.value == "LONG"
    assert result.proposed_stop < result.entry_reference < result.proposed_target
    # Winners run: the backstop target is far (>= 5R), so it rarely caps the tail;
    # the trailing trend-break invalidation is the real exit.
    risk = result.entry_reference - result.proposed_stop
    assert (result.proposed_target - result.entry_reference) >= risk * 5
    assert result.gross_expected_value > 0
    assert "quantity" not in type(result).model_fields


def test_no_breakout_is_rejected() -> None:
    # The range fixture never closes above its prior channel high.
    result = DonchianBreakoutEvaluator().evaluate(
        context=evaluation(portfolio_data("range"), _bull_context())
    )
    assert result.decision is StrategyDecision.REJECT
    assert "NO_CHANNEL_BREAKOUT_ON_CLOSE" in result.rejection_reasons


def test_extreme_volatility_fails_closed() -> None:
    context = updated_snapshot(
        trend_state=TrendState.STRONG_BULL_TREND,
        breakout_state=BreakoutState.CONFIRMED_UP,
        volatility_state=VolatilityState.EXTREME,
    )
    result = DonchianBreakoutEvaluator().evaluate(
        context=evaluation(portfolio_data("breakout"), context)
    )
    assert result.decision is StrategyDecision.INELIGIBLE_REGIME


def test_large_breakout_buffer_rejects_a_marginal_break() -> None:
    from decimal import Decimal

    strict = DonchianBreakoutConfiguration(breakout_buffer_atr=Decimal("5"))
    result = DonchianBreakoutEvaluator(strict).evaluate(
        context=evaluation(portfolio_data("breakout"), _bull_context())
    )
    # Requiring the close to clear the channel by 5x ATR rejects a marginal break.
    assert result.decision is StrategyDecision.REJECT
    assert "NO_CHANNEL_BREAKOUT_ON_CLOSE" in result.rejection_reasons


def _entry() -> PositionEntryContext:
    return PositionEntryContext(
        strategy_id="donchian-breakout",
        strategy_version="1.0.0",
        maximum_holding_period=timedelta(days=60),
    )


def test_trend_break_trailing_exit_fires_when_uptrend_ends() -> None:
    holding = timedelta(days=2)
    holding_ctx = _bull_context()
    still_trending = evaluate_invalidation(_entry(), holding_ctx, holding)
    assert still_trending.decision is InvalidationDecision.HOLD

    broken = updated_snapshot(
        trend_state=TrendState.RANGE,
        breakout_state=BreakoutState.CONFIRMED_DOWN,
        volatility_state=VolatilityState.NORMAL,
    )
    exited = evaluate_invalidation(_entry(), broken, holding)
    assert exited.decision is InvalidationDecision.EXIT
    assert "TREND_STRUCTURE_BROKEN" in exited.reasons


def test_maximum_holding_period_forces_exit() -> None:
    exited = evaluate_invalidation(_entry(), _bull_context(), timedelta(days=90))
    assert exited.decision is InvalidationDecision.EXIT
    assert "MAXIMUM_HOLDING_PERIOD" in exited.reasons
