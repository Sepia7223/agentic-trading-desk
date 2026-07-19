"""Completed-bar volatility compression breakout evaluator."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from trading_desk.context.models import BreakoutState, VolatilityState
from trading_desk.strategy.common.statistics import average_true_range, mean, prior_range
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
from trading_desk.strategy.portfolio_configuration import VolatilityBreakoutConfiguration


class VolatilityBreakoutEvaluator:
    strategy_id = "volatility-breakout"
    strategy_version = "1.0.0"

    def __init__(self, configuration: VolatilityBreakoutConfiguration | None = None) -> None:
        self.configuration = configuration or VolatilityBreakoutConfiguration()
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
            market.breakout_state is not BreakoutState.CONFIRMED_UP
            or market.volatility_state not in {VolatilityState.EXPANSION, VolatilityState.NORMAL}
        ):
            return rejected_result(
                evaluator=self,
                context=context,
                decision=StrategyDecision.INELIGIBLE_REGIME,
                reasons=("CONFIRMED_EXPANSION_REQUIRED",),
            )
        opens, highs, lows, closes = safe_prices(context)
        cfg = self.configuration
        atr = average_true_range(highs, lows, closes, cfg.atr_window)
        lower, upper = prior_range(highs, lows, cfg.consolidation_window)
        width = upper - lower
        breakout = closes[-1] - upper
        chase = breakout / atr if atr else Decimal("999")
        recent_ranges = tuple(
            highs[index] - lows[index]
            for index in range(len(highs) - cfg.volatility_window - 1, len(highs) - 1)
        )
        current_range = highs[-1] - lows[-1]
        expansion = current_range / mean(recent_ranges) if mean(recent_ranges) else Decimal("0")
        width_atr = width / atr if atr else Decimal("999")
        reasons: list[str] = []
        if width_atr > cfg.maximum_consolidation_width_atr:
            reasons.append("CONSOLIDATION_TOO_WIDE")
        if breakout < atr * cfg.minimum_breakout_atr or closes[-1] <= upper:
            reasons.append("BREAKOUT_NOT_CONFIRMED_ON_CLOSE")
        if expansion < cfg.minimum_expansion_ratio:
            reasons.append("INSUFFICIENT_VOLATILITY_EXPANSION")
        if chase > cfg.maximum_chase_atr:
            reasons.append("BREAKOUT_TOO_EXTENDED")
        entry = closes[-1]
        stop = upper - atr * cfg.stop_buffer_atr
        risk = entry - stop
        target = entry + risk * cfg.target_r_multiple
        if stop <= 0 or risk <= 0 or (target - entry) / risk < cfg.minimum_reward_to_risk:
            reasons.append("INVALID_REWARD_RISK")
        evidence = (
            StrategyEvidence(name="consolidation_width_atr", value=width_atr),
            StrategyEvidence(
                name="breakout_distance_atr",
                value=chase,
                threshold=cfg.maximum_chase_atr,
                passed=Decimal("0") < chase <= cfg.maximum_chase_atr,
            ),
            StrategyEvidence(
                name="volatility_expansion_ratio",
                value=expansion,
                threshold=cfg.minimum_expansion_ratio,
                passed=expansion >= cfg.minimum_expansion_ratio,
            ),
            StrategyEvidence(
                name="completed_close_confirmation",
                value=closes[-1] > upper,
                passed=closes[-1] > upper,
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
        probability = min(
            Decimal("0.68"), Decimal("0.50") + (expansion - Decimal("1")) / Decimal("5")
        )
        gain, loss = target - entry, risk
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
            signal_strength=min(Decimal("1"), expansion / Decimal("2")),
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
                "close_inside_original_range",
                "volatility_collapse",
                "maximum_holding_period",
            ),
            evidence=evidence,
        )
