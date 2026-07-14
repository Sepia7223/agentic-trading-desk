from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from trading_desk.cli import build_parser
from trading_desk.strategy import score
from trading_desk.strategy.baseline import evaluate_baseline
from trading_desk.strategy.configuration import StrategyConfiguration
from trading_desk.strategy.models import (
    BaselineResult,
    DataValidationResult,
    ExecutionTimingPolicy,
    HMMRegimeResult,
    KalmanTrendResult,
    MacroState,
    Regime,
    RegimeProbability,
    StrategyAction,
    StrategyBarResolution,
    StrategyContext,
    StrategyMarketData,
    StrategyVariant,
)
from trading_desk.strategy.pipeline import RegimeAwareStrategyPipeline
from trading_desk.strategy.signal_engine import generate_trade_candidate


def _data(closes: tuple[float, ...] | None = None) -> StrategyMarketData:
    values = closes or tuple(100.0 + index * 0.05 for index in range(390))
    end = datetime(2026, 7, 13, tzinfo=UTC)
    timestamps = tuple(end - timedelta(days=len(values) - 1 - i) for i in range(len(values)))
    return StrategyMarketData(
        epic="CS.D.TEST.CFD.IP",
        instrument_name="Test market",
        timestamps=timestamps,
        open_midpoints=values,
        high_midpoints=tuple(value + 0.2 for value in values),
        low_midpoints=tuple(value - 0.2 for value in values),
        close_midpoints=values,
        bids=tuple(value - 0.001 for value in values),
        asks=tuple(value + 0.001 for value in values),
        spreads=(0.002,) * len(values),
        spread_bps=(0.2,) * len(values),
        volume=(1000.0,) * len(values),
        market_status="TRADEABLE",
        data_retrieval_time=end,
        bar_resolution=StrategyBarResolution.DAY,
        source_bar_count=len(values),
    )


def _context(data: StrategyMarketData, holding: bool | None = False) -> StrategyContext:
    return StrategyContext(
        holding=holding,
        macro_score=1,
        current_spread=0.002,
        current_spread_bps=0.2,
        market_status="TRADEABLE",
        current_time=data.timestamps[-1],
    )


def _baseline(**updates: object) -> BaselineResult:
    baseline = BaselineResult(
        trend_score=2,
        trend_detail="bullish",
        momentum_score=2,
        momentum_detail="rebound",
        macro_score=1,
        total_pillar_score=5,
        original_decision="RE-ENTRY",
        original_flags=("rebound: RSI rebound", "rebound: MACD improving"),
        exhaustion_flags=(),
        bearish_flags=(),
        rebound_flags=("RSI rebound", "MACD improving"),
        death_cross=False,
        relentless_bearish=False,
    )
    return baseline.model_copy(update=updates)


def _kalman(**updates: object) -> KalmanTrendResult:
    result = KalmanTrendResult(
        ready=True,
        current_filtered_level=100.0,
        current_slope=0.1,
        current_slope_uncertainty=0.1,
        current_normalized_slope=0.001,
        current_normalized_slope_uncertainty=0.001,
        normalized_price_deviation=0.0,
        observations_used=390,
    )
    return result.model_copy(update=updates)


def _regime(regime: Regime = Regime.BULL_LOW_VOL, **updates: object) -> HMMRegimeResult:
    probabilities = {
        Regime.BULL_LOW_VOL: 0.9 if regime is Regime.BULL_LOW_VOL else 0.05,
        Regime.TRANSITIONAL: 0.9 if regime is Regime.TRANSITIONAL else 0.05,
        Regime.BEAR_HIGH_VOL: 0.9 if regime is Regime.BEAR_HIGH_VOL else 0.05,
    }
    result = HMMRegimeResult(
        ready=True,
        current_regime=regime,
        probabilities=tuple(
            RegimeProbability(regime=item, probability=probabilities[item])
            for item in (
                Regime.BULL_LOW_VOL,
                Regime.TRANSITIONAL,
                Regime.BEAR_HIGH_VOL,
            )
        ),
        selected_regime_probability=0.9,
        uncertainty=0.2,
        converged=True,
        observations_used=370,
    )
    return result.model_copy(update=updates)


