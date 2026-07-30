from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from m12_helpers import updated_snapshot
from test_strategy_governance import NOW, trade
from trading_desk.context.fingerprints import fingerprint
from trading_desk.context.models import BreakoutState, RangeState, TrendState
from trading_desk.strategy.invalidation import (
    InvalidationDecision,
    PositionEntryContext,
    evaluate_invalidation,
)
from trading_desk.strategy.validation import (
    ValidationGates,
    ValidationReport,
    ValidationStage,
    calculate_metrics,
    execution_stress,
    portfolio_ablation,
    portfolio_contribution,
    robustness_stress,
    walk_forward_validate,
)


def test_walk_forward_is_chronological_and_retains_failed_windows() -> None:
    definitions = (
        (
            NOW,
            NOW + timedelta(days=10),
            NOW + timedelta(days=11),
            NOW + timedelta(days=20),
            (trade(0, "2"),),
            "a" * 64,
        ),
        (
            NOW + timedelta(days=1),
            NOW + timedelta(days=20),
            NOW + timedelta(days=21),
            NOW + timedelta(days=30),
            (trade(1, "-2"),),
            "b" * 64,
        ),
    )
    result = walk_forward_validate("research", definitions)
    assert result.failed_window_count == 1
    assert result.profitable_window_fraction == Decimal("0.5")
    assert result.parameter_instability == Decimal("1")
    assert result == walk_forward_validate("research", definitions)


def test_walk_forward_rejects_overlapping_forward_windows() -> None:
    definitions = (
        (
            NOW,
            NOW + timedelta(days=2),
            NOW + timedelta(days=3),
            NOW + timedelta(days=6),
            (),
            "a" * 64,
        ),
        (
            NOW,
            NOW + timedelta(days=3),
            NOW + timedelta(days=5),
            NOW + timedelta(days=8),
            (),
            "a" * 64,
        ),
    )
    with pytest.raises(ValueError, match="overlap"):
        walk_forward_validate("research", definitions)


def test_final_test_requires_preexisting_lock() -> None:
    metrics = calculate_metrics(())
    fields = {
        "strategy_id": "research",
        "strategy_version": "1.0.0",
        "stage": ValidationStage.FINAL_TEST,
        "dataset_fingerprint": "d" * 64,
        "dataset_start": NOW,
        "dataset_end": NOW + timedelta(days=1),
        "configuration_fingerprint": "c" * 64,
        "metrics": metrics,
        "required_gates": ValidationGates(),
        "failed_gates": ("MINIMUM_CLOSED_TRADES",),
        "data_quality_findings": (),
        "final_test_locked_before_evaluation": False,
        "created_at": NOW,
    }
    fields["validation_report_id"] = fingerprint(fields)
    with pytest.raises(ValidationError, match="pre-existing lock"):
        ValidationReport.model_validate(fields)


def test_execution_and_portfolio_stress_preserve_strategy_lineage() -> None:
    trend = trade(0, "2").model_copy(update={"strategy_id": "trend-regime-v1"})
    pullback = trade(1, "1").model_copy(update={"strategy_id": "trend-pullback-v1"})
    stress = execution_stress((pullback,), "trend-pullback-v1", Decimal("0.10"))
    assert stress.delayed_bars == 1
    contribution = portfolio_contribution("trend-pullback-v1", (trend, pullback))
    assert contribution.trade_contribution == 1
    assert contribution.marginal_net_return == pullback.net_pnl


def test_required_robustness_and_portfolio_ablations_are_retained() -> None:
    values = (
        trade(0, "2").model_copy(update={"strategy_id": "trend-regime-v1"}),
        trade(1, "1").model_copy(update={"strategy_id": "trend-pullback-v1"}),
        trade(2, "1").model_copy(update={"strategy_id": "volatility-breakout"}),
        trade(3, "1").model_copy(update={"strategy_id": "range-mean-reversion"}),
    )
    robustness = robustness_stress(values, "portfolio")
    assert {item.stress_type.value for item in robustness} == {
        "PARAMETER",
        "TIMEFRAME",
        "INSTRUMENT_HOLDOUT",
        "PERIOD_HOLDOUT",
        "REGIME_HOLDOUT",
        "MISSING_BAR",
        "VOLATILITY_SHIFT",
    }
    scenarios = portfolio_ablation(
        values, correlation_filtered=values[:3], risk_filtered=values[:2]
    )
    assert tuple(item.name for item in scenarios) == (
        "existing_trend_alone",
        "trend_plus_pullback",
        "trend_plus_breakout",
        "trend_plus_mean_reversion",
        "all_validated_strategies",
        "after_correlation_filter",
        "after_risk",
    )
    assert all(len(item.scenario_fingerprint) == 64 for item in scenarios)


@pytest.mark.parametrize(
    ("strategy_id", "context", "reason"),
    [
        (
            "trend-pullback-v1",
            updated_snapshot(trend_state=TrendState.RANGE),
            "TREND_STRUCTURE_INVALIDATED",
        ),
        (
            "volatility-breakout",
            updated_snapshot(breakout_state=BreakoutState.CONFIRMED_DOWN),
            "BREAKOUT_FAILED",
        ),
        (
            "range-mean-reversion",
            updated_snapshot(range_state=RangeState.NOT_RANGE),
            "RANGE_INVALIDATED",
        ),
    ],
)
def test_strategy_invalidation_signals_exit_without_closing(
    strategy_id: str,
    context,
    reason: str,  # type: ignore[no-untyped-def]
) -> None:
    entry = PositionEntryContext(
        strategy_id=strategy_id,
        strategy_version="1.0.0",
        maximum_holding_period=timedelta(days=2),
    )
    result = evaluate_invalidation(entry, context, timedelta(hours=2))
    assert result.decision is InvalidationDecision.EXIT
    assert reason in result.reasons
    assert "close" not in type(result).model_fields


def test_missing_invalidation_context_fails_unknown() -> None:
    entry = PositionEntryContext(
        strategy_id="trend-pullback-v1",
        strategy_version="1.0.0",
        maximum_holding_period=timedelta(days=2),
    )
    assert evaluate_invalidation(entry, None, timedelta()).decision is InvalidationDecision.UNKNOWN
