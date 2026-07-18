"""Deterministic inactivity funnel diagnostics; never configuration mutation."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.opportunity.fingerprints import fingerprint


class InactivityBottleneck(StrEnum):
    INSUFFICIENT_MARKET_COVERAGE = "INSUFFICIENT_MARKET_COVERAGE"
    NO_REGIME_ELIGIBLE_STRATEGY = "NO_REGIME_ELIGIBLE_STRATEGY"
    STRATEGY_SIGNAL_TOO_RARE = "STRATEGY_SIGNAL_TOO_RARE"
    TRANSACTION_COST_TOO_HIGH = "TRANSACTION_COST_TOO_HIGH"
    MARKET_DATA_QUALITY_FAILURES = "MARKET_DATA_QUALITY_FAILURES"
    CORRELATION_FILTER_DOMINANT = "CORRELATION_FILTER_DOMINANT"
    RISK_REJECTIONS_DOMINANT = "RISK_REJECTIONS_DOMINANT"
    EXECUTION_PREFLIGHT_FAILURES = "EXECUTION_PREFLIGHT_FAILURES"
    EVENT_FILTER_DOMINANT = "EVENT_FILTER_DOMINANT"
    SYSTEM_HALTED = "SYSTEM_HALTED"
    NORMAL_LOW_OPPORTUNITY_PERIOD = "NORMAL_LOW_OPPORTUNITY_PERIOD"


class ActivityCounters(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    markets_scanned: int = Field(default=0, ge=0)
    instrument_timeframes_evaluated: int = Field(default=0, ge=0)
    strategy_evaluations: int = Field(default=0, ge=0)
    eligible_strategy_evaluations: int = Field(default=0, ge=0)
    research_only_strategy_evaluations: int = Field(default=0, ge=0)
    backtest_validated_evaluations: int = Field(default=0, ge=0)
    demo_executable_evaluations: int = Field(default=0, ge=0)
    ineligible_regime_evaluations: int = Field(default=0, ge=0)
    candidate_producing_evaluations: int = Field(default=0, ge=0)
    candidates_created: int = Field(default=0, ge=0)
    positive_expected_value_candidates: int = Field(default=0, ge=0)
    candidates_rejected_by_context: int = Field(default=0, ge=0)
    candidates_rejected_by_strategy: int = Field(default=0, ge=0)
    candidates_rejected_by_cost: int = Field(default=0, ge=0)
    candidates_rejected_by_data_quality: int = Field(default=0, ge=0)
    candidates_rejected_by_correlation: int = Field(default=0, ge=0)
    candidates_rejected_by_risk: int = Field(default=0, ge=0)
    candidates_rejected_by_execution_preflight: int = Field(default=0, ge=0)
    trades_submitted: int = Field(default=0, ge=0)
    trades_confirmed: int = Field(default=0, ge=0)
    positions_closed: int = Field(default=0, ge=0)


class InactivityDiagnostic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    diagnostic_id: str = Field(min_length=64, max_length=64)
    created_at: datetime
    period: str
    counters: ActivityCounters
    dominant_bottleneck: InactivityBottleneck
    human_review_recommended: bool
    automatic_configuration_change: bool = False
    diagnostic_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("created_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("diagnostic timestamp must be UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def identity(self) -> Self:
        if self.automatic_configuration_change:
            raise ValueError("inactivity diagnostics cannot change configuration")
        expected = fingerprint(
            self.model_dump(mode="python", exclude={"diagnostic_id", "diagnostic_fingerprint"})
        )
        if self.diagnostic_id != expected or self.diagnostic_fingerprint != expected:
            raise ValueError("diagnostic fingerprint mismatch")
        return self


def diagnose_inactivity(
    created_at: datetime,
    period: str,
    counters: ActivityCounters,
    *,
    system_halted: bool = False,
) -> InactivityDiagnostic:
    if system_halted:
        bottleneck = InactivityBottleneck.SYSTEM_HALTED
    else:
        weighted = (
            (counters.candidates_rejected_by_context, InactivityBottleneck.EVENT_FILTER_DOMINANT),
            (
                counters.candidates_rejected_by_strategy,
                InactivityBottleneck.NO_REGIME_ELIGIBLE_STRATEGY,
            ),
            (counters.candidates_rejected_by_cost, InactivityBottleneck.TRANSACTION_COST_TOO_HIGH),
            (
                counters.candidates_rejected_by_data_quality,
                InactivityBottleneck.MARKET_DATA_QUALITY_FAILURES,
            ),
            (
                counters.candidates_rejected_by_correlation,
                InactivityBottleneck.CORRELATION_FILTER_DOMINANT,
            ),
            (counters.candidates_rejected_by_risk, InactivityBottleneck.RISK_REJECTIONS_DOMINANT),
            (
                counters.candidates_rejected_by_execution_preflight,
                InactivityBottleneck.EXECUTION_PREFLIGHT_FAILURES,
            ),
        )
        maximum, bottleneck = max(weighted, key=lambda item: (item[0], item[1].value))
        if maximum == 0:
            bottleneck = (
                InactivityBottleneck.INSUFFICIENT_MARKET_COVERAGE
                if counters.markets_scanned == 0
                else InactivityBottleneck.NORMAL_LOW_OPPORTUNITY_PERIOD
            )
    fields = {
        "created_at": created_at,
        "period": period,
        "counters": counters,
        "dominant_bottleneck": bottleneck,
        "human_review_recommended": bottleneck
        is not InactivityBottleneck.NORMAL_LOW_OPPORTUNITY_PERIOD,
        "automatic_configuration_change": False,
    }
    identity = fingerprint(fields)
    return InactivityDiagnostic.model_validate(
        {**fields, "diagnostic_id": identity, "diagnostic_fingerprint": identity}
    )
