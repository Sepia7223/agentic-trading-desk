"""Deterministic strategy registry with explicit research isolation."""

from __future__ import annotations

from datetime import UTC, datetime
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
        "strategy_code_fingerprint": "0" * 64,
        "indicator_definition_version": "portfolio-indicators-v1",
        "validation_report_id": None,
        "validation_dataset_fingerprint": None,
        "promotion_timestamp": None,
        "promotion_authority": None,
    }
    fields.update(overrides)
    identity = fingerprint(fields)
    return StrategyDescriptor.model_validate({**fields, "configuration_fingerprint": identity})


def default_strategies() -> tuple[StrategyDescriptor, ...]:
    return (
        _descriptor(
            "trend-regime-v1",
            ValidationStatus.DEMO_EXPLORATION_ENABLED,
            strategy_code_fingerprint=fingerprint("trend-regime-v1:1.0.0"),
            validation_report_id="milestone-3-validated-trend",
            validation_dataset_fingerprint=fingerprint("milestone-3-regression-evidence"),
            promotion_timestamp=datetime(2026, 7, 16, 13, 58, 19, tzinfo=UTC),
            promotion_authority="accepted-milestone-lineage",
        ),
        _descriptor(
            "trend-pullback-v1",
            ValidationStatus.RESEARCH_ONLY,
            strategy_code_fingerprint=fingerprint("trend-pullback-v1:1.0.0"),
            validation_report_id=(
                "48f60c07c11fc93994815318827f79173babaf47ea9df3a4a54463b44e3fc130"
            ),
            validation_dataset_fingerprint=(
                "5d8ae6e7a1f47f63c8395464c4f03ff761a6c7e84712e1c02e1c77dced04229d"
            ),
        ),
        _descriptor(
            "range-mean-reversion",
            ValidationStatus.RESEARCH_ONLY,
            strategy_code_fingerprint=fingerprint("range-mean-reversion:1.0.0"),
            eligible_trend_states=(TrendState.RANGE,),
            eligible_volatility_states=(VolatilityState.LOW, VolatilityState.NORMAL),
            validation_report_id=(
                "b307e0c6abcb0d5bb8c6e40656ee805fb2cd3da0aa7ff42c871d70f4da69db3d"
            ),
            validation_dataset_fingerprint=(
                "5d8ae6e7a1f47f63c8395464c4f03ff761a6c7e84712e1c02e1c77dced04229d"
            ),
        ),
        _descriptor(
            "volatility-breakout",
            ValidationStatus.RESEARCH_ONLY,
            strategy_code_fingerprint=fingerprint("volatility-breakout:1.0.0"),
            eligible_volatility_states=(VolatilityState.COMPRESSION, VolatilityState.EXPANSION),
            eligible_trend_states=tuple(TrendState),
            validation_report_id=(
                "dfc9707a43d12f16a03dbb494a91b894995a4ab220e9076b68006aab05f3e4c6"
            ),
            validation_dataset_fingerprint=(
                "5d8ae6e7a1f47f63c8395464c4f03ff761a6c7e84712e1c02e1c77dced04229d"
            ),
        ),
        _descriptor(
            "post-news-continuation",
            ValidationStatus.RESEARCH_ONLY,
            eligible_event_states=(ScheduledEventState.POST_EVENT_ELIGIBLE,),
            eligible_trend_states=(TrendState.STRONG_BULL_TREND, TrendState.WEAK_BULL_TREND),
        ),
        _descriptor(
            "donchian-breakout",
            ValidationStatus.RESEARCH_ONLY,
            strategy_code_fingerprint=fingerprint("donchian-breakout:1.0.0"),
            eligible_volatility_states=(
                VolatilityState.NORMAL,
                VolatilityState.HIGH,
                VolatilityState.EXPANSION,
            ),
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
