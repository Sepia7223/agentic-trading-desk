"""Deterministic routing; only validated strategies can be selected."""

from __future__ import annotations

from trading_desk.context.models import ContextQuality, ContextReasonCode, MarketContextSnapshot
from trading_desk.router.config import RouterConfiguration
from trading_desk.router.eligibility import evaluate_eligibility
from trading_desk.router.fingerprints import fingerprint
from trading_desk.router.models import (
    CapitalPreservationReason,
    RoutedStrategyResult,
    RouteStatus,
    StrategyRouterDecision,
    ValidationStatus,
)
from trading_desk.router.registry import StrategyRegistry
from trading_desk.router.research import evaluate_research_strategy
from trading_desk.router.selection import select_strategy
from trading_desk.strategy.models import StrategyContext, StrategyMarketData, TradeCandidate
from trading_desk.strategy.pipeline import RegimeAwareStrategyPipeline


class StrategyRouter:
    def __init__(
        self,
        registry: StrategyRegistry | None = None,
        config: RouterConfiguration | None = None,
    ) -> None:
        self.registry = registry or StrategyRegistry()
        self.config = config or RouterConfiguration()

    def route(
        self,
        context: MarketContextSnapshot,
        *,
        history_size: int,
        integrity_ok: bool = True,
        execution_halted: bool = False,
    ) -> StrategyRouterDecision:
        assessments = tuple(
            evaluate_eligibility(
                item,
                context,
                history_size=history_size,
                integrity_ok=integrity_ok,
                execution_halted=execution_halted,
            )
            for item in self.registry.strategies
        )
        by_id = {item.strategy_id: item for item in self.registry.strategies}
        validated = tuple(
            item.strategy_id
            for item in assessments
            if item.eligible
            and by_id[item.strategy_id].validation_status is ValidationStatus.VALIDATED
        )
        research = tuple(
            item.strategy_id
            for item in assessments
            if item.eligible
            and by_id[item.strategy_id].validation_status is ValidationStatus.RESEARCH_ONLY
        )
        selected = select_strategy(validated, self.config)
        if context.context_quality is ContextQuality.INVALID:
            status = RouteStatus.INVALID_CONTEXT
        elif selected:
            status = RouteStatus.STRATEGY_SELECTED
        elif research:
            status = RouteStatus.RESEARCH_EVALUATION_ONLY
        else:
            status = RouteStatus.CAPITAL_PRESERVATION
        reasons = _capital_reasons(context, integrity_ok, execution_halted)
        if len(validated) > 1 and self.config.reject_ambiguous_priority:
            reasons = (*reasons, CapitalPreservationReason.CONFLICTING_CONTEXT)
        if not selected and not reasons:
            reasons = (CapitalPreservationReason.NO_VALIDATED_STRATEGY,)
        selected_descriptor = by_id[selected] if selected else None
        fields: dict[str, object] = {
            "instrument": context.instrument,
            "evaluation_timestamp": context.evaluation_timestamp,
            "context_id": context.context_id,
            "selected_strategy_id": selected,
            "selected_strategy_version": selected_descriptor.strategy_version
            if selected_descriptor
            else None,
            "route_status": status,
            "eligible_strategies": validated,
            "ineligible_strategies": tuple(
                item.strategy_id for item in assessments if not item.eligible
            ),
            "research_only_strategies": research,
            "reason_codes": reasons,
            "context_fingerprint": context.context_fingerprint,
            "router_configuration_fingerprint": self.config.configuration_fingerprint,
        }
        identity = fingerprint(fields)
        return StrategyRouterDecision.model_validate(
            {**fields, "router_decision_id": identity, "decision_fingerprint": identity}
        )

    def evaluate_validated_strategy(
        self,
        context_snapshot: MarketContextSnapshot,
        market_data: StrategyMarketData,
        strategy_context: StrategyContext,
        *,
        integrity_ok: bool = True,
        execution_halted: bool = False,
        pipeline: RegimeAwareStrategyPipeline | None = None,
    ) -> RoutedStrategyResult:
        decision = self.route(
            context_snapshot,
            history_size=len(market_data.timestamps),
            integrity_ok=integrity_ok,
            execution_halted=execution_halted,
        )
        candidate = None
        if decision.selected_strategy_id == "trend-regime-v1":
            candidate = (pipeline or RegimeAwareStrategyPipeline()).analyze_latest(
                market_data, strategy_context
            )
        research_results = tuple(
            evaluate_research_strategy(identifier, context_snapshot, market_data)
            for identifier in decision.research_only_strategies
        )
        return RoutedStrategyResult(
            decision=decision,
            candidate=candidate,
            research_results=research_results,
        )

    def route_candidate(
        self,
        context_snapshot: MarketContextSnapshot,
        market_data: StrategyMarketData,
        candidate: TradeCandidate,
        *,
        integrity_ok: bool = True,
        execution_halted: bool = False,
    ) -> RoutedStrategyResult:
        if candidate.epic != context_snapshot.epic or candidate.epic != market_data.epic:
            raise ValueError("candidate and context instrument mismatch")
        decision = self.route(
            context_snapshot,
            history_size=len(market_data.timestamps),
            integrity_ok=integrity_ok,
            execution_halted=execution_halted,
        )
        routed_candidate = candidate if decision.selected_strategy_id == "trend-regime-v1" else None
        research_results = tuple(
            evaluate_research_strategy(identifier, context_snapshot, market_data)
            for identifier in decision.research_only_strategies
        )
        return RoutedStrategyResult(
            decision=decision,
            candidate=routed_candidate,
            research_results=research_results,
        )


def _capital_reasons(
    context: MarketContextSnapshot, integrity_ok: bool, execution_halted: bool
) -> tuple[CapitalPreservationReason, ...]:
    mapping = {
        ContextReasonCode.LOW_LIQUIDITY: CapitalPreservationReason.LOW_LIQUIDITY,
        ContextReasonCode.ABNORMAL_SPREAD: CapitalPreservationReason.ABNORMAL_SPREAD,
        ContextReasonCode.EXTREME_VOLATILITY: CapitalPreservationReason.EXTREME_VOLATILITY,
        ContextReasonCode.REGIME_TRANSITION: CapitalPreservationReason.REGIME_TRANSITION,
        ContextReasonCode.PRE_HIGH_IMPACT_EVENT: CapitalPreservationReason.PRE_HIGH_IMPACT_EVENT,
        ContextReasonCode.INITIAL_NEWS_REACTION: CapitalPreservationReason.INITIAL_NEWS_REACTION,
        ContextReasonCode.INSUFFICIENT_HISTORY: CapitalPreservationReason.INSUFFICIENT_HISTORY,
        ContextReasonCode.STALE_DATA: CapitalPreservationReason.STALE_CONTEXT,
        ContextReasonCode.MARKET_CLOSED: CapitalPreservationReason.MARKET_CLOSED,
    }
    values = [mapping[item] for item in context.reason_codes if item in mapping]
    if not integrity_ok:
        values.append(CapitalPreservationReason.INTEGRITY_FAILURE)
    if execution_halted:
        values.append(CapitalPreservationReason.UNRESOLVED_EXECUTION)
    return tuple(dict.fromkeys(values))
