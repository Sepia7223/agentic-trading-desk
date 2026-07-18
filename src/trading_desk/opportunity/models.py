"""Strict immutable Opportunity Engine records."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.context.models import ContextTimeframe
from trading_desk.opportunity.fingerprints import fingerprint


class OpportunityModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def reject_floats(cls, value: object) -> object:
        if _contains_float(value):
            raise ValueError("binary floating point is prohibited in opportunity records")
        return value


class StrategyFamily(StrEnum):
    TREND_REGIME = "TREND_REGIME"
    TREND_PULLBACK = "TREND_PULLBACK"
    VOLATILITY_BREAKOUT = "VOLATILITY_BREAKOUT"
    RANGE_MEAN_REVERSION = "RANGE_MEAN_REVERSION"


class StrategyValidationState(StrEnum):
    RESEARCH_ONLY = "RESEARCH_ONLY"
    BACKTEST_VALIDATED = "BACKTEST_VALIDATED"
    DEMO_EXPLORATION_ENABLED = "DEMO_EXPLORATION_ENABLED"
    DISABLED = "DISABLED"


class CandidateDirection(StrEnum):
    LONG = "LONG"


class CandidateStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    REJECTED = "REJECTED"
    SUPPRESSED = "SUPPRESSED"
    SELECTED = "SELECTED"


class ConfidenceLabel(StrEnum):
    STRONG = "STRONG"
    STANDARD = "STANDARD"
    EXPLORATORY = "EXPLORATORY"
    REJECTED = "REJECTED"


class OpportunityRejectionCode(StrEnum):
    CONFIGURATION_DISABLED = "CONFIGURATION_DISABLED"
    STALE_CONTEXT = "STALE_CONTEXT"
    UNFINISHED_BAR = "UNFINISHED_BAR"
    UNSUPPORTED_TIMEFRAME = "UNSUPPORTED_TIMEFRAME"
    STRATEGY_NOT_EXECUTABLE = "STRATEGY_NOT_EXECUTABLE"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    NON_POSITIVE_EXPECTED_VALUE = "NON_POSITIVE_EXPECTED_VALUE"
    SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
    DATA_QUALITY_REJECTED = "DATA_QUALITY_REJECTED"
    DUPLICATE_CANDIDATE = "DUPLICATE_CANDIDATE"
    SAME_BAR_DUPLICATE = "SAME_BAR_DUPLICATE"
    LOWER_RANKED_SAME_INSTRUMENT = "LOWER_RANKED_SAME_INSTRUMENT"
    TIMEFRAME_SIGNAL_DUPLICATE = "TIMEFRAME_SIGNAL_DUPLICATE"
    STRATEGY_SIGNAL_DUPLICATE = "STRATEGY_SIGNAL_DUPLICATE"
    CORRELATED_EXPOSURE_LIMIT = "CORRELATED_EXPOSURE_LIMIT"
    CURRENCY_CONCENTRATION_LIMIT = "CURRENCY_CONCENTRATION_LIMIT"
    EXISTING_POSITION_CONFLICT = "EXISTING_POSITION_CONFLICT"
    RECENT_REENTRY_COOLDOWN = "RECENT_REENTRY_COOLDOWN"
    PORTFOLIO_EXPOSURE_LIMIT = "PORTFOLIO_EXPOSURE_LIMIT"


class StrategyPolicy(OpportunityModel):
    strategy_id: str
    strategy_version: str
    family: StrategyFamily
    states: tuple[StrategyValidationState, ...]
    supported_timeframes: tuple[ContextTimeframe, ...]
    fingerprint: str = Field(min_length=64, max_length=64)

    @property
    def demo_executable(self) -> bool:
        return {
            StrategyValidationState.BACKTEST_VALIDATED,
            StrategyValidationState.DEMO_EXPLORATION_ENABLED,
        }.issubset(set(self.states)) and StrategyValidationState.DISABLED not in self.states

    @model_validator(mode="after")
    def identity(self) -> Self:
        expected = fingerprint(self.model_dump(mode="python", exclude={"fingerprint"}))
        if expected != self.fingerprint:
            raise ValueError("strategy policy fingerprint mismatch")
        return self


class CandidateEvidence(OpportunityModel):
    created_at: datetime
    cycle_id: str
    instrument_id: str
    epic: str
    asset_class: Literal["FOREX"]
    timeframe: ContextTimeframe
    completed_bar_timestamp: datetime
    strategy: StrategyPolicy
    market_context_id: str
    market_context_fingerprint: str = Field(min_length=64, max_length=64)
    regime: str
    regime_confidence: Decimal = Field(ge=0, le=1)
    entry_reference_price: Decimal = Field(gt=0)
    proposed_stop: Decimal = Field(gt=0)
    proposed_target: Decimal = Field(gt=0)
    expected_holding_period: timedelta = Field(gt=timedelta(0))
    signal_strength: Decimal = Field(ge=0, le=1)
    signal_confidence: Decimal = Field(ge=0, le=1)
    estimated_win_probability: Decimal = Field(ge=0, le=1)
    estimated_loss_probability: Decimal = Field(ge=0, le=1)
    estimated_average_gain: Decimal = Field(gt=0)
    estimated_average_loss: Decimal = Field(gt=0)
    current_bid: Decimal = Field(gt=0)
    current_ask: Decimal = Field(gt=0)
    spread_observed_at: datetime
    liquidity_score: Decimal = Field(ge=0, le=1)
    volatility_score: Decimal = Field(ge=0, le=1)
    session_score: Decimal = Field(ge=0, le=1)
    event_risk_score: Decimal = Field(ge=0, le=1)
    data_quality_score: Decimal = Field(ge=0, le=1)
    uncertainty_score: Decimal = Field(ge=0, le=1)
    correlation_groups: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    @field_validator("created_at", "completed_bar_timestamp", "spread_observed_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("opportunity timestamps must be UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if self.completed_bar_timestamp >= self.created_at:
            raise ValueError("candidate requires a completed historical bar")
        if self.current_bid > self.current_ask:
            raise ValueError("candidate bid cannot exceed ask")
        if self.proposed_stop >= self.entry_reference_price:
            raise ValueError("long candidate stop must be below entry")
        if self.proposed_target <= self.entry_reference_price:
            raise ValueError("long candidate target must exceed entry")
        if self.estimated_win_probability + self.estimated_loss_probability != 1:
            raise ValueError("candidate probabilities must sum exactly to one")
        if not self.evidence_ids or len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("candidate evidence must be present and unique")
        return self


class CostEstimate(OpportunityModel):
    spread_estimate: Decimal = Field(gt=0)
    slippage_estimate: Decimal = Field(ge=0)
    commission_estimate: Decimal = Field(ge=0)
    funding_estimate: Decimal = Field(ge=0)
    uncertainty_penalty: Decimal = Field(ge=0)
    low_liquidity_surcharge: Decimal = Field(ge=0)
    event_risk_surcharge: Decimal = Field(ge=0)
    total_estimated_cost: Decimal = Field(gt=0)
    configuration_fingerprint: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def total(self) -> Self:
        expected = sum(
            (
                self.spread_estimate,
                self.slippage_estimate,
                self.commission_estimate,
                self.funding_estimate,
                self.uncertainty_penalty,
                self.low_liquidity_surcharge,
                self.event_risk_surcharge,
            ),
            Decimal("0"),
        )
        if self.total_estimated_cost != expected:
            raise ValueError("estimated cost total mismatch")
        return self


class OpportunityCandidate(OpportunityModel):
    candidate_id: str = Field(min_length=64, max_length=64)
    candidate_fingerprint: str = Field(min_length=64, max_length=64)
    created_at: datetime
    cycle_id: str
    instrument_id: str
    epic: str
    asset_class: Literal["FOREX"]
    timeframe: ContextTimeframe
    completed_bar_timestamp: datetime
    strategy_id: str
    strategy_version: str
    strategy_fingerprint: str
    strategy_family: StrategyFamily
    strategy_validation_states: tuple[StrategyValidationState, ...]
    market_context_id: str
    market_context_fingerprint: str
    regime: str
    regime_confidence: Decimal
    direction: CandidateDirection = CandidateDirection.LONG
    entry_reference_price: Decimal
    proposed_stop: Decimal
    proposed_target: Decimal
    expected_holding_period: timedelta
    signal_strength: Decimal
    signal_confidence: Decimal
    estimated_win_probability: Decimal
    estimated_loss_probability: Decimal
    estimated_average_gain: Decimal
    estimated_average_loss: Decimal
    current_bid: Decimal
    current_ask: Decimal
    gross_expected_value: Decimal
    costs: CostEstimate
    net_expected_value: Decimal
    reward_to_risk: Decimal = Field(gt=0)
    liquidity_score: Decimal
    volatility_score: Decimal
    session_score: Decimal
    event_risk_score: Decimal
    data_quality_score: Decimal
    uncertainty_score: Decimal
    correlation_groups: tuple[str, ...]
    opportunity_score: Decimal = Field(ge=0, le=100)
    confidence_label: ConfidenceLabel
    recommended_risk_multiplier: Decimal = Field(ge=0, le=1)
    status: CandidateStatus
    rejection_reasons: tuple[OpportunityRejectionCode, ...]
    evidence_ids: tuple[str, ...]

    @field_validator("created_at", "completed_bar_timestamp")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("opportunity timestamps must be UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def identity(self) -> Self:
        expected = fingerprint(
            self.model_dump(mode="python", exclude={"candidate_id", "candidate_fingerprint"})
        )
        if self.candidate_id != expected or self.candidate_fingerprint != expected:
            raise ValueError("opportunity candidate fingerprint mismatch")
        if self.status is CandidateStatus.ELIGIBLE and self.rejection_reasons:
            raise ValueError("eligible candidate cannot contain rejection reasons")
        return self


class OpportunityRanking(OpportunityModel):
    ranking_id: str = Field(min_length=64, max_length=64)
    ranking_fingerprint: str = Field(min_length=64, max_length=64)
    cycle_id: str
    created_at: datetime
    configuration_fingerprint: str
    ordered_candidate_ids: tuple[str, ...]
    selected_candidate_ids: tuple[str, ...]
    rejected_candidate_ids: tuple[str, ...]
    rejection_reasons: tuple[tuple[str, tuple[OpportunityRejectionCode, ...]], ...]

    @field_validator("created_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("ranking timestamp must be UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def identity(self) -> Self:
        expected = fingerprint(
            self.model_dump(mode="python", exclude={"ranking_id", "ranking_fingerprint"})
        )
        if self.ranking_id != expected or self.ranking_fingerprint != expected:
            raise ValueError("opportunity ranking fingerprint mismatch")
        return self


def create_strategy_policy(
    strategy_id: str,
    family: StrategyFamily,
    states: tuple[StrategyValidationState, ...],
    timeframes: tuple[ContextTimeframe, ...],
    version: str = "1.0.0",
) -> StrategyPolicy:
    fields = {
        "strategy_id": strategy_id,
        "strategy_version": version,
        "family": family,
        "states": states,
        "supported_timeframes": timeframes,
    }
    return StrategyPolicy.model_validate({**fields, "fingerprint": fingerprint(fields)})


def default_strategy_policies() -> tuple[StrategyPolicy, ...]:
    frames = (ContextTimeframe.MINUTE_5, ContextTimeframe.MINUTE_15, ContextTimeframe.HOUR)
    executable = (
        StrategyValidationState.BACKTEST_VALIDATED,
        StrategyValidationState.DEMO_EXPLORATION_ENABLED,
    )
    return (
        create_strategy_policy("trend-regime-v1", StrategyFamily.TREND_REGIME, executable, frames),
        create_strategy_policy(
            "trend-pullback-v1",
            StrategyFamily.TREND_PULLBACK,
            (StrategyValidationState.RESEARCH_ONLY,),
            frames,
        ),
        create_strategy_policy(
            "volatility-breakout-v1",
            StrategyFamily.VOLATILITY_BREAKOUT,
            (StrategyValidationState.RESEARCH_ONLY,),
            frames,
        ),
        create_strategy_policy(
            "range-mean-reversion-v1",
            StrategyFamily.RANGE_MEAN_REVERSION,
            (StrategyValidationState.RESEARCH_ONLY,),
            frames,
        ),
    )


def _contains_float(value: object) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_contains_float(item) for item in value.values())
    if isinstance(value, (tuple, list)):
        return any(_contains_float(item) for item in value)
    return False
