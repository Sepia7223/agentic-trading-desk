"""Immutable contracts for journal evidence, retrieval, reviews, and integrity."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.journal.fingerprints import (
    decode_primitive,
    fingerprint,
    reject_machine_paths,
    reject_secret_fields,
    to_primitive,
)


class JournalModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class JournalRecordType(StrEnum):
    SCHEDULER_CYCLE = "SCHEDULER_CYCLE"
    MARKET_CONTEXT = "MARKET_CONTEXT"
    SESSION_CLASSIFICATION = "SESSION_CLASSIFICATION"
    EVENT_CONTEXT = "EVENT_CONTEXT"
    ROUTER_DECISION = "ROUTER_DECISION"
    STRATEGY_ELIGIBILITY = "STRATEGY_ELIGIBILITY"
    RESEARCH_STRATEGY_RESULT = "RESEARCH_STRATEGY_RESULT"
    CAPITAL_PRESERVATION_DECISION = "CAPITAL_PRESERVATION_DECISION"
    STRATEGY_SIGNAL = "STRATEGY_SIGNAL"
    STRATEGY_REJECTION = "STRATEGY_REJECTION"
    RISK_DECISION = "RISK_DECISION"
    APPROVED_TRADE_INTENT = "APPROVED_TRADE_INTENT"
    PAPER_PORTFOLIO_EVENT = "PAPER_PORTFOLIO_EVENT"
    PAPER_FILL = "PAPER_FILL"
    PAPER_CLOSED_TRADE = "PAPER_CLOSED_TRADE"
    PAPER_UNRESOLVED_POSITION = "PAPER_UNRESOLVED_POSITION"
    EXECUTION_REQUEST = "EXECUTION_REQUEST"
    EXECUTION_PREFLIGHT = "EXECUTION_PREFLIGHT"
    OPERATOR_CONFIRMATION = "OPERATOR_CONFIRMATION"
    BROKER_SUBMISSION = "BROKER_SUBMISSION"
    BROKER_CONFIRMATION = "BROKER_CONFIRMATION"
    EXECUTION_RECONCILIATION = "EXECUTION_RECONCILIATION"
    EXECUTION_FAILURE = "EXECUTION_FAILURE"
    POSITION_MONITOR_SNAPSHOT = "POSITION_MONITOR_SNAPSHOT"
    EXIT_DECISION = "EXIT_DECISION"
    EXIT_PREFLIGHT = "EXIT_PREFLIGHT"
    CLOSE_REQUEST = "CLOSE_REQUEST"
    CLOSE_SUBMISSION = "CLOSE_SUBMISSION"
    CLOSE_CONFIRMATION = "CLOSE_CONFIRMATION"
    CLOSE_RECONCILIATION = "CLOSE_RECONCILIATION"
    POSITION_CLOSED = "POSITION_CLOSED"
    POSITION_CLOSE_BLOCKED = "POSITION_CLOSE_BLOCKED"
    POSITION_LIFECYCLE_HALTED = "POSITION_LIFECYCLE_HALTED"
    PAPER_DEMO_EXIT_COMPARISON = "PAPER_DEMO_EXIT_COMPARISON"
    AI_ANALYSIS = "AI_ANALYSIS"
    POST_TRADE_REVIEW = "POST_TRADE_REVIEW"
    DAILY_REVIEW = "DAILY_REVIEW"
    WEEKLY_REVIEW = "WEEKLY_REVIEW"
    MONTHLY_REVIEW = "MONTHLY_REVIEW"
    AMENDMENT = "AMENDMENT"
    INTEGRITY_EVENT = "INTEGRITY_EVENT"


class IntegrityStatus(StrEnum):
    VALID = "VALID"
    WARNINGS = "WARNINGS"
    INVALID = "INVALID"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    UNSUPPORTED_SCHEMA = "UNSUPPORTED_SCHEMA"


class ProcessClassification(StrEnum):
    VALID_PROCESS = "VALID_PROCESS"
    RULE_VIOLATION = "RULE_VIOLATION"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    DATA_ERROR = "DATA_ERROR"
    RISK_ERROR = "RISK_ERROR"
    RECONCILIATION_ERROR = "RECONCILIATION_ERROR"
    UNRESOLVED = "UNRESOLVED"
    UNKNOWN = "UNKNOWN"


class FinancialOutcome(StrEnum):
    WIN = "WIN"
    LOSS = "LOSS"
    BREAKEVEN = "BREAKEVEN"
    UNREALIZED = "UNREALIZED"
    UNKNOWN = "UNKNOWN"


class ExportFormat(StrEnum):
    JSONL = "jsonl"
    CSV = "csv"
    MARKDOWN = "markdown"


class AmendmentReasonCode(StrEnum):
    DATA_CORRECTION = "DATA_CORRECTION"
    BROKER_CONFIRMATION_UPDATE = "BROKER_CONFIRMATION_UPDATE"
    RECONCILIATION_UPDATE = "RECONCILIATION_UPDATE"
    CLASSIFICATION_CORRECTION = "CLASSIFICATION_CORRECTION"
    HUMAN_NOTE_ADDED = "HUMAN_NOTE_ADDED"
    AI_REVIEW_ADDED = "AI_REVIEW_ADDED"
    SCHEMA_MIGRATION_NOTE = "SCHEMA_MIGRATION_NOTE"
    DUPLICATE_REFERENCE_CORRECTION = "DUPLICATE_REFERENCE_CORRECTION"
    OTHER = "OTHER"


class JournalRecord(JournalModel):
    journal_record_id: str = Field(min_length=64, max_length=64)
    sequence_number: int = Field(ge=1)
    record_type: JournalRecordType
    source_record_id: str = Field(min_length=1, max_length=256)
    source_parent_ids: tuple[str, ...] = ()
    created_at: datetime
    effective_at: datetime
    trading_day: date
    instrument: str | None = Field(default=None, max_length=200)
    epic: str | None = Field(default=None, max_length=80)
    strategy_variant: str | None = Field(default=None, max_length=100)
    environment: str = Field(default="LOCAL", min_length=1, max_length=32)
    schema_version: int = Field(ge=1)
    record_version: int = Field(default=1, ge=1)
    source_fingerprint: str = Field(min_length=64, max_length=64)
    payload_fingerprint: str = Field(min_length=64, max_length=64)
    previous_record_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)
    journal_record_fingerprint: str = Field(min_length=64, max_length=64)
    payload: dict[str, object]
    deferred_linkage: bool = False
    atomic_group_id: str | None = Field(default=None, min_length=64, max_length=64)
    atomic_group_index: int | None = Field(default=None, ge=1)
    atomic_group_size: int | None = Field(default=None, ge=2)

    @field_validator("created_at", "effective_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("journal timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        if self.trading_day != self.effective_at.date():
            raise ValueError("trading day must match the UTC effective timestamp")
        if len(set(self.source_parent_ids)) != len(self.source_parent_ids):
            raise ValueError("source parent IDs must be unique")
        group_values = (self.atomic_group_id, self.atomic_group_index, self.atomic_group_size)
        if any(value is not None for value in group_values) and any(
            value is None for value in group_values
        ):
            raise ValueError("atomic group metadata must be complete")
        if (
            self.atomic_group_index
            and self.atomic_group_size
            and self.atomic_group_index > self.atomic_group_size
        ):
            raise ValueError("atomic group index exceeds group size")
        reject_secret_fields(self.payload)
        if fingerprint(self.payload) != self.payload_fingerprint:
            raise ValueError("payload fingerprint mismatch")
        expected = fingerprint(self.fingerprint_fields())
        if self.journal_record_id != expected or self.journal_record_fingerprint != expected:
            raise ValueError("journal record fingerprint mismatch")
        return self

    def fingerprint_fields(self) -> dict[str, object]:
        return {
            "sequence_number": self.sequence_number,
            "record_type": self.record_type,
            "source_record_id": self.source_record_id,
            "source_parent_ids": self.source_parent_ids,
            "created_at": self.created_at,
            "effective_at": self.effective_at,
            "trading_day": self.trading_day,
            "instrument": self.instrument,
            "epic": self.epic,
            "strategy_variant": self.strategy_variant,
            "environment": self.environment,
            "schema_version": self.schema_version,
            "record_version": self.record_version,
            "source_fingerprint": self.source_fingerprint,
            "payload_fingerprint": self.payload_fingerprint,
            "previous_record_fingerprint": self.previous_record_fingerprint,
            "deferred_linkage": self.deferred_linkage,
            "atomic_group_id": self.atomic_group_id,
            "atomic_group_index": self.atomic_group_index,
            "atomic_group_size": self.atomic_group_size,
        }


def create_journal_record(
    *,
    sequence_number: int,
    record_type: JournalRecordType,
    source_record_id: str,
    source: object,
    source_parent_ids: tuple[str, ...] = (),
    created_at: datetime,
    effective_at: datetime,
    previous_record_fingerprint: str | None,
    schema_version: int = 1,
    record_version: int = 1,
    instrument: str | None = None,
    epic: str | None = None,
    strategy_variant: str | None = None,
    environment: str = "LOCAL",
    deferred_linkage: bool = False,
    atomic_group_id: str | None = None,
    atomic_group_index: int | None = None,
    atomic_group_size: int | None = None,
) -> JournalRecord:
    reject_secret_fields(source)
    reject_machine_paths(source)
    primitive = decode_primitive(to_primitive(source))
    if not isinstance(primitive, dict):
        primitive = {"value": primitive}
    payload: dict[str, object] = primitive
    source_fingerprint = fingerprint(payload)
    payload_fingerprint = fingerprint(payload)
    fields: dict[str, object] = {
        "sequence_number": sequence_number,
        "record_type": record_type,
        "source_record_id": source_record_id,
        "source_parent_ids": source_parent_ids,
        "created_at": created_at,
        "effective_at": effective_at,
        "trading_day": effective_at.astimezone(UTC).date(),
        "instrument": instrument,
        "epic": epic,
        "strategy_variant": strategy_variant,
        "environment": environment,
        "schema_version": schema_version,
        "record_version": record_version,
        "source_fingerprint": source_fingerprint,
        "payload_fingerprint": payload_fingerprint,
        "previous_record_fingerprint": previous_record_fingerprint,
        "payload": payload,
        "deferred_linkage": deferred_linkage,
        "atomic_group_id": atomic_group_id,
        "atomic_group_index": atomic_group_index,
        "atomic_group_size": atomic_group_size,
    }
    identity = fingerprint({key: value for key, value in fields.items() if key != "payload"})
    return JournalRecord.model_validate(
        {**fields, "journal_record_id": identity, "journal_record_fingerprint": identity}
    )


class JournalQuery(JournalModel):
    record_type: JournalRecordType | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    cutoff_at: datetime | None = None
    instrument: str | None = None
    epic: str | None = None
    strategy_variant: str | None = None
    regime: str | None = None
    risk_status: str | None = None
    risk_reason_code: str | None = None
    execution_status: str | None = None
    process_classification: ProcessClassification | None = None
    financial_outcome: FinancialOutcome | None = None
    environment: str | None = None
    source_record_id: str | None = None
    candidate_id: str | None = None
    risk_decision_id: str | None = None
    trade_id: str | None = None
    configuration_fingerprint: str | None = None
    minimum_pnl: Decimal | None = None
    maximum_pnl: Decimal | None = None
    minimum_drawdown: Decimal | None = None
    maximum_drawdown: Decimal | None = None
    limit: int = Field(default=100, ge=1)
    offset: int = Field(default=0, ge=0)

    @field_validator("start_at", "end_at", "cutoff_at")
    @classmethod
    def utc_filter(cls, value: datetime | None) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value)
        ):
            raise ValueError("query timestamps must be timezone-aware UTC")
        return value

    @model_validator(mode="after")
    def valid_ranges(self) -> Self:
        if self.start_at and self.end_at and self.start_at > self.end_at:
            raise ValueError("query start must not follow end")
        if self.cutoff_at and self.end_at and self.end_at > self.cutoff_at:
            raise ValueError("query end cannot exceed its cutoff")
        return self

    @property
    def query_fingerprint(self) -> str:
        return fingerprint(self.model_dump(mode="python"))


class JournalQueryResult(JournalModel):
    records: tuple[JournalRecord, ...]
    total_matches: int = Field(ge=0)
    next_offset: int | None
    query_fingerprint: str = Field(min_length=64, max_length=64)


class JournalLineage(JournalModel):
    requested_id: str
    records: tuple[JournalRecord, ...]
    missing_parent_ids: tuple[str, ...] = ()


class IntegrityFinding(JournalModel):
    code: str
    message: str
    journal_record_id: str | None = None
    blocking: bool = True


class IntegrityReport(JournalModel):
    status: IntegrityStatus
    schema_version: int
    records_checked: int = Field(ge=0)
    findings: tuple[IntegrityFinding, ...]
    verified_at: datetime

    @field_validator("verified_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("integrity timestamp must be timezone-aware")
        return value.astimezone(UTC)


class Amendment(JournalModel):
    amendment_id: str = Field(min_length=64, max_length=64)
    target_journal_record_id: str = Field(min_length=64, max_length=64)
    created_at: datetime
    reason_code: AmendmentReasonCode
    reason: str = Field(min_length=1, max_length=1000)
    corrected_fields: dict[str, object]
    previous_values_fingerprint: str = Field(min_length=64, max_length=64)
    corrected_values_fingerprint: str = Field(min_length=64, max_length=64)
    created_by: str = Field(min_length=1, max_length=100)
    approval_reference: str | None = Field(default=None, max_length=256)
    amendment_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("created_at")
    @classmethod
    def utc_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("amendment timestamp must be timezone-aware")
        return value.astimezone(UTC)


class PostTradeReviewInput(JournalModel):
    trade_id: str
    instrument: str
    epic: str
    strategy_variant: str | None = None
    entry_timestamp: datetime
    exit_timestamp: datetime | None
    quantity: Decimal
    entry_price: Decimal
    exit_price: Decimal | None
    gross_pnl: Decimal | None
    commission: Decimal = Decimal("0")
    funding: Decimal = Decimal("0")
    spread_cost: Decimal = Decimal("0")
    slippage_cost: Decimal = Decimal("0")
    initial_risk_amount: Decimal | None = None
    maximum_favorable_excursion: Decimal | None = None
    maximum_adverse_excursion: Decimal | None = None
    entry_regime: str | None = None
    exit_regime: str | None = None
    rule_violation: bool = False
    execution_error: bool = False
    data_error: bool = False
    risk_error: bool = False
    reconciliation_error: bool = False
    unresolved: bool = False
    risk_reason_context: tuple[str, ...] = ()
    execution_quality: str | None = None


class PostTradeReview(JournalModel):
    trade_id: str
    gross_pnl: Decimal | None
    net_pnl: Decimal | None
    total_costs: Decimal
    spread_cost: Decimal
    slippage_cost: Decimal
    commission: Decimal
    funding: Decimal
    holding_period_seconds: int | None
    maximum_favorable_excursion: Decimal | None
    maximum_adverse_excursion: Decimal | None
    return_fraction: Decimal | None
    risk_multiple: Decimal | None
    entry_regime: str | None
    exit_regime: str | None
    strategy_variant: str | None
    risk_reason_context: tuple[str, ...]
    execution_quality: str | None
    process_classification: ProcessClassification
    financial_outcome: FinancialOutcome
    review_fingerprint: str = Field(min_length=64, max_length=64)


class PeriodicReview(JournalModel):
    period_type: str
    period_start: datetime
    period_end: datetime
    sample_size: int
    counts: dict[str, int]
    totals: dict[str, Decimal]
    breakdowns: dict[str, dict[str, Decimal | int]]
    metrics: dict[str, Decimal | int | str]
    insufficient_sample: bool
    review_fingerprint: str = Field(min_length=64, max_length=64)


class SimilarityFeatures(JournalModel):
    source_record_id: str
    timestamp: datetime
    instrument: str
    strategy_variant: str | None
    entry_regime: str | None
    regime_probabilities: tuple[Decimal, ...] = ()
    kalman_slope: Decimal | None = None
    volatility: Decimal | None = None
    spread_bps: Decimal | None = None
    time_of_day: str | None = None
    session: str | None = None
    holding_period_seconds: int | None = None
    risk_fraction: Decimal | None = None
    entry_distance_to_stop: Decimal | None = None
    maximum_favorable_excursion: Decimal | None = None
    maximum_adverse_excursion: Decimal | None = None
    cost_fraction: Decimal | None = None
    process_classification: ProcessClassification = ProcessClassification.UNKNOWN
    financial_outcome: FinancialOutcome = FinancialOutcome.UNKNOWN


class SimilarityMatch(JournalModel):
    source_record_id: str
    distance: Decimal
    features: SimilarityFeatures


class PaperDemoComparisonInput(JournalModel):
    comparison_id: str
    paper_trade_id: str
    demo_trade_id: str
    paper_entry_price: Decimal
    demo_entry_price: Decimal
    paper_exit_price: Decimal | None = None
    demo_exit_price: Decimal | None = None
    paper_quantity: Decimal
    demo_quantity: Decimal
    paper_entry_timestamp: datetime
    demo_entry_timestamp: datetime
    paper_costs: Decimal = Decimal("0")
    demo_costs: Decimal = Decimal("0")
    paper_pnl: Decimal | None = None
    demo_pnl: Decimal | None = None
    paper_stop: Decimal | None = None
    demo_stop: Decimal | None = None
    paper_target: Decimal | None = None
    demo_target: Decimal | None = None


class PaperDemoComparison(JournalModel):
    comparison_id: str
    paper_trade_id: str
    demo_trade_id: str
    paper_entry_price: Decimal
    demo_entry_price: Decimal
    entry_slippage_difference: Decimal
    paper_exit_price: Decimal | None
    demo_exit_price: Decimal | None
    exit_slippage_difference: Decimal | None
    quantity_difference: Decimal
    timing_difference_seconds: int
    cost_difference: Decimal
    pnl_difference: Decimal | None
    stop_difference: Decimal | None
    target_difference: Decimal | None
    comparison_fingerprint: str = Field(min_length=64, max_length=64)


class BackupResult(JournalModel):
    path: Path
    checksum: str = Field(min_length=64, max_length=64)
    created_at: datetime
    verified: bool


class ExportResult(JournalModel):
    path: Path
    format: ExportFormat
    schema_version: int
    configuration_fingerprint: str
    query_fingerprint: str
    export_timestamp: datetime
    source_record_count: int
    checksum: str = Field(min_length=64, max_length=64)