def _candidate(
    *,
    context: StrategyContext | None = None,
    validation: DataValidationResult | None = None,
    baseline: BaselineResult | None = None,
    kalman: KalmanTrendResult | None = None,
    regime: HMMRegimeResult | None = None,
):
    data = _data()
    return generate_trade_candidate(
        data,
        context or _context(data),
        validation or DataValidationResult(valid=True, findings=()),
        baseline or _baseline(),
        kalman or _kalman(),
        regime or _regime(),
        StrategyConfiguration(),
    )


def test_all_mandatory_bullish_gates_produce_long_candidate() -> None:
    candidate = _candidate()

    assert candidate.action is StrategyAction.LONG_CANDIDATE
    assert all(gate.passed for gate in candidate.mandatory_gates)
    assert candidate.rejection_reasons == ()
    assert candidate.signal_timestamp == candidate.data_cutoff_timestamp
    assert candidate.earliest_eligible_execution_timestamp is not None
    assert candidate.earliest_eligible_execution_timestamp > candidate.signal_timestamp
    assert candidate.execution_timing_policy is ExecutionTimingPolicy.NEXT_VALID_BAR
    prohibited_fields = {
        "quantity",
        "position_size",
        "leverage",
        "monetary_risk",
        "order_type",
        "stop_price",
        "limit_price",
    }
    assert prohibited_fields.isdisjoint(type(candidate).model_fields)


def test_read_only_strategy_cli_commands_parse_explicit_cutoffs() -> None:
    parser = build_parser()
    analyze = parser.parse_args(["strategy", "analyze", "CS.D.TEST.CFD.IP"])
    walk = parser.parse_args(
        [
            "strategy",
            "walk-forward",
            "CS.D.TEST.CFD.IP",
            "--start-index",
            "220",
            "--end-index",
            "240",
        ]
    )

    assert analyze.strategy_command == "analyze"
    assert walk.strategy_command == "walk-forward"
    assert (walk.start_index, walk.end_index) == (220, 240)


@pytest.mark.parametrize(
    ("change", "failed_gate"),
    [
        ({"validation": DataValidationResult(valid=False, findings=())}, "market_data_valid"),
        ({"context_holding": None}, "holding_state_known"),
        ({"context_holding": True}, "position_flat"),
        ({"context_spread_bps": 20.0}, "spread_acceptable"),
        ({"kalman": _kalman(current_normalized_slope=-0.001)}, "positive_kalman_slope"),
        (
            {"kalman": _kalman(current_normalized_slope_uncertainty=0.02)},
            "kalman_slope_uncertainty",
        ),
        ({"kalman": _kalman(normalized_price_deviation=2.0)}, "entry_deviation"),
        ({"baseline": _baseline(trend_score=0)}, "baseline_trend"),
        ({"baseline": _baseline(momentum_score=0)}, "baseline_momentum"),
        (
            {"baseline": _baseline(rebound_flags=(), original_decision="HOLD")},
            "fresh_entry_trigger",
        ),
        ({"baseline": _baseline(death_cross=True)}, "no_death_cross"),
        ({"baseline": _baseline(relentless_bearish=True)}, "no_relentless_bearish"),
        ({"regime": _regime(Regime.TRANSITIONAL)}, "bull_low_vol_regime"),
        ({"regime": _regime(Regime.BEAR_HIGH_VOL)}, "bull_low_vol_regime"),
        (
            {
                "regime": _regime(
                    selected_regime_probability=0.5,
                    ready=False,
                    reason="low confidence",
                )
            },
            "regime_probability",
        ),
        ({"kalman": _kalman(current_normalized_slope=math.nan)}, "kalman_output_finite"),
    ],
)
def test_failure_of_any_mandatory_gate_prevents_long_candidate(
    change: dict[str, object], failed_gate: str
) -> None:
    data = _data()
    context = _context(data, change.get("context_holding", False))
    if "context_spread_bps" in change:
        context = context.model_copy(update={"current_spread_bps": change["context_spread_bps"]})
    candidate = _candidate(
        context=context,
        validation=change.get("validation"),  # type: ignore[arg-type]
        baseline=change.get("baseline"),  # type: ignore[arg-type]
        kalman=change.get("kalman"),  # type: ignore[arg-type]
        regime=change.get("regime"),  # type: ignore[arg-type]
    )

    assert candidate.action is not StrategyAction.LONG_CANDIDATE
    failed = {gate.name for gate in candidate.mandatory_gates if not gate.passed}
    assert failed_gate in failed
    assert candidate.rejection_reasons


