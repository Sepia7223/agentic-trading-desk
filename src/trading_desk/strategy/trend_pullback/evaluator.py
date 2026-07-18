"""Long-only controlled retracement evaluator."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from trading_desk.context.models import TrendState, VolatilityState
from trading_desk.strategy.common.statistics import average_true_range, linear_slope
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
from trading_desk.strategy.portfolio_configuration import TrendPullbackConfiguration


class TrendPullbackEvaluator:
    strategy_id = "trend-pullback-v1"
    strategy_version = "1.0.0"

    def __init__(self, configuration: TrendPullbackConfiguration | None = None) -> None:
        self.configuration = configuration or TrendPullbackConfiguration()
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
        if market.trend_state not in {TrendState.STRONG_BULL_TREND, TrendState.WEAK_BULL_TREND}:
            return rejected_result(
                evaluator=self,
                context=context,
                decision=StrategyDecision.INELIGIBLE_REGIME,
                reasons=("BULL_TREND_REQUIRED",),
            )
        if market.volatility_state in {
            VolatilityState.EXTREME,
            VolatilityState.EXPANSION,
            VolatilityState.UNKNOWN,
        }:
            return rejected_result(
                evaluator=self,
                context=context,
                decision=StrategyDecision.INELIGIBLE_REGIME,
                reasons=("DISORDERLY_VOLATILITY",),
            )
        opens, highs, lows, closes = safe_prices(context)
        cfg = self.configuration
        atr = average_true_range(highs, lows, closes, cfg.atr_window)
        slope = linear_slope(closes, cfg.trend_window)
        normalized_slope = slope / atr if atr else Decimal("0")
        recent_peak = max(highs[-cfg.pullback_lookback - 1 : -1])
        recent_low = min(lows[-cfg.pullback_lookback :])
        retracement = (recent_peak - recent_low) / atr if atr else Decimal("0")
        recovery = (closes[-1] - recent_low) / max(recent_peak - recent_low, Decimal("0.00000001"))
        extension = (closes[-1] - recent_peak) / atr if atr else Decimal("999")
        reasons: list[str] = []
        if normalized_slope < cfg.minimum_normalized_slope:
            reasons.append("TREND_TOO_WEAK")
        if not cfg.minimum_retracement_atr <= retracement <= cfg.maximum_retracement_atr:
            reasons.append("PULLBACK_DEPTH_INVALID")
        if recovery < cfg.recovery_fraction or closes[-1] <= opens[-1]:
            reasons.append("RECOVERY_NOT_CONFIRMED")
        if extension > cfg.maximum_entry_extension_atr:
            reasons.append("ENTRY_TOO_EXTENDED")
        entry = closes[-1]
        stop = recent_low - atr * cfg.stop_buffer_atr
        risk = entry - stop
        target = entry + risk * cfg.target_r_multiple
        if stop <= 0 or risk <= 0 or (target - entry) / risk < cfg.minimum_reward_to_risk:
            reasons.append("INVALID_REWARD_RISK")
        evidence = (
            StrategyEvidence(
                name="normalized_slope",
                value=normalized_slope,
                threshold=cfg.minimum_normalized_slope,
                passed=normalized_slope >= cfg.minimum_normalized_slope,
            ),
            StrategyEvidence(name="retracement_atr", value=retracement),
            StrategyEvidence(
                name="recovery_fraction",
                value=recovery,
                threshold=cfg.recovery_fraction,
                passed=recovery >= cfg.recovery_fraction,
            ),
            StrategyEvidence(
                name="entry_extension_atr",
                value=extension,
                threshold=cfg.maximum_entry_extension_atr,
                passed=extension <= cfg.maximum_entry_extension_atr,
            ),
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
        probability = min(Decimal("0.70"), Decimal("0.50") + normalized_slope / Decimal("10"))
        gain = target - entry
        loss = risk
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
            signal_strength=min(Decimal("1"), normalized_slope),
            signal_confidence=probability,
            entry_reference=entry,
            proposed_stop=stop,
            proposed_target=target,
            expected_holding_period=timedelta(
                seconds=context.timeframe.seconds * cfg.maximum_holding_bars
            ),
            estimated_win_probability=probability,
            estimated_average_gain=gain,
            estimated_average_loss=loss,
            gross_expected_value=probability * gain - (Decimal("1") - probability) * loss,
            invalidation_conditions=(
                "trend_structure_break",
                "disorderly_volatility",
                "maximum_holding_period",
            ),
            evidence=evidence,
        )
