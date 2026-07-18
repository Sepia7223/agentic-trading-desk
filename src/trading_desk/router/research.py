"""Deterministic, non-executable evaluation of research-only strategies."""

from __future__ import annotations

from decimal import Decimal

from trading_desk.context.fingerprints import fingerprint
from trading_desk.context.models import (
    BreakoutState,
    MarketContextSnapshot,
    RangeState,
    ScheduledEventState,
    VolatilityState,
)
from trading_desk.router.models import ResearchStrategyResult
from trading_desk.strategy.contracts import StrategyDecision, evaluation_context
from trading_desk.strategy.models import StrategyMarketData
from trading_desk.strategy.portfolio_registry import PortfolioStrategyRegistry


def evaluate_research_strategy(
    strategy_id: str,
    context: MarketContextSnapshot,
    data: StrategyMarketData,
) -> ResearchStrategyResult:
    """Evaluate a frozen research hypothesis without creating a TradeCandidate."""
    if strategy_id != "post-news-continuation":
        evaluator = PortfolioStrategyRegistry().require(strategy_id)
        result = evaluator.evaluate(
            context=evaluation_context(
                evaluation_timestamp=context.evaluation_timestamp,
                instrument_id=context.instrument,
                epic=context.epic,
                timeframe=context.timeframe,
                completed_bar_timestamp=context.data_cutoff_timestamp,
                market_data=data,
                higher_timeframe_data=None,
                market_context=context,
                existing_position=False,
                strategy_configuration_fingerprint=evaluator.strategy_fingerprint,
            )
        )
        portfolio_observed = tuple(
            (item.name, item.value) for item in result.evidence if isinstance(item.value, Decimal)
        )
        portfolio_fields: dict[str, object] = {
            "strategy_id": strategy_id,
            "context_id": context.context_id,
            "evaluation_timestamp": context.evaluation_timestamp,
            "trigger_observed": result.decision is StrategyDecision.CANDIDATE,
            "reasons": result.rejection_reasons,
            "observed_values": portfolio_observed,
            "executable": False,
        }
        return ResearchStrategyResult.model_validate(
            {
                **portfolio_fields,
                "research_result_id": fingerprint(portfolio_fields),
            }
        )

    reasons: list[str] = []
    trigger = False
    observed: tuple[tuple[str, Decimal], ...] = ()
    if len(data.close_midpoints) < 21:
        reasons.append("insufficient_research_history")
    else:
        close = Decimal(str(data.close_midpoints[-1]))
        prior_high = Decimal(str(max(data.high_midpoints[-21:-1])))
        prior_low = Decimal(str(min(data.low_midpoints[-21:-1])))
        width = prior_high - prior_low
        range_location = (close - prior_low) / width if width > 0 else Decimal("0.5")
        observed = (
            ("close", close),
            ("prior_high", prior_high),
            ("prior_low", prior_low),
            ("range_location", range_location),
        )
        if strategy_id == "range-mean-reversion":
            trigger = context.range_state is RangeState.ESTABLISHED and range_location <= Decimal(
                "0.2"
            )
            if not trigger:
                reasons.append("no_lower_range_boundary_trigger")
        elif strategy_id == "volatility-breakout":
            trigger = (
                context.breakout_state is BreakoutState.CONFIRMED_UP
                and context.volatility_state is VolatilityState.EXPANSION
            )
            if not trigger:
                reasons.append("no_completed_bar_upside_breakout")
        elif strategy_id == "post-news-continuation":
            trigger = (
                context.scheduled_event_state is ScheduledEventState.POST_EVENT_ELIGIBLE
                and close > prior_high
            )
            if not trigger:
                reasons.append("no_post_event_continuation_confirmation")
        else:
            reasons.append("unknown_research_strategy")
    fields: dict[str, object] = {
        "strategy_id": strategy_id,
        "context_id": context.context_id,
        "evaluation_timestamp": context.evaluation_timestamp,
        "trigger_observed": trigger,
        "reasons": tuple(reasons),
        "observed_values": observed,
        "executable": False,
    }
    return ResearchStrategyResult.model_validate(
        {**fields, "research_result_id": fingerprint(fields)}
    )
