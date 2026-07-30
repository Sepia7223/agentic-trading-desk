"""Completed-bar Donchian channel breakout trend-following evaluator.

Long-only. Enters when the completed close breaks above the highest high of the
prior ``entry_channel_window`` bars (the Donchian upper channel). The stop is an
ATR multiple below entry. The **primary exit is the trailing trend-break
invalidation** (the position holds while the uptrend persists and exits when it
breaks), with only a deliberately **wide backstop target** so a few large winners
can pay for the many small losses that define trend-following. The strategy
contract requires a target, so it cannot be omitted — but a far (default 8R)
backstop avoids the fixed 2R cap that amputated the earlier families' fat right
tail, which is the structural fix here.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from trading_desk.context.models import VolatilityState
from trading_desk.strategy.common.statistics import average_true_range, prior_range
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
from trading_desk.strategy.portfolio_configuration import DonchianBreakoutConfiguration


class DonchianBreakoutEvaluator:
    strategy_id = "donchian-breakout"
    strategy_version = "1.0.0"

    def __init__(self, configuration: DonchianBreakoutConfiguration | None = None) -> None:
        self.configuration = configuration or DonchianBreakoutConfiguration()
        self.strategy_fingerprint = evaluator_fingerprint(
            self.strategy_id, self.strategy_version, self.configuration
        )

    def evaluate(self, *, context: StrategyEvaluationContext) -> StrategyEvaluationResult:
        common = common_rejections(context, self.configuration)
        if common:
            return rejected_result(
                evaluator=self, context=context, decision=common[0], reasons=common[1]
            )
        if context.market_context.volatility_state is VolatilityState.EXTREME:
            return rejected_result(
                evaluator=self,
                context=context,
                decision=StrategyDecision.INELIGIBLE_REGIME,
                reasons=("EXTREME_VOLATILITY",),
            )
        opens, highs, lows, closes = safe_prices(context)
        cfg = self.configuration
        atr = average_true_range(highs, lows, closes, cfg.atr_window)
        _, upper = prior_range(highs, lows, cfg.entry_channel_window)
        breakout = closes[-1] - upper
        entry = closes[-1]
        stop = entry - atr * cfg.stop_atr_multiple
        risk = entry - stop
        target = entry + risk * cfg.target_r_multiple
        reasons: list[str] = []
        if closes[-1] <= upper or breakout < atr * cfg.breakout_buffer_atr:
            reasons.append("NO_CHANNEL_BREAKOUT_ON_CLOSE")
        if atr <= 0 or stop <= 0 or risk <= 0:
            reasons.append("INVALID_STOP")
        breakout_atr = breakout / atr if atr else Decimal("0")
        evidence = (
            StrategyEvidence(
                name="channel_breakout_atr",
                value=breakout_atr,
                threshold=cfg.breakout_buffer_atr,
                passed=breakout_atr >= cfg.breakout_buffer_atr,
            ),
            StrategyEvidence(
                name="completed_close_above_channel",
                value=closes[-1] > upper,
                passed=closes[-1] > upper,
            ),
            StrategyEvidence(name="entry_channel_high", value=upper),
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
        probability = cfg.assumed_win_probability
        gain = risk * cfg.assumed_reward_multiple
        loss = risk
        strength = min(Decimal("1"), breakout_atr / Decimal("2"))
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
            signal_strength=strength,
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
                "trend_structure_broken",
                "maximum_holding_period",
            ),
            evidence=evidence,
        )
