"""Long-only lower-boundary reversion evaluator for stable ranges."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from trading_desk.context.models import BreakoutState, RangeState, TrendState, VolatilityState
from trading_desk.strategy.common.statistics import average_true_range, linear_slope, prior_range
from trading_desk.strategy.contracts import (
    StrategyDecision,
    StrategyDirection,
    StrategyEvaluationContext,
    StrategyEvaluationResult,
    StrategyEvidence,
    strategy_result,
)
from trading_desk.strategy.evaluator_support import (
    common_rejections,
    evaluator_fingerprint,
    rejected_result,
    safe_prices,
)
from trading_desk.strategy.portfolio_configuration import RangeMeanReversionConfiguration


class RangeMeanReversionEvaluator:
    strategy_id = "range-mean-reversion"
    strategy_version = "1.0.0"

    def __init__(self, configuration: RangeMeanReversionConfiguration | None = None) -> None:
        self.configuration = configuration or RangeMeanReversionConfiguration()
        self.strategy_fingerprint = evaluator_fingerprint(
            self.strategy_id, self.strategy_version, self.configuration
        )

    def evaluate(self, *, context: StrategyEvaluationContext) -> StrategyEvaluationResult:
        common = common_rejections(context, self.configuration)
        if common:
            return rejected_result(
                evaluator=self, context=context, decision=common[0], reasons=common[1]
            )
        market = context.market_context
        if (
            market.range_state is not RangeState.ESTABLISHED
            or market.trend_state is not TrendState.RANGE
        ):
            return rejected_result(
                evaluator=self,
                context=context,
                decision=StrategyDecision.INELIGIBLE_REGIME,
                reasons=("STABLE_RANGE_REQUIRED",),
            )
        if market.breakout_state is not BreakoutState.NONE or market.volatility_state not in {
            VolatilityState.LOW,
            VolatilityState.NORMAL,
            VolatilityState.COMPRESSION,
        }:
            return rejected_result(
                evaluator=self,
                context=context,
                decision=StrategyDecision.INELIGIBLE_REGIME,
                reasons=("BREAKOUT_OR_VOLATILITY_BLOCK",),
            )
        opens, highs, lows, closes = safe_prices(context)
        cfg = self.configuration
        atr = average_true_range(highs, lows, closes, cfg.atr_window)
        lower, upper = prior_range(highs, lows, cfg.range_window)
        width = upper - lower
        equilibrium = (upper + lower) / Decimal("2")
        location = (closes[-1] - lower) / width if width else Decimal("1")
        normalized_slope = (
            abs(linear_slope(closes[:-1], cfg.trend_window) / atr) if atr else Decimal("999")
        )
        recovery = (closes[-1] - lows[-1]) / width if width else Decimal("0")
        reasons: list[str] = []
        if width <= 0 or width / atr > cfg.maximum_range_width_atr:
            reasons.append("UNSTABLE_RANGE_WIDTH")
        if normalized_slope > cfg.maximum_normalized_slope:
            reasons.append("DIRECTIONAL_TREND_PRESENT")
        if not Decimal("0") <= location <= cfg.lower_entry_fraction:
            reasons.append("NOT_AT_LOWER_RANGE_REGION")
        if recovery < cfg.recovery_fraction or closes[-1] <= opens[-1]:
            reasons.append("UPWARD_REJECTION_NOT_CONFIRMED")
        entry = closes[-1]
        stop = lower - atr * cfg.stop_buffer_atr
        target = equilibrium
        risk = entry - stop
        reward = target - entry
        if stop <= 0 or risk <= 0 or reward <= 0 or reward / risk < cfg.minimum_reward_to_risk:
            reasons.append("INVALID_REWARD_RISK")
        evidence = (
            StrategyEvidence(
                name="range_location",
                value=location,
                threshold=cfg.lower_entry_fraction,
                passed=location <= cfg.lower_entry_fraction,
            ),
            StrategyEvidence(
                name="normalized_slope",
                value=normalized_slope,
                threshold=cfg.maximum_normalized_slope,
                passed=normalized_slope <= cfg.maximum_normalized_slope,
            ),
            StrategyEvidence(
                name="recovery_fraction",
                value=recovery,
                threshold=cfg.recovery_fraction,
                passed=recovery >= cfg.recovery_fraction,
            ),
            StrategyEvidence(name="range_width_atr", value=width / atr),
        )
        if reasons:
            return strategy_result(
                evaluation_id=context.evaluation_id,
                strategy_id=self.strategy_id,
                strategy_version=self.strategy_version,
                strategy_fingerprint=self.strategy_fingerprint,
                instrument_id=context.instrument_id,
                epic=context.epic,
                timeframe=context.timeframe,
                evaluation_timestamp=context.evaluation_timestamp,
                decision=StrategyDecision.REJECT,
                signal_strength=Decimal("0"),
                signal_confidence=Decimal("0"),
                evidence=evidence,
                rejection_reasons=tuple(reasons),
            )
        probability = Decimal("0.58")
        return strategy_result(
            evaluation_id=context.evaluation_id,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            strategy_fingerprint=self.strategy_fingerprint,
            instrument_id=context.instrument_id,
            epic=context.epic,
            timeframe=context.timeframe,
            evaluation_timestamp=context.evaluation_timestamp,
            decision=StrategyDecision.CANDIDATE,
            direction=StrategyDirection.LONG,
            signal_strength=max(Decimal("0"), Decimal("1") - location),
            signal_confidence=probability,
            entry_reference=entry,
            proposed_stop=stop,
            proposed_target=target,
            expected_holding_period=timedelta(
                seconds=context.timeframe.seconds * cfg.maximum_holding_bars
            ),
            estimated_win_probability=probability,
            estimated_average_gain=reward,
            estimated_average_loss=risk,
            gross_expected_value=probability * reward - (Decimal("1") - probability) * risk,
            invalidation_conditions=(
                "range_boundary_break",
                "directional_regime",
                "maximum_holding_period",
            ),
            evidence=evidence,
        )
