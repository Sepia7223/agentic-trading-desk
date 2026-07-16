"""Strict structured contracts for advisory AI analysis."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.ai.fingerprints import fingerprint

ADVISORY_STATEMENT = (
    "This analysis is advisory only. It cannot approve trades, determine quantity, "
    "change risk limits, mutate the portfolio, or execute broker operations."
)
POLICY_VERSION = "ai-advisory-policy-v1"
PROMPT_VERSION = "ai-prompt-v1"


class AIModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def reject_binary_floats(cls, value: object) -> object:
        if _contains_float(value):
            raise ValueError("binary floating point is prohibited in AI models")
        return value


class AnalysisMode(StrEnum):
    SIGNAL_EXPLANATION = "SIGNAL_EXPLANATION"
    RISK_DECISION_EXPLANATION = "RISK_DECISION_EXPLANATION"
    TRADE_REVIEW = "TRADE_REVIEW"
    DAILY_REVIEW = "DAILY_REVIEW"
    WEEKLY_REVIEW = "WEEKLY_REVIEW"
    MONTHLY_REVIEW = "MONTHLY_REVIEW"
    HISTORICAL_COMPARISON = "HISTORICAL_COMPARISON"
    ANOMALY_REVIEW = "ANOMALY_REVIEW"
    RESEARCH_HYPOTHESIS = "RESEARCH_HYPOTHESIS"
    PORTFOLIO_SUMMARY = "PORTFOLIO_SUMMARY"


class AnalysisStatus(StrEnum):
    COMPLETED = "COMPLETED"
    DISABLED = "DISABLED"
    REJECTED_BY_POLICY = "REJECTED_BY_POLICY"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    TIMEOUT = "TIMEOUT"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    SANITIZATION_FAILED = "SANITIZATION_FAILED"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"


class SanitizationReasonCode(StrEnum):
    SECRET_FIELD_DETECTED = "SECRET_FIELD_DETECTED"
    RAW_AUTHORIZATION_DATA_DETECTED = "RAW_AUTHORIZATION_DATA_DETECTED"
    INPUT_TOO_LARGE = "INPUT_TOO_LARGE"
    TOO_MANY_RECORDS = "TOO_MANY_RECORDS"
    UNSUPPORTED_CONTEXT = "UNSUPPORTED_CONTEXT"
    MISSING_REQUIRED_CONTEXT = "MISSING_REQUIRED_CONTEXT"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    INVALID_DECIMAL = "INVALID_DECIMAL"
    UNSAFE_FIELD_NAME = "UNSAFE_FIELD_NAME"
    PROVIDER_DISABLED = "PROVIDER_DISABLED"
    NETWORK_PROVIDER_DISABLED = "NETWORK_PROVIDER_DISABLED"


class EvidenceStrength(StrEnum):
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    WEAK_EVIDENCE = "WEAK_EVIDENCE"
    MODERATE_EVIDENCE = "MODERATE_EVIDENCE"
    STRONGER_HISTORICAL_EVIDENCE = "STRONGER_HISTORICAL_EVIDENCE"


class ProcessClassification(StrEnum):
    GOOD_PROCESS = "GOOD_PROCESS"
    BAD_PROCESS = "BAD_PROCESS"
    INDETERMINATE = "INDETERMINATE"


class FinancialOutcome(StrEnum):
    PROFIT = "PROFIT"
    LOSS = "LOSS"
    FLAT = "FLAT"
    UNRESOLVED = "UNRESOLVED"


class SignalScores(AIModel):
    trend: int | None = None
    momentum: int | None = None
    macro: int | None = None
    total: int | None = None


class RegimeProbability(AIModel):
    regime: str = Field(min_length=1, max_length=80)
    probability: Decimal = Field(ge=0, le=1)


class KalmanSummary(AIModel):
    level: Decimal | None = None
    slope: Decimal | None = None
    slope_uncertainty: Decimal | None = Field(default=None, ge=0)
    normalized_price_deviation: Decimal | None = None


class ReviewMetrics(AIModel):
    signals_evaluated: int = Field(default=0, ge=0)
    candidates: int = Field(default=0, ge=0)
    risk_approvals: int = Field(default=0, ge=0)
    risk_rejections: int = Field(default=0, ge=0)
    positions_opened: int = Field(default=0, ge=0)
    positions_closed: int = Field(default=0, ge=0)
    unresolved_positions: int = Field(default=0, ge=0)
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    costs: Decimal = Field(default=Decimal("0"), ge=0)
    rule_violations: tuple[str, ...] = ()
    anomalies: tuple[str, ...] = ()


class SanitizedContext(AIModel):
    instrument: str | None = Field(default=None, max_length=200)
    timeframe: str | None = Field(default=None, max_length=40)
    strategy_variant: str | None = Field(default=None, max_length=80)
    signal_action: str | None = Field(default=None, max_length=40)
    signal_scores: SignalScores | None = None
    regime: str | None = Field(default=None, max_length=80)
    regime_probabilities: tuple[RegimeProbability, ...] = ()
    kalman_state: KalmanSummary | None = None
    gate_results: tuple[str, ...] = ()
    risk_status: str | None = Field(default=None, max_length=40)
    risk_reason_codes: tuple[str, ...] = ()
    approved_quantity: Decimal | None = Field(default=None, ge=0)
    entry_price: Decimal | None = Field(default=None, gt=0)
    exit_price: Decimal | None = Field(default=None, gt=0)
    gross_pnl: Decimal | None = None
    net_pnl: Decimal | None = None
    costs: Decimal | None = Field(default=None, ge=0)
    holding_period_seconds: Decimal | None = Field(default=None, ge=0)
    maximum_favorable_excursion: Decimal | None = Field(default=None, ge=0)
    maximum_adverse_excursion: Decimal | None = Field(default=None, ge=0)
    portfolio_equity: Decimal | None = None
    drawdown: Decimal | None = Field(default=None, ge=0)
    exposure: Decimal | None = Field(default=None, ge=0)
    process_classification: ProcessClassification | None = None
    financial_outcome: FinancialOutcome | None = None
    historical_summary: str | None = Field(default=None, max_length=4000)
    account_reference: str | None = Field(default=None, max_length=20)
    broker_reference: str | None = Field(default=None, max_length=20)
    human_notes: str | None = Field(default=None, max_length=4000)
    news_context: str | None = Field(default=None, max_length=4000)
    review_metrics: ReviewMetrics | None = None

    @field_validator("account_reference", "broker_reference")
    @classmethod
    def require_redacted_reference(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"\*{3}(?:[A-Za-z0-9]{4})?", value):
            raise ValueError("account and broker references must be redacted")
        return value


class HistoricalExample(AIModel):
    record_id: str = Field(min_length=1, max_length=128)
    timestamp: datetime
    instrument: str | None = None
    strategy_variant: str | None = None
    regime: str | None = None
    risk_status: str | None = None
    reason_codes: tuple[str, ...] = ()
    financial_outcome: FinancialOutcome | None = None
    process_classification: ProcessClassification | None = None
    net_return: Decimal | None = None
    holding_period_seconds: Decimal | None = Field(default=None, ge=0)
    spread: Decimal | None = Field(default=None, ge=0)
    volatility: Decimal | None = Field(default=None, ge=0)
    drawdown: Decimal | None = Field(default=None, ge=0)
    qualitative_summary: str | None = Field(default=None, max_length=2000)

    @field_validator("timestamp")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        return _utc(value)


class AIAnalysisRequest(AIModel):
    request_id: str = Field(min_length=64, max_length=64)
    mode: AnalysisMode
    created_at: datetime
    source_record_ids: tuple[str, ...]
    strategy_configuration_fingerprint: str | None = None
    risk_configuration_fingerprint: str | None = None
    portfolio_configuration_fingerprint: str | None = None
    journal_snapshot_id: str | None = None
    sanitized_context: SanitizedContext
    historical_examples: tuple[HistoricalExample, ...] = ()
    explicit_questions: tuple[str, ...] = ()
    policy_version: str = POLICY_VERSION
    configuration_fingerprint: str = Field(min_length=64, max_length=64)
    request_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("created_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def source_links_are_unique(self) -> AIAnalysisRequest:
        if not self.source_record_ids or len(set(self.source_record_ids)) != len(
            self.source_record_ids
        ):
            raise ValueError("source record IDs are required and must be unique")
        fields = self.model_dump(mode="python", exclude={"request_id", "request_fingerprint"})
        expected = fingerprint(fields)
        if self.request_id != expected or self.request_fingerprint != expected:
            raise ValueError("AI request fingerprint is invalid")
        return self

    @field_validator(
        "strategy_configuration_fingerprint",
        "risk_configuration_fingerprint",
        "portfolio_configuration_fingerprint",
    )
    @classmethod
    def optional_sha256(cls, value: str | None) -> str | None:
        if value is not None and not _is_sha256(value):
            raise ValueError("configuration fingerprint must be lowercase SHA-256")
        return value


class Observation(AIModel):
    category: str = Field(min_length=1, max_length=80)
    statement: str = Field(min_length=1, max_length=2000)
    supporting_record_ids: tuple[str, ...]
    confidence: Decimal = Field(ge=0, le=1)
    limitation: str | None = Field(default=None, max_length=1000)


class HistoricalComparison(AIModel):
    sample_size: int = Field(ge=0)
    matching_criteria: tuple[str, ...]
    average_net_return: Decimal | None = None
    win_rate: Decimal | None = Field(default=None, ge=0, le=1)
    average_holding_period_seconds: Decimal | None = Field(default=None, ge=0)
    common_failure_patterns: tuple[str, ...] = ()
    uncertainty: str
    evidence_strength: EvidenceStrength


class ResearchHypothesis(AIModel):
    hypothesis_id: str = Field(min_length=1, max_length=128)
    statement: str = Field(min_length=1, max_length=2000)
    rationale: str = Field(min_length=1, max_length=2000)
    required_dataset: str = Field(min_length=1, max_length=1000)
    proposed_test: str = Field(min_length=1, max_length=2000)
    prohibited_automatic_action: Literal[True] = True


class AIAnalysisResponse(AIModel):
    response_id: str = Field(min_length=64, max_length=64)
    request_id: str = Field(min_length=64, max_length=64)
    mode: AnalysisMode
    created_at: datetime
    summary: str = Field(min_length=1, max_length=10_000)
    observations: tuple[Observation, ...]
    evidence: tuple[str, ...]
    uncertainties: tuple[str, ...]
    risk_flags: tuple[str, ...]
    process_findings: tuple[str, ...]
    historical_comparisons: tuple[HistoricalComparison, ...]
    research_hypotheses: tuple[ResearchHypothesis, ...]
    recommended_human_actions: tuple[str, ...]
    prohibited_actions_acknowledged: Literal[True]
    advisory_statement: str = ADVISORY_STATEMENT
    source_record_ids: tuple[str, ...]
    provider_name: str
    model_name: str
    configuration_fingerprint: str = Field(min_length=64, max_length=64)
    request_fingerprint: str = Field(min_length=64, max_length=64)
    response_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("created_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @field_validator("advisory_statement")
    @classmethod
    def exact_advisory_statement(cls, value: str) -> str:
        if value != ADVISORY_STATEMENT:
            raise ValueError("mandatory advisory statement is missing or changed")
        return value

    @model_validator(mode="after")
    def valid_response_fingerprint(self) -> AIAnalysisResponse:
        fields = self.model_dump(mode="python", exclude={"response_id", "response_fingerprint"})
        expected = fingerprint(fields)
        if self.response_id != expected or self.response_fingerprint != expected:
            raise ValueError("AI response fingerprint is invalid")
        return self


class AIAnalysisRecord(AIModel):
    analysis_id: str = Field(min_length=64, max_length=64)
    request_id: str
    mode: AnalysisMode
    created_at: datetime
    source_record_ids: tuple[str, ...]
    sanitized_input_fingerprint: str = Field(min_length=64, max_length=64)
    provider_name: str
    model_name: str
    structured_response: AIAnalysisResponse
    policy_version: str
    configuration_fingerprint: str
    analysis_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("created_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def valid_analysis_fingerprint(self) -> AIAnalysisRecord:
        fields = self.model_dump(mode="python", exclude={"analysis_id", "analysis_fingerprint"})
        expected = fingerprint(fields)
        if self.analysis_id != expected or self.analysis_fingerprint != expected:
            raise ValueError("AI analysis fingerprint is invalid")
        return self


class AIAnalysisResult(AIModel):
    status: AnalysisStatus
    request_id: str | None = None
    response: AIAnalysisResponse | None = None
    record: AIAnalysisRecord | None = None
    reason_codes: tuple[SanitizationReasonCode, ...] = ()
    safe_message: str


class RetrievalFilter(AIModel):
    instrument: str | None = None
    strategy_variant: str | None = None
    regime: str | None = None
    risk_status: str | None = None
    reason_codes: tuple[str, ...] = ()
    financial_outcome: FinancialOutcome | None = None
    process_classification: ProcessClassification | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    minimum_spread: Decimal | None = Field(default=None, ge=0)
    maximum_spread: Decimal | None = Field(default=None, ge=0)
    minimum_holding_period_seconds: Decimal | None = Field(default=None, ge=0)
    maximum_holding_period_seconds: Decimal | None = Field(default=None, ge=0)

    @field_validator("start_at", "end_at")
    @classmethod
    def optional_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("AI timestamps must be timezone-aware UTC")
    return value.astimezone(UTC)


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _contains_float(value: object) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_contains_float(item) for item in value.values())
    if isinstance(value, (tuple, list)):
        return any(_contains_float(item) for item in value)
    return False