def test_existing_baseline_adapter_preserves_raw_score_behavior() -> None:
    data = _data()
    context = _context(data)
    raw = score.score_symbol(
        list(data.close_midpoints),
        macro_score=context.macro_score,
        symbol=data.epic,
        holding=context.holding,
    )
    typed = evaluate_baseline(data, context)

    assert typed.trend_score == raw["pillars"]["trend"]["score"]
    assert typed.momentum_score == raw["pillars"]["momentum"]["score"]
    assert typed.total_pillar_score == raw["pillar_total"]
    assert typed.original_decision == raw["decision"]["action"]
    assert typed.death_cross == raw["decision"]["flags"]["death_cross"]


def _three_regime_prices() -> tuple[float, ...]:
    random = np.random.default_rng(10)
    returns = np.concatenate(
        [
            random.normal(-0.006, 0.025, 130),
            random.normal(0.0, 0.010, 130),
            random.normal(0.005, 0.001, 130),
        ]
    )
    return tuple(float(value) for value in 100.0 * np.exp(np.cumsum(returns)))


def test_appended_future_does_not_change_an_earlier_cutoff_signal() -> None:
    prefix = _three_regime_prices()
    future = tuple(prefix[-1] * (1.0 + 0.02 * index) for index in range(1, 21))
    prefix_data = _data(prefix)
    future_timestamps = tuple(
        prefix_data.timestamps[-1] + timedelta(days=index) for index in range(1, 21)
    )
    extended_data = _data(prefix + future).model_copy(
        update={
            "timestamps": prefix_data.timestamps + future_timestamps,
            "data_retrieval_time": future_timestamps[-1],
        }
    )
    config = StrategyConfiguration(
        minimum_regime_probability=0.0,
        maximum_regime_uncertainty=1.0,
        hmm_minimum_effective_observations=3.0,
    )
    pipeline = RegimeAwareStrategyPipeline(config)

    original = pipeline.evaluate_at_cutoff(prefix_data, _context(prefix_data), len(prefix) - 1)
    with_future = pipeline.evaluate_at_cutoff(
        extended_data, _context(extended_data), len(prefix) - 1
    )

    assert original.model_dump() == with_future.model_dump()


def test_walk_forward_is_reproducible_at_each_explicit_cutoff() -> None:
    data = _data(_three_regime_prices())
    config = StrategyConfiguration(
        minimum_regime_probability=0.0,
        maximum_regime_uncertainty=1.0,
        hmm_minimum_effective_observations=3.0,
    )
    pipeline = RegimeAwareStrategyPipeline(config)

    first = pipeline.walk_forward(data, _context(data), start_index=388, end_index=389)
    second = pipeline.walk_forward(data, _context(data), start_index=388, end_index=389)

    assert [item.model_dump() for item in first] == [item.model_dump() for item in second]


