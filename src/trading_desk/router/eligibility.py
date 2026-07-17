"""Pure strategy eligibility checks."""

from trading_desk.context.models import ContextQuality, MarketContextSnapshot
from trading_desk.router.models import StrategyDescriptor, StrategyEligibility, ValidationStatus


def evaluate_eligibility(
    strategy: StrategyDescriptor,
    context: MarketContextSnapshot,
    *,
    history_size: int,
    integrity_ok: bool = True,
    execution_halted: bool = False,
) -> StrategyEligibility:
    reasons: list[str] = []
    if strategy.validation_status in {ValidationStatus.DISABLED, ValidationStatus.REJECTED}:
        reasons.append(f"status:{strategy.validation_status.value}")
    if context.context_quality is ContextQuality.INVALID:
        reasons.append("invalid_context")
    if (
        "*" not in strategy.supported_instruments
        and context.epic not in strategy.supported_instruments
    ):
        reasons.append("unsupported_instrument")
    if context.timeframe not in strategy.supported_timeframes:
        reasons.append("unsupported_timeframe")
    if history_size < strategy.required_history:
        reasons.append("insufficient_history")
    if context.session not in strategy.eligible_sessions:
        reasons.append("ineligible_session")
    if context.liquidity_state not in strategy.eligible_liquidity_states:
        reasons.append("ineligible_liquidity")
    if context.volatility_state not in strategy.eligible_volatility_states:
        reasons.append("ineligible_volatility")
    if context.trend_state not in strategy.eligible_trend_states:
        reasons.append("ineligible_trend")
    if context.scheduled_event_state not in strategy.eligible_event_states:
        reasons.append("event_block")
    if context.spread_bps > strategy.maximum_spread_bps:
        reasons.append("spread_too_wide")
    if not integrity_ok:
        reasons.append("integrity_failure")
    if execution_halted:
        reasons.append("execution_halted")
    return StrategyEligibility(
        strategy_id=strategy.strategy_id,
        eligible=not reasons,
        reasons=tuple(reasons),
    )
