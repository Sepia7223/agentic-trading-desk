"""Mandatory deterministic long-only signal gates."""

from __future__ import annotations

import math
from datetime import timedelta
from importlib.metadata import version

from trading_desk.strategy.baseline import BASELINE_MODEL_VERSION
from trading_desk.strategy.configuration import StrategyConfiguration
from trading_desk.strategy.data_validation import infer_bar_cadence
from trading_desk.strategy.kalman import KALMAN_MODEL_VERSION
from trading_desk.strategy.models import (
    BaselineResult,
    DataValidationResult,
    ExecutionTimingPolicy,
    GateResult,
    HMMRegimeResult,
    KalmanTrendResult,
    MacroState,
    ModelVersion,
    Regime,
    RegimeProbability,
    StrategyAction,
    StrategyContext,
    StrategyMarketData,
    StrategyVariant,
    TradeCandidate,
)
from trading_desk.strategy.regime import HMM_MODEL_VERSION

SIGNAL_ENGINE_VERSION = "mandatory-long-gates-v2"


def generate_trade_candidate(
    data: StrategyMarketData,
    context: StrategyContext,
    validation: DataValidationResult,
    baseline: BaselineResult,
    kalman: KalmanTrendResult,
    regime: HMMRegimeResult,
    config: StrategyConfiguration,
) -> TradeCandidate:
    selected_probability = regime.selected_regime_probability
    fresh_trigger = len(baseline.rebound_flags) >= 2 or baseline.original_decision.startswith(
        "RE-ENTRY"
    )
    kalman_enabled = config.variant in {
        StrategyVariant.BASELINE_KALMAN,
        StrategyVariant.BASELINE_KALMAN_HMM,
    }
    hmm_enabled = config.variant in {
        StrategyVariant.BASELINE_HMM,
        StrategyVariant.BASELINE_KALMAN_HMM,
    }
    finite_kalman_output = (not kalman_enabled) or _finite_optional(
        kalman.current_filtered_level,
        kalman.current_slope,
        kalman.current_slope_uncertainty,
        kalman.current_normalized_slope,
        kalman.current_normalized_slope_uncertainty,
        kalman.normalized_price_deviation,
    )
    finite_regime_output = (not hmm_enabled) or _finite_optional(
        regime.uncertainty, selected_probability
    )
    normalized_slope = kalman.current_normalized_slope
    normalized_slope_uncertainty = kalman.current_normalized_slope_uncertainty
    deviation = kalman.normalized_price_deviation
    gates = [
        _gate("market_data_valid", validation.valid, "market data passed validation"),
        _gate(
            "market_tradeable",
            data.market_status.upper() == "TRADEABLE"
            and context.market_status.upper() == "TRADEABLE",
            "market status must be TRADEABLE",
        ),
        _gate("holding_state_known", context.holding is not None, "holding state must be known"),
        _gate("position_flat", context.holding is False, "position must be known and flat"),
        _gate(
            "spread_acceptable",
            context.current_spread_bps <= config.maximum_spread_bps,
            "relative spread must be within the basis-point threshold",
        ),
        _gate(
            "macro_confirmation",
            not config.require_macro_confirmation
            or (context.macro_score is not None and context.macro_score >= 0),
            "macro confirmation is required and must be non-adverse",
        ),
    ]
    if kalman_enabled:
        gates.extend(
            [
                _gate("kalman_ready", kalman.ready, "Kalman trend must be ready"),
                _gate(
                    "kalman_output_finite",
                    finite_kalman_output,
                    "Kalman output must be finite",
                ),
                _gate(
                    "positive_kalman_slope",
                    normalized_slope is not None and normalized_slope > 0,
                    "normalized Kalman slope must be positive",
                ),
                _gate(
                    "kalman_slope_uncertainty",
                    normalized_slope_uncertainty is not None
                    and normalized_slope_uncertainty
                    <= config.maximum_kalman_normalized_slope_uncertainty,
                    "normalized Kalman slope uncertainty must be acceptable",
                ),
                _gate(
                    "entry_deviation",
                    deviation is not None
                    and config.minimum_entry_deviation
                    <= deviation
                    <= config.maximum_entry_deviation,
                    "normalized price deviation must be inside the entry range",
                ),
            ]
        )
    if hmm_enabled:
        gates.extend(
            [
                _gate(
                    "regime_output_finite",
                    finite_regime_output,
                    "HMM output must be finite",
                ),
                _gate("regime_ready", regime.ready, "HMM regime must be converged and confident"),
                _gate(
                    "bull_low_vol_regime",
                    regime.current_regime is Regime.BULL_LOW_VOL,
                    "regime must be BULL_LOW_VOL",
                ),
                _gate(
                    "regime_probability",
                    selected_probability >= config.minimum_regime_probability,
                    "regime probability must meet the configured minimum",
                ),
                _gate(
                    "regime_uncertainty",
                    regime.uncertainty <= config.maximum_regime_uncertainty,
                    "regime uncertainty must be acceptable",
                ),
            ]
        )
    gates.extend(
        [
            _gate(
                "baseline_trend",
                baseline.trend_score >= config.minimum_trend_score,
                "baseline trend score must meet the minimum",
            ),
            _gate(
                "baseline_momentum",
                baseline.momentum_score >= config.minimum_momentum_score,
                "baseline momentum score must meet the minimum",
            ),
            _gate("fresh_entry_trigger", fresh_trigger, "a fresh rebound trigger is required"),
            _gate("no_death_cross", not baseline.death_cross, "death-cross must be absent"),
            _gate(
                "no_relentless_bearish",
                not baseline.relentless_bearish,
                "relentless bearish conditions must be absent",
            ),
        ]
    )
    all_passed = all(gate.passed for gate in gates)
    if all_passed:
        action = StrategyAction.LONG_CANDIDATE
    elif (
        context.holding is True
        and validation.valid
        and (not kalman_enabled or (kalman.ready and finite_kalman_output))
        and (not hmm_enabled or (regime.ready and finite_regime_output))
    ):
        action = StrategyAction.WATCH
    else:
        action = StrategyAction.NO_TRADE
    rejection_reasons = tuple(gate.reason for gate in gates if not gate.passed)
    deterministic_reasons = tuple(gate.reason for gate in gates if gate.passed)
    cadence_seconds, _ = infer_bar_cadence(data)
    signal_timestamp = data.timestamps[-1]
    earliest_execution = (
        signal_timestamp + timedelta(seconds=cadence_seconds)
        if cadence_seconds is not None
        else None
    )
    macro_state = _macro_state(context.macro_score)
    output_regime = regime.current_regime if hmm_enabled else Regime.UNKNOWN
    output_probabilities = (
        regime.probabilities
        if hmm_enabled
        else tuple(
            RegimeProbability(regime=item, probability=0.0)
            for item in (Regime.BULL_LOW_VOL, Regime.TRANSITIONAL, Regime.BEAR_HIGH_VOL)
        )
    )
    return TradeCandidate(
        epic=data.epic,
        instrument_name=data.instrument_name,
        evaluation_timestamp=data.timestamps[-1],
        signal_timestamp=signal_timestamp,
        data_cutoff_timestamp=signal_timestamp,
        earliest_eligible_execution_timestamp=earliest_execution,
        execution_timing_policy=ExecutionTimingPolicy.NEXT_VALID_BAR,
        strategy_variant=config.variant,
        action=action,
        baseline_trend_score=baseline.trend_score,
        baseline_momentum_score=baseline.momentum_score,
        macro_score=baseline.macro_score,
        macro_state=macro_state,
        total_baseline_score=baseline.total_pillar_score,
        current_regime=output_regime,
        regime_probabilities=output_probabilities,
        regime_uncertainty=regime.uncertainty if hmm_enabled else 1.0,
        kalman_level=kalman.current_filtered_level if kalman_enabled else None,
        kalman_slope=kalman.current_slope if kalman_enabled else None,
        kalman_slope_uncertainty=kalman.current_slope_uncertainty if kalman_enabled else None,
        kalman_normalized_slope=kalman.current_normalized_slope if kalman_enabled else None,
        kalman_normalized_slope_uncertainty=(
            kalman.current_normalized_slope_uncertainty if kalman_enabled else None
        ),
        normalized_price_deviation=(kalman.normalized_price_deviation if kalman_enabled else None),
        current_spread=context.current_spread,
        current_spread_bps=context.current_spread_bps,
        validation_findings=validation.findings,
        mandatory_gates=tuple(gates),
        deterministic_reasons=deterministic_reasons,
        rejection_reasons=rejection_reasons,
        model_versions=(
            ModelVersion(component="baseline", version=BASELINE_MODEL_VERSION),
            ModelVersion(component="kalman", version=KALMAN_MODEL_VERSION),
            ModelVersion(component="hmm", version=HMM_MODEL_VERSION),
            ModelVersion(component="signal_engine", version=SIGNAL_ENGINE_VERSION),
            ModelVersion(component="strategy_schema", version=config.strategy_schema_version),
            *_numerical_runtime_versions(),
        ),
        configuration_fingerprint=config.fingerprint,
    )


def _gate(name: str, passed: bool, reason: str) -> GateResult:
    return GateResult(name=name, passed=bool(passed), reason=reason)


def _finite_optional(*values: float | None) -> bool:
    return all(value is not None and math.isfinite(value) for value in values)


def _macro_state(score: int | None) -> MacroState:
    if score is None:
        return MacroState.UNKNOWN
    if score < 0:
        return MacroState.ADVERSE
    if score > 0:
        return MacroState.FAVORABLE
    return MacroState.NEUTRAL


def _numerical_runtime_versions() -> tuple[ModelVersion, ...]:
    packages = ("numpy", "scipy", "scikit-learn", "hmmlearn")
    return tuple(ModelVersion(component=name, version=version(name)) for name in packages)