def test_macro_policy_distinguishes_missing_neutral_adverse_and_favorable() -> None:
    data = _data()
    for macro_score, expected in (
        (None, MacroState.UNKNOWN),
        (0, MacroState.NEUTRAL),
        (-1, MacroState.ADVERSE),
        (1, MacroState.FAVORABLE),
    ):
        context = _context(data).model_copy(update={"macro_score": macro_score})
        candidate = _candidate(context=context)
        assert candidate.macro_state is expected
    required = StrategyConfiguration(require_macro_confirmation=True)
    missing_context = _context(data).model_copy(update={"macro_score": None})
    candidate = generate_trade_candidate(
        data,
        missing_context,
        DataValidationResult(valid=True, findings=()),
        _baseline(macro_score=None),
        _kalman(),
        _regime(),
        required,
    )
    assert candidate.action is StrategyAction.NO_TRADE
    assert not next(g for g in candidate.mandatory_gates if g.name == "macro_confirmation").passed


def test_holding_true_never_produces_long_candidate_under_bullish_inputs() -> None:
    data = _data()
    candidate = _candidate(context=_context(data, holding=True))
    assert candidate.action is StrategyAction.WATCH
    assert candidate.action is not StrategyAction.LONG_CANDIDATE


@pytest.mark.parametrize(
    "variant",
    [
        StrategyVariant.BASELINE_ONLY,
        StrategyVariant.BASELINE_KALMAN,
        StrategyVariant.BASELINE_HMM,
        StrategyVariant.BASELINE_KALMAN_HMM,
    ],
)
def test_named_ablation_variants_record_selection_and_ignore_disabled_gates(
    variant: StrategyVariant,
) -> None:
    data = _data()
    config = StrategyConfiguration(variant=variant)
    candidate = generate_trade_candidate(
        data,
        _context(data),
        DataValidationResult(valid=True, findings=()),
        _baseline(),
        _kalman(ready=False, current_normalized_slope=-1.0),
        _regime(Regime.BEAR_HIGH_VOL, ready=False),
        config,
    )
    gate_names = {gate.name for gate in candidate.mandatory_gates}
    assert candidate.strategy_variant is variant
    assert ("kalman_ready" in gate_names) is (
        variant in {StrategyVariant.BASELINE_KALMAN, StrategyVariant.BASELINE_KALMAN_HMM}
    )
    assert ("regime_ready" in gate_names) is (
        variant in {StrategyVariant.BASELINE_HMM, StrategyVariant.BASELINE_KALMAN_HMM}
    )


def test_disabled_ablation_components_cannot_change_serialized_result() -> None:
    data = _data()
    config = StrategyConfiguration(variant=StrategyVariant.BASELINE_ONLY)
    arguments = (
        data,
        _context(data),
        DataValidationResult(valid=True, findings=()),
        _baseline(),
    )
    first = generate_trade_candidate(
        *arguments,
        _kalman(current_normalized_slope=-99.0),
        _regime(Regime.BEAR_HIGH_VOL),
        config,
    )
    second = generate_trade_candidate(
        *arguments,
        _kalman(current_normalized_slope=99.0),
        _regime(Regime.BULL_LOW_VOL),
        config,
    )

    assert first.model_dump() == second.model_dump()


def test_strategy_source_has_no_credentials_tokens_or_mutation_surface() -> None:
    strategy_root = Path(__file__).parents[1] / "src" / "trading_desk" / "strategy"
    source = "\n".join(path.read_text(encoding="utf-8") for path in strategy_root.glob("*.py"))
    prohibited = (
        "IG_IDENTIFIER",
        "IG_PASSWORD",
        "IG_API_KEY",
        "OPENAI_API_KEY",
        "CST",
        "X-SECURITY-TOKEN",
        "place_order",
        "create_order",
        "execute_order",
        "close_position",
        "switch_account",
        "/positions/otc",
        "/working-orders/otc",
        "/workingorders/otc",
        "/confirms/",
    )

    assert all(value not in source for value in prohibited)
    assert "trading_desk.ig.client" not in source
    assert "trading_desk.config" not in source
