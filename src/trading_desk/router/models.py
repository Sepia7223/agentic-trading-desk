"""Strict strategy metadata and immutable routing decisions."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.context.models import (
    ContextTimeframe,
    LiquidityState,
    ScheduledEventState,
    SessionState,
    TrendState,
    VolatilityState,
)
from trading_desk.router.fingerprints import fingerprint
from trading_desk.strategy.models import TradeCandidate


class RouterModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class ValidationStatus(StrEnum):
    VALIDATED = "VALIDATED"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    DISABLED = "DISABLED"
    REJECTED = "REJECTED"


class RouteStatus(StrEnum):
    STRATEGY_SELECTED = "STRATEGY_SELECTED"
    CAPITAL_PRESERVATION = "CAPITAL_PRESERVATION"
    RESEARCH_EVALUATION_ONLY = "RESEARCH_EVALUATION_ONLY"
    INVALID_CONTEXT = "INVALID_CONTEXT"


class Direction(StrEnum):
    LONG = "LONG"


class CapitalPreservationReason(StrEnum):
    NO_VALIDATED_STRATEGY = "NO_VALIDATED_STRATEGY"
    LOW_LIQUIDITY = "LOW_LIQUIDITY"
    ABNORMAL_SPREAD = "ABNORMAL_SPREAD"
    EXTREME_VOLATILITY = "EXTREME_VOLATILITY"
    REGIME_TRANSITION = "REGIME_TRANSITION"
    PRE_HIGH_IMPACT_EVENT = "PRE_HIGH_IMPACT_EVENT"
    INITIAL_NEWS_REACTION = "INITIAL_NEWS_REACTION"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    CONFLICTING_CONTEXT = "CONFLICTING_CONTEXT"
    STALE_CONTEXT = "STALE_CONTEXT"
    MARKET_CLOSED = "MARKET_CLOSED"
    UNRESOLVED_EXECUTION = "UNRESOLVED_EXECUTION"
    INTEGRITY_FAILURE = "INTEGRITY_FAILURE"


class StrategyDescriptor(RouterModel):
    strategy_id: str
    strategy_version: str
    supported_instruments: tuple[str, ...]
    supported_timeframes: tuple[ContextTimeframe, ...]
    supported_directions: tuple[Direction, ...] = (Direction.LONG,)
    required_history: int = Field(ge=1)
    eligible_sessions: tuple[SessionState, ...]
    eligible_liquidity_states: tuple[LiquidityState, ...]
    eligible_volatility_states: tuple[VolatilityState, ...]
    eligible_trend_states: tuple[TrendState, ...]
    eligible_event_states: tuple[ScheduledEventState, ...]
    maximum_spread_bps: Decimal = Field(gt=0)
    configuration_fingerprint: str = Field(min_length=64, max_length=64)
    validation_status: ValidationStatus

    @model_validator(mode="after")
    def validate_fingerprint(self) -> Self:
        expected = fingerprint(
            self.model_dump(mode="python", exclude={"configuration_fingerprint"})
        )
        if self.configuration_fingerprint != expected:
            raise ValueError("strategy configuration fingerprint mismatch")
        return self


class StrategyEligibility(RouterModel):
    strategy_id: str
    eligible: bool
    reasons: tuple[str, ...]


class StrategyRouterDecision(RouterModel):
    router_decision_id: str = Field(min_length=64, max_length=64)
    instrument: str
    evaluation_timestamp: datetime
    context_id: str
    selected_strategy_id: str | None
    selected_strategy_version: str | None
    route_status: RouteStatus
    eligible_strategies: tuple[str, ...]
    ineligible_strategies: tuple[str, ...]
    research_only_strategies: tuple[str, ...]
    reason_codes: tuple[CapitalPreservationReason, ...]
    context_fingerprint: str
    router_configuration_fingerprint: str
    decision_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("evaluation_timestamp")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("router timestamp must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        fields = self.model_dump(
            mode="python", exclude={"router_decision_id", "decision_fingerprint"}
        )
        expected = fingerprint(fields)
        if self.router_decision_id != expected or self.decision_fingerprint != expected:
            raise ValueError("router decision fingerprint mismatch")
        if self.route_status is RouteStatus.STRATEGY_SELECTED and not self.selected_strategy_id:
            raise ValueError("selected route requires a strategy")
        return self


class RoutedStrategyResult(RouterModel):
    decision: StrategyRouterDecision
    candidate: TradeCandidate | None
    research_results: tuple[ResearchStrategyResult, ...] = ()

    @model_validator(mode="after")
    def candidate_matches_route(self) -> Self:
        if self.candidate is not None and self.decision.selected_strategy_id != "trend-regime-v1":
            raise ValueError("candidate may only come from the validated trend strategy")
        if self.decision.route_status is not RouteStatus.STRATEGY_SELECTED and self.candidate:
            raise ValueError("non-selected routes cannot produce candidates")
        if any(item.executable for item in self.research_results):
            raise ValueError("research results can never be executable")
        return self


class ResearchStrategyResult(RouterModel):
    research_result_id: str = Field(min_length=64, max_length=64)
    strategy_id: str
    context_id: str
    evaluation_timestamp: datetime
    trigger_observed: bool
    reasons: tuple[str, ...]
    observed_values: tuple[tuple[str, Decimal], ...]
    executable: bool = False

    @model_validator(mode="after")
    def validate_research_boundary(self) -> Self:
        if self.executable:
            raise ValueError("research strategy results are non-executable")
        fields = self.model_dump(mode="python", exclude={"research_result_id"})
        if self.research_result_id != fingerprint(fields):
            raise ValueError("research result fingerprint mismatch")
        return self
