from datetime import timedelta

import pytest
from pydantic import ValidationError

from context_helpers import kalman, market_data, regime, snapshot
from trading_desk.context.classifier import MarketContextEngine
from trading_desk.context.config import MarketContextConfiguration
from trading_desk.context.models import (
    ContextQuality,
    ContextReasonCode,
    ContextTimeframe,
    LiquidityState,
    ScheduledEventState,
    TrendState,
    VolatilityState,
)
from trading_desk.router.config import RouterConfiguration
from trading_desk.router.engine import StrategyRouter
from trading_desk.router.models import RouteStatus, ValidationStatus
from trading_desk.router.registry import StrategyRegistry, default_strategies
from trading_desk.strategy.models import Regime, StrategyContext


def test_context_is_deterministic_and_future_append_does_not_change_cutoff() -> None:
    data = market_data()
    engine = MarketContextEngine(
        MarketContextConfiguration(minimum_history=30, volatility_window=5)
    )
    first = engine.classify(
        data,
        kalman(),
        regime(),
        evaluation_timestamp=data.timestamps[-1],
        timeframe=ContextTimeframe.HOUR,
    )
    second = engine.classify(
        data,
        kalman(),
        regime(),
        evaluation_timestamp=data.timestamps[-1],
        timeframe=ContextTimeframe.HOUR,
    )
    assert first == second
    assert first.context_fingerprint == second.context_fingerprint


def test_context_marks_stale_unknown_and_abnormal_inputs_invalid() -> None:
    data = market_data(spread_bps=25)
    result = MarketContextEngine(
        MarketContextConfiguration(minimum_history=30, volatility_window=5)
    ).classify(
        data,
        kalman(ready=False),
        regime(ready=False),
        evaluation_timestamp=data.timestamps[-1] + timedelta(hours=3),
        timeframe=ContextTimeframe.HOUR,
    )
    assert result.context_quality is ContextQuality.INVALID
    assert ContextReasonCode.STALE_DATA in result.reason_codes
    assert ContextReasonCode.ABNORMAL_SPREAD in result.reason_codes
    assert result.trend_state is TrendState.UNKNOWN


def test_bear_regime_is_high_volatility_disorder() -> None:
    data = market_data()
    result = MarketContextEngine(
        MarketContextConfiguration(minimum_history=30, volatility_window=5)
    ).classify(
        data,
        kalman(),
        regime(Regime.BEAR_HIGH_VOL),
        evaluation_timestamp=data.timestamps[-1],
        timeframe=ContextTimeframe.HOUR,
    )
    assert result.trend_state is TrendState.HIGH_VOLATILITY_DISORDER


def test_validated_trend_strategy_is_selected() -> None:
    decision = StrategyRouter().route(snapshot(), history_size=300)
    assert decision.route_status is RouteStatus.STRATEGY_SELECTED
    assert decision.selected_strategy_id == "trend-regime-v1"


@pytest.mark.parametrize(
    ("updates", "research_id"),
    [
        (
            {"trend_state": TrendState.RANGE, "volatility_state": VolatilityState.NORMAL},
            "range-mean-reversion",
        ),
        (
            {
                "trend_state": TrendState.TRANSITION,
                "volatility_state": VolatilityState.COMPRESSION,
            },
            "volatility-breakout",
        ),
        (
            {"scheduled_event_state": ScheduledEventState.POST_EVENT_ELIGIBLE},
            "post-news-continuation",
        ),
    ],
)
def test_research_strategies_never_become_selected(
    updates: dict[str, object], research_id: str
) -> None:
    decision = StrategyRouter().route(snapshot(**updates), history_size=300)
    assert research_id in decision.research_only_strategies
    assert decision.selected_strategy_id != research_id


def test_invalid_and_halted_context_routes_to_capital_preservation() -> None:
    context = snapshot(
        context_quality=ContextQuality.INVALID,
        liquidity_state=LiquidityState.ABNORMAL,
        reason_codes=(ContextReasonCode.ABNORMAL_SPREAD,),
    )
    decision = StrategyRouter().route(context, history_size=300, execution_halted=True)
    assert decision.route_status is RouteStatus.INVALID_CONTEXT
    assert decision.selected_strategy_id is None


