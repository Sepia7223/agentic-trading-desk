"""Cutoff-safe orchestration for deterministic regime-aware analysis."""

from __future__ import annotations

from trading_desk.strategy.baseline import evaluate_baseline
from trading_desk.strategy.configuration import StrategyConfiguration
from trading_desk.strategy.data_validation import validate_market_data
from trading_desk.strategy.kalman import fit_local_linear_trend
from trading_desk.strategy.models import (
    BaselineResult,
    HMMRegimeResult,
    KalmanTrendResult,
    Regime,
    RegimeProbability,
    StrategyContext,
    StrategyMarketData,
    StrategyVariant,
    TradeCandidate,
    ValidationFinding,
)
from trading_desk.strategy.regime import fit_regime_model
from trading_desk.strategy.signal_engine import generate_trade_candidate


class RegimeAwareStrategyPipeline:
    """Evaluate only the latest point of an explicit cutoff slice."""

    def __init__(self, config: StrategyConfiguration | None = None) -> None:
        self.config = config or StrategyConfiguration()

    def analyze_latest(
        self,
        data: StrategyMarketData,
        context: StrategyContext,
        *,
        inherited_findings: tuple[ValidationFinding, ...] = (),
    ) -> TradeCandidate:
        if not data.timestamps:
            raise ValueError("strategy market data contains no observations")
        return self._evaluate(data, context, inherited_findings)

    def evaluate_at_cutoff(
        self,
        data: StrategyMarketData,
        context: StrategyContext,
        cutoff_index: int,
    ) -> TradeCandidate:
        cutoff_data = data.sliced_through(cutoff_index)
        cutoff_context = context.model_copy(
            update={
                "current_time": cutoff_data.timestamps[-1],
                "current_spread": cutoff_data.spreads[-1],
                "current_spread_bps": cutoff_data.spread_bps[-1],
                "market_status": cutoff_data.market_status,
            }
        )
        return self._evaluate(cutoff_data, cutoff_context, ())

    def walk_forward(
        self,
        data: StrategyMarketData,
        context: StrategyContext,
        *,
        start_index: int,
        end_index: int,
    ) -> tuple[TradeCandidate, ...]:
        if start_index < 0 or end_index < start_index or end_index >= len(data.timestamps):
            raise ValueError("invalid walk-forward index range")
        return tuple(
            self.evaluate_at_cutoff(data, context, cutoff)
            for cutoff in range(start_index, end_index + 1)
        )

    def _evaluate(
        self,
        data: StrategyMarketData,
        context: StrategyContext,
        inherited_findings: tuple[ValidationFinding, ...],
    ) -> TradeCandidate:
        baseline = _baseline_or_default(data, context)
        validation = validate_market_data(
            data,
            context,
            self.config,
            inherited_findings=inherited_findings,
        )
        kalman_enabled = self.config.variant in {
            StrategyVariant.BASELINE_KALMAN,
            StrategyVariant.BASELINE_KALMAN_HMM,
        }
        hmm_enabled = self.config.variant in {
            StrategyVariant.BASELINE_HMM,
            StrategyVariant.BASELINE_KALMAN_HMM,
        }
        if validation.valid:
            kalman = (
                fit_local_linear_trend(data.close_midpoints, self.config)
                if kalman_enabled or self.config.variant is StrategyVariant.BASELINE_KALMAN_HMM
                else _unknown_kalman(len(data.timestamps), "Kalman component disabled")
            )
            regime = (
                fit_regime_model(
                    data.close_midpoints,
                    kalman if self.config.variant is StrategyVariant.BASELINE_KALMAN_HMM else None,
                    self.config,
                )
                if hmm_enabled
                else _unknown_regime("HMM component disabled")
            )
        else:
            kalman = _unknown_kalman(len(data.timestamps), "market data validation failed")
            regime = _unknown_regime("market data validation failed")
        return generate_trade_candidate(
            data,
            context,
            validation,
            baseline,
            kalman,
            regime,
            self.config,
        )


def _baseline_or_default(data: StrategyMarketData, context: StrategyContext) -> BaselineResult:
    if data.close_midpoints:
        try:
            return evaluate_baseline(data, context)
        except (ArithmeticError, IndexError, TypeError, ValueError):
            pass
    return BaselineResult(
        trend_score=0,
        trend_detail="unavailable",
        momentum_score=0,
        momentum_detail="unavailable",
        macro_score=context.macro_score,
        total_pillar_score=context.macro_score or 0,
        original_decision="NO TRADE",
        original_flags=(),
        exhaustion_flags=(),
        bearish_flags=(),
        rebound_flags=(),
        death_cross=False,
        relentless_bearish=False,
    )


def _unknown_regime(reason: str) -> HMMRegimeResult:
    probabilities = tuple(
        RegimeProbability(regime=regime, probability=0.0)
        for regime in (
            Regime.BULL_LOW_VOL,
            Regime.TRANSITIONAL,
            Regime.BEAR_HIGH_VOL,
        )
    )
    return HMMRegimeResult(ready=False, reason=reason, probabilities=probabilities)


def _unknown_kalman(observations: int, reason: str) -> KalmanTrendResult:
    return KalmanTrendResult(ready=False, reason=reason, observations_used=observations)
