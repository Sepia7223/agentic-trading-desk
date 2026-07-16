"""Deterministic strategy registry with explicit research isolation."""

from __future__ import annotations

from decimal import Decimal

from trading_desk.context.fingerprints import fingerprint
from trading_desk.context.models import (
    ContextTimeframe,
    LiquidityState,
    ScheduledEventState,
    SessionState,
    TrendState,
    VolatilityState,
)
from trading_desk.router.errors import DuplicateStrategyError
from trading_desk.router.models import Direction, StrategyDescriptor, ValidationStatus


def _descriptor(
    strategy_id: str, status: ValidationStatus, **overrides: object
) -> StrategyDescriptor:
    fields: dict[str, object] = {
        "strategy_id": strategy_id,
        "strategy_version": "1.0.0",
        "supported_instruments": ("*",),
        "supported_timeframes": tuple(ContextTimeframe),
        "supported_directions": (Direction.LONG,),
        "required_history": 220,
        "eligible_sessions": (
            SessionState.ASIA,
            SessionState.LONDON,
            SessionState.NEW_YORK,
            SessionState.LONDON_NEW_YORK_OVERLAP,
        ),
        "eligible_liquidity_states": (LiquidityState.HIGH, LiquidityState.NORMAL),
        "eligible_volatility_states": (
            VolatilityState.LOW,
            VolatilityState.NORMAL,
            VolatilityState.HIGH,
        ),
        "eligible_trend_states": (TrendState.STRONG_BULL_TREND, TrendState.WEAK_BULL_TREND),
        "eligible_event_states": (
            ScheduledEventState.NO_EVENT,
            ScheduledEventState.POST_EVENT_ELIGIBLE,
            ScheduledEventState.STALE_EVENT,
        ),
        "maximum_spread_bps": Decimal("10"),
        "validation_status": status,
    }
    fields.update(overrides)
    identity = fingerprint(fields)
    return StrategyDescriptor.model_validate({**fields, "configuration_fingerprint": identity})


def default_strategies() -> tuple[StrategyDescriptor, ...]:
    return (
        _descriptor("trend-regime-v1", ValidationStatus.VALIDATED),
        _descriptor(
            "range-mean-reversion",
            ValidationStatus.RESEARCH_ONLY,
            eligible_trend_states=(TrendState.RANGE,),
            eligible_volatility_states=(VolatilityState.LOW, VolatilityState.NORMAL),
        ),
        _descriptor(
            "volatility-breakout",
            ValidationStatus.RESEARCH_ONLY,
            eligible_volatility_states=(VolatilityState.COMPRESSION, VolatilityState.EXPANSION),
            eligible_trend_states=tuple(TrendState),
        ),
        _descriptor(
            "post-news-continuation",
            ValidationStatus.RESEARCH_ONLY,
            eligible_event_states=(ScheduledEventState.POST_EVENT_ELIGIBLE,),
            eligible_trend_states=(TrendState.STRONG_BULL_TREND, TrendState.WEAK_BULL_TREND),
        ),
    )


class StrategyRegistry:
    def __init__(self, strategies: tuple[StrategyDescriptor, ...] | None = None) -> None:
        values = tuple(
            StrategyDescriptor.model_validate(item.model_dump(mode="python"))
            for item in (strategies or default_strategies())
        )
        identifiers = [item.strategy_id for item in values]
        if len(identifiers) != len(set(identifiers)):
            raise DuplicateStrategyError("strategy identifiers must be unique")
        self._strategies = tuple(sorted(values, key=lambda item: item.strategy_id))

    @property
    def strategies(self) -> tuple[StrategyDescriptor, ...]:
        return self._strategies
