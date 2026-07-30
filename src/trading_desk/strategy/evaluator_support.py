"""Shared fail-closed support for deterministic strategy evaluators."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Protocol

from trading_desk.context.fingerprints import fingerprint
from trading_desk.context.models import (
    ContextQuality,
    LiquidityState,
    ScheduledEventState,
    SessionState,
)
from trading_desk.strategy.common.statistics import decimal_prices
from trading_desk.strategy.contracts import (
    StrategyDecision,
    StrategyEvaluationContext,
    StrategyEvaluationResult,
    strategy_result,
)
from trading_desk.strategy.portfolio_configuration import GovernedStrategyConfiguration


class _EvaluatorIdentity(Protocol):
    strategy_id: str
    strategy_version: str
    strategy_fingerprint: str


def safe_prices(context: StrategyEvaluationContext) -> tuple[tuple[Decimal, ...], ...]:
    data = context.market_data
    return (
        decimal_prices(data.open_midpoints),
        decimal_prices(data.high_midpoints),
        decimal_prices(data.low_midpoints),
        decimal_prices(data.close_midpoints),
    )


def common_rejections(
    context: StrategyEvaluationContext, config: GovernedStrategyConfiguration
) -> tuple[StrategyDecision, tuple[str, ...]] | None:
    if len(context.market_data.timestamps) < config.minimum_history:
        return StrategyDecision.INSUFFICIENT_DATA, ("INSUFFICIENT_WARMUP_HISTORY",)
    if context.completed_bar_timestamp != context.market_data.timestamps[-1]:
        return StrategyDecision.STALE_DATA, ("STALE_OR_INCOMPLETE_BAR",)
    age = context.evaluation_timestamp - context.completed_bar_timestamp
    maximum = timedelta(seconds=context.timeframe.seconds * config.maximum_signal_age_bars)
    if age > maximum:
        return StrategyDecision.STALE_DATA, ("STALE_SIGNAL",)
    market = context.market_context
    reasons: list[str] = []
    if context.existing_position is None:
        reasons.append("UNKNOWN_POSITION_STATE")
    elif context.existing_position:
        reasons.append("EXISTING_POSITION")
    if market.context_quality is not ContextQuality.VALID:
        reasons.append("INVALID_MARKET_CONTEXT")
    if market.market_status.upper() != "TRADEABLE":
        reasons.append("MARKET_NOT_TRADEABLE")
    if market.spread_bps > config.maximum_spread_bps:
        reasons.append("EXCESSIVE_SPREAD")
    if market.liquidity_state not in {LiquidityState.HIGH, LiquidityState.NORMAL}:
        reasons.append("LIQUIDITY_INELIGIBLE")
    if market.session in {SessionState.CLOSED, SessionState.HOLIDAY_OR_THIN, SessionState.UNKNOWN}:
        reasons.append("SESSION_INELIGIBLE")
    if market.scheduled_event_state in {
        ScheduledEventState.PRE_EVENT,
        ScheduledEventState.INITIAL_REACTION,
        ScheduledEventState.POST_EVENT_STABILIZING,
        ScheduledEventState.UNKNOWN,
    }:
        reasons.append("EVENT_RISK_BLOCK")
    if reasons:
        return StrategyDecision.REJECT, tuple(reasons)
    return None


def rejected_result(
    *,
    evaluator: _EvaluatorIdentity,
    context: StrategyEvaluationContext,
    decision: StrategyDecision,
    reasons: tuple[str, ...],
) -> StrategyEvaluationResult:
    return strategy_result(
        evaluation_id=context.evaluation_id,
        strategy_id=evaluator.strategy_id,
        strategy_version=evaluator.strategy_version,
        strategy_fingerprint=evaluator.strategy_fingerprint,
        instrument_id=context.instrument_id,
        epic=context.epic,
        timeframe=context.timeframe,
        evaluation_timestamp=context.evaluation_timestamp,
        decision=decision,
        signal_strength=Decimal("0"),
        signal_confidence=Decimal("0"),
        rejection_reasons=reasons,
    )


def evaluator_fingerprint(strategy_id: str, version: str, config: object) -> str:
    return fingerprint({"strategy_id": strategy_id, "strategy_version": version, "config": config})