def test_router_priority_and_identity_are_deterministic() -> None:
    descriptors = tuple(
        item.model_copy(update={"validation_status": ValidationStatus.VALIDATED})
        if item.strategy_id == "post-news-continuation"
        else item
        for item in default_strategies()
    )
    # Re-fingerprint the promoted fixture to model a separately reviewed promotion.
    promoted = []
    from trading_desk.context.fingerprints import fingerprint

    for item in descriptors:
        fields = item.model_dump(mode="python", exclude={"configuration_fingerprint"})
        promoted.append(item.model_copy(update={"configuration_fingerprint": fingerprint(fields)}))
    router = StrategyRouter(StrategyRegistry(tuple(promoted)), RouterConfiguration())
    context = snapshot(scheduled_event_state=ScheduledEventState.POST_EVENT_ELIGIBLE)
    first = router.route(context, history_size=300)
    second = router.route(context, history_size=300)
    assert first == second
    assert first.selected_strategy_id == "post-news-continuation"

    rejected = StrategyRouter(
        StrategyRegistry(tuple(promoted)),
        RouterConfiguration(reject_ambiguous_priority=True),
    ).route(context, history_size=300)
    assert rejected.selected_strategy_id is None
    assert "CONFLICTING_CONTEXT" in {item.value for item in rejected.reason_codes}


def test_strategy_fingerprint_mismatch_is_rejected() -> None:
    fields = default_strategies()[0].model_dump(mode="python")
    fields["configuration_fingerprint"] = "0" * 64
    with pytest.raises(ValidationError, match="fingerprint mismatch"):
        type(default_strategies()[0]).model_validate(fields)


def test_disabled_rejected_unsupported_and_history_checks() -> None:
    strategies = default_strategies()
    disabled_fields = strategies[0].model_dump(mode="python", exclude={"configuration_fingerprint"})
    disabled_fields["validation_status"] = ValidationStatus.DISABLED
    from trading_desk.context.fingerprints import fingerprint
    from trading_desk.router.models import StrategyDescriptor

    disabled = StrategyDescriptor.model_validate(
        {**disabled_fields, "configuration_fingerprint": fingerprint(disabled_fields)}
    )
    decision = StrategyRouter(StrategyRegistry((disabled,))).route(snapshot(), history_size=1)
    assert decision.selected_strategy_id is None
    assert decision.route_status is RouteStatus.CAPITAL_PRESERVATION


def test_only_validated_route_can_invoke_strategy_pipeline() -> None:
    data = market_data(count=230)
    strategy_context = StrategyContext(
        holding=False,
        macro_score=1,
        current_spread=data.spreads[-1],
        current_spread_bps=data.spread_bps[-1],
        market_status=data.market_status,
        current_time=data.timestamps[-1],
    )
    selected = StrategyRouter().evaluate_validated_strategy(snapshot(), data, strategy_context)
    research = StrategyRouter().evaluate_validated_strategy(
        snapshot(trend_state=TrendState.RANGE), data, strategy_context
    )
    assert selected.decision.selected_strategy_id == "trend-regime-v1"
    assert selected.candidate is not None
    assert research.decision.selected_strategy_id is None
    assert research.candidate is None
    assert research.research_results
    assert all(not item.executable for item in research.research_results)


def test_research_evaluation_is_deterministic_and_cannot_create_candidate() -> None:
    data = market_data(count=230, slope=0)
    strategy_context = StrategyContext(
        holding=False,
        macro_score=0,
        current_spread=data.spreads[-1],
        current_spread_bps=data.spread_bps[-1],
        market_status=data.market_status,
        current_time=data.timestamps[-1],
    )
    context = snapshot(trend_state=TrendState.RANGE, range_state="ESTABLISHED")
    first = StrategyRouter().evaluate_validated_strategy(context, data, strategy_context)
    second = StrategyRouter().evaluate_validated_strategy(context, data, strategy_context)
    assert first == second
    assert first.candidate is None
    assert {item.strategy_id for item in first.research_results} == {"range-mean-reversion"}
