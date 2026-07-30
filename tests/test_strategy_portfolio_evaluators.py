from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from m12_helpers import evaluation, portfolio_data, updated_snapshot
from trading_desk.context.models import (
    BreakoutState,
    RangeState,
    TrendState,
    VolatilityState,
)
from trading_desk.strategy.contracts import StrategyDecision, evaluation_context
from trading_desk.strategy.range_mean_reversion import RangeMeanReversionEvaluator
from trading_desk.strategy.trend_pullback import TrendPullbackEvaluator
from trading_desk.strategy.volatility_breakout import VolatilityBreakoutEvaluator


@pytest.mark.parametrize(
    ("evaluator", "kind", "context"),
    [
        (
            TrendPullbackEvaluator(),
            "pullback",
            updated_snapshot(trend_state=TrendState.STRONG_BULL_TREND),
        ),
        (
            VolatilityBreakoutEvaluator(),
            "breakout",
            updated_snapshot(
                breakout_state=BreakoutState.CONFIRMED_UP,
                volatility_state=VolatilityState.EXPANSION,
            ),
        ),
        (
            RangeMeanReversionEvaluator(),
            "range",
            updated_snapshot(
                trend_state=TrendState.RANGE,
                range_state=RangeState.ESTABLISHED,
                breakout_state=BreakoutState.NONE,
                volatility_state=VolatilityState.LOW,
            ),
        ),
    ],
)
def test_strategy_candidate_is_long_only_and_contains_no_quantity(
    evaluator,
    kind: str,
    context,  # type: ignore[no-untyped-def]
) -> None:
    result = evaluator.evaluate(context=evaluation(portfolio_data(kind), context))
    assert result.decision is StrategyDecision.CANDIDATE
    assert result.direction.value == "LONG"
    assert result.proposed_stop < result.entry_reference < result.proposed_target
    assert "quantity" not in type(result).model_fields
    assert "position_size" not in type(result).model_fields


@pytest.mark.parametrize(
    ("evaluator", "kind"),
    [
        (TrendPullbackEvaluator(), "pullback"),
        (VolatilityBreakoutEvaluator(), "breakout"),
        (RangeMeanReversionEvaluator(), "range"),
    ],
)
def test_unknown_position_and_excessive_spread_fail_closed(evaluator, kind: str) -> None:  # type: ignore[no-untyped-def]
    data = portfolio_data(kind)
    base = evaluation(data, updated_snapshot())
    unknown = base.model_copy(update={"existing_position": None})
    result = evaluator.evaluate(context=unknown)
    assert result.decision is StrategyDecision.REJECT
    assert "UNKNOWN_POSITION_STATE" in result.rejection_reasons

    wide_context = updated_snapshot(spread_bps="50")
    result = evaluator.evaluate(context=evaluation(data, wide_context))
    assert result.decision is StrategyDecision.REJECT
    assert "EXCESSIVE_SPREAD" in result.rejection_reasons


def test_wrong_regimes_are_ineligible() -> None:
    assert (
        TrendPullbackEvaluator()
        .evaluate(
            context=evaluation(
                portfolio_data("pullback"), updated_snapshot(trend_state=TrendState.RANGE)
            )
        )
        .decision
        is StrategyDecision.INELIGIBLE_REGIME
    )
    assert (
        VolatilityBreakoutEvaluator()
        .evaluate(
            context=evaluation(
                portfolio_data("breakout"), updated_snapshot(breakout_state=BreakoutState.NONE)
            )
        )
        .decision
        is StrategyDecision.INELIGIBLE_REGIME
    )
    assert (
        RangeMeanReversionEvaluator()
        .evaluate(
            context=evaluation(
                portfolio_data("range"), updated_snapshot(trend_state=TrendState.STRONG_BULL_TREND)
            )
        )
        .decision
        is StrategyDecision.INELIGIBLE_REGIME
    )


def test_future_append_does_not_change_cutoff_result() -> None:
    data = portfolio_data("pullback")
    context = updated_snapshot(trend_state=TrendState.STRONG_BULL_TREND)
    first = TrendPullbackEvaluator().evaluate(context=evaluation(data, context))
    future = data.model_copy(
        update={
            "timestamps": (*data.timestamps, data.timestamps[-1] + timedelta(hours=1)),
            "open_midpoints": (*data.open_midpoints, 200.0),
            "high_midpoints": (*data.high_midpoints, 201.0),
            "low_midpoints": (*data.low_midpoints, 199.0),
            "close_midpoints": (*data.close_midpoints, 200.0),
            "bids": (*data.bids, 199.99),
            "asks": (*data.asks, 200.01),
            "spreads": (*data.spreads, 0.02),
            "spread_bps": (*data.spread_bps, 1.0),
            "volume": (*data.volume, 1000.0),
            "source_bar_count": len(data.timestamps) + 1,
        }
    )
    second = TrendPullbackEvaluator().evaluate(
        context=evaluation(future.sliced_through(len(data.timestamps) - 1), context)
    )
    assert first.decision == second.decision
    assert first.evidence == second.evidence


def test_incomplete_higher_timeframe_data_is_rejected() -> None:
    data = portfolio_data("pullback")
    base = evaluation(data, updated_snapshot())
    future = data.model_copy(
        update={
            "timestamps": tuple(item + timedelta(hours=2) for item in data.timestamps),
            "data_retrieval_time": data.data_retrieval_time + timedelta(hours=2),
        }
    )
    fields = base.model_dump(mode="python", exclude={"evaluation_id"})
    fields["higher_timeframe_data"] = future
    with pytest.raises(ValidationError, match="higher-timeframe"):
        evaluation_context(**fields)


@pytest.mark.parametrize(
    ("evaluator", "context"),
    [
        (
            VolatilityBreakoutEvaluator(),
            updated_snapshot(
                breakout_state=BreakoutState.CONFIRMED_UP,
                volatility_state=VolatilityState.EXPANSION,
            ),
        ),
        (
            RangeMeanReversionEvaluator(),
            updated_snapshot(
                trend_state=TrendState.RANGE,
                range_state=RangeState.ESTABLISHED,
                breakout_state=BreakoutState.NONE,
                volatility_state=VolatilityState.LOW,
            ),
        ),
    ],
)
def test_zero_average_true_range_rejects_instead_of_crashing(
    evaluator,
    context,  # type: ignore[no-untyped-def]
) -> None:
    """Flat quiet-market history (high == low == close) must fail closed.

    Real historical bars can produce a zero ATR; discovered during Milestone 12
    historical validation when unguarded ``width / atr`` divisions raised
    ``decimal.DivisionByZero`` mid-simulation.
    """

    data = portfolio_data("range")
    flat = tuple(100.0 for _ in data.close_midpoints)
    frozen = data.model_copy(
        update={
            "open_midpoints": flat,
            "high_midpoints": flat,
            "low_midpoints": flat,
            "close_midpoints": flat,
            "bids": tuple(value - 0.005 for value in flat),
            "asks": tuple(value + 0.005 for value in flat),
        }
    )
    result = evaluator.evaluate(context=evaluation(frozen, context))
    assert result.decision is not StrategyDecision.CANDIDATE
