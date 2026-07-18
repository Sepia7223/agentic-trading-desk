"""Deterministic invalidation signals consumed by the Milestone 10 lifecycle."""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from trading_desk.context.models import (
    BreakoutState,
    MarketContextSnapshot,
    RangeState,
    TrendState,
    VolatilityState,
)


class InvalidationDecision(StrEnum):
    HOLD = "HOLD"
    EXIT = "EXIT"
    UNKNOWN = "UNKNOWN"


class PositionEntryContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    strategy_id: str
    strategy_version: str
    original_range_lower: str | None = None
    original_range_upper: str | None = None
    maximum_holding_period: timedelta


class StrategyInvalidationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: InvalidationDecision
    reasons: tuple[str, ...]


def evaluate_invalidation(
    entry: PositionEntryContext,
    context: MarketContextSnapshot | None,
    holding_period: timedelta,
    *,
    risk_requires_exit: bool = False,
) -> StrategyInvalidationResult:
    if risk_requires_exit:
        return StrategyInvalidationResult(
            decision=InvalidationDecision.EXIT, reasons=("RISK_REQUIRES_EXIT",)
        )
    if holding_period >= entry.maximum_holding_period:
        return StrategyInvalidationResult(
            decision=InvalidationDecision.EXIT, reasons=("MAXIMUM_HOLDING_PERIOD",)
        )
    if context is None:
        return StrategyInvalidationResult(
            decision=InvalidationDecision.UNKNOWN, reasons=("CURRENT_CONTEXT_UNAVAILABLE",)
        )
    reasons: list[str] = []
    if entry.strategy_id == "trend-pullback-v1" and (
        context.trend_state not in {TrendState.STRONG_BULL_TREND, TrendState.WEAK_BULL_TREND}
        or context.volatility_state is VolatilityState.EXTREME
    ):
        reasons.append("TREND_STRUCTURE_INVALIDATED")
    elif (
        entry.strategy_id == "volatility-breakout"
        and context.breakout_state is BreakoutState.CONFIRMED_DOWN
    ):
        reasons.append("BREAKOUT_FAILED")
    elif entry.strategy_id == "range-mean-reversion" and (
        context.range_state is not RangeState.ESTABLISHED
        or context.trend_state is not TrendState.RANGE
    ):
        reasons.append("RANGE_INVALIDATED")
    elif entry.strategy_id not in {
        "trend-regime-v1",
        "trend-pullback-v1",
        "volatility-breakout",
        "range-mean-reversion",
    }:
        return StrategyInvalidationResult(
            decision=InvalidationDecision.UNKNOWN, reasons=("UNKNOWN_STRATEGY_VERSION",)
        )
    return StrategyInvalidationResult(
        decision=InvalidationDecision.EXIT if reasons else InvalidationDecision.HOLD,
        reasons=tuple(reasons),
    )
