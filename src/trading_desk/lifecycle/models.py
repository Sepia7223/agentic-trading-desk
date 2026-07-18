"""Strict immutable contracts for the complete Demo position exit lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.lifecycle.fingerprints import fingerprint


class LifecycleModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def reject_binary_floats(cls, value: object) -> object:
        if _contains_float(value):
            raise ValueError("binary floating point is prohibited in lifecycle models")
        return value


class PositionDirection(StrEnum):
    LONG = "LONG"


class PositionStatus(StrEnum):
    OPEN = "OPEN"
    UNKNOWN = "UNKNOWN"


class LifecycleMarketStatus(StrEnum):
    TRADEABLE = "TRADEABLE"
    CLOSED = "CLOSED"
    CLOSINGS_ONLY = "CLOSINGS_ONLY"
    UNKNOWN = "UNKNOWN"


class ExitReason(StrEnum):
    PROTECTIVE_STOP = "PROTECTIVE_STOP"
    PROFIT_TARGET = "PROFIT_TARGET"
    STRATEGY_INVALIDATED = "STRATEGY_INVALIDATED"
    MAXIMUM_HOLDING_PERIOD = "MAXIMUM_HOLDING_PERIOD"
    RISK_LIMIT_BREACH = "RISK_LIMIT_BREACH"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    DRAWDOWN_LIMIT = "DRAWDOWN_LIMIT"
    KILL_SWITCH = "KILL_SWITCH"
    MARKET_CLOSURE_POLICY = "MARKET_CLOSURE_POLICY"
    EMERGENCY_OPERATOR_POLICY = "EMERGENCY_OPERATOR_POLICY"
    BROKER_STATE_MISMATCH = "BROKER_STATE_MISMATCH"
    DATA_STALE = "DATA_STALE"
    RECONCILIATION_FAILURE = "RECONCILIATION_FAILURE"
    UNKNOWN = "UNKNOWN"


class ExitDecisionStatus(StrEnum):
    HOLD = "HOLD"
    EXIT_REQUIRED = "EXIT_REQUIRED"
    EXIT_BLOCKED = "EXIT_BLOCKED"
    INVALID_STATE = "INVALID_STATE"
    EMERGENCY_EXIT_REQUIRED = "EMERGENCY_EXIT_REQUIRED"


class StrategyExitState(StrEnum):
    HOLD = "HOLD"
    EXIT = "EXIT"
    UNKNOWN = "UNKNOWN"


class ExitPreflightStatus(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"
    DISABLED = "DISABLED"
    INVALID_STATE = "INVALID_STATE"


class CloseSide(StrEnum):
    SELL = "SELL"


class CloseOrderType(StrEnum):
    MARKET = "MARKET"


class CloseTimeInForce(StrEnum):
    FILL_OR_KILL = "FILL_OR_KILL"


class CloseExecutionStatus(StrEnum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"
    TIMED_OUT = "TIMED_OUT"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    RECONCILED = "RECONCILED"


class CloseConfirmationStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PENDING = "PENDING"
    UNKNOWN = "UNKNOWN"


class CloseReconciliationStatus(StrEnum):
    POSITION_CLOSED = "POSITION_CLOSED"
    PARTIAL_POSITION_REMAINS = "PARTIAL_POSITION_REMAINS"
    POSITION_STILL_OPEN = "POSITION_STILL_OPEN"
    UNEXPECTED_OPPOSITE_POSITION = "UNEXPECTED_OPPOSITE_POSITION"
    POSITION_NOT_FOUND_AS_EXPECTED = "POSITION_NOT_FOUND_AS_EXPECTED"
    RECONCILIATION_MISMATCH = "RECONCILIATION_MISMATCH"
    RECONCILIATION_PENDING = "RECONCILIATION_PENDING"


class LifecycleEventType(StrEnum):
    POSITION_MONITORED = "POSITION_MONITORED"
    EXIT_DECISION_CREATED = "EXIT_DECISION_CREATED"
    EXIT_PREFLIGHT_UPDATED = "EXIT_PREFLIGHT_UPDATED"
    CLOSE_REQUEST_CREATED = "CLOSE_REQUEST_CREATED"
    CLOSE_SUBMITTED = "CLOSE_SUBMITTED"
    CLOSE_CONFIRMATION_UPDATED = "CLOSE_CONFIRMATION_UPDATED"
    CLOSE_RECONCILIATION_UPDATED = "CLOSE_RECONCILIATION_UPDATED"
    POSITION_CLOSED = "POSITION_CLOSED"
    POSITION_CLOSE_BLOCKED = "POSITION_CLOSE_BLOCKED"
    POSITION_LIFECYCLE_HALTED = "POSITION_LIFECYCLE_HALTED"
    POST_TRADE_REVIEW_CREATED = "POST_TRADE_REVIEW_CREATED"


class DemoPositionSnapshot(LifecycleModel):
    snapshot_id: str = Field(min_length=64, max_length=64)
    position_id: str
    deal_id: str = Field(min_length=1, max_length=30)
    deal_reference: str | None = Field(default=None, max_length=30)
    instrument: str
    epic: str = Field(pattern=r"[A-Za-z0-9._]{6,30}")
    asset_class: str
    direction: PositionDirection
    quantity: Decimal = Field(gt=0)
    entry_timestamp: datetime
    entry_level: Decimal = Field(gt=0)
    current_bid: Decimal = Field(gt=0)
    current_ask: Decimal = Field(gt=0)
    current_mark: Decimal = Field(gt=0)
    stop_level: Decimal | None = Field(default=None, gt=0)
    target_level: Decimal | None = Field(default=None, gt=0)
    unrealized_pnl: Decimal
    accrued_costs: Decimal = Field(ge=0)
    current_exposure: Decimal = Field(ge=0)
    current_risk: Decimal = Field(ge=0)
    holding_duration: timedelta = Field(ge=timedelta(0))
    market_status: LifecycleMarketStatus
    position_status: PositionStatus
    account_snapshot_id: str
    market_snapshot_id: str
    source_execution_id: str
    strategy_id: str
    strategy_version: str
    strategy_configuration_fingerprint: str = Field(min_length=64, max_length=64)
    risk_configuration_fingerprint: str = Field(min_length=64, max_length=64)
    execution_configuration_fingerprint: str = Field(min_length=64, max_length=64)
    snapshot_timestamp: datetime
    market_timestamp: datetime
    account_timestamp: datetime
    snapshot_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator(
        "entry_timestamp", "snapshot_timestamp", "market_timestamp", "account_timestamp"
    )
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if self.current_bid > self.current_ask:
            raise ValueError("position bid cannot exceed ask")
        if self.current_mark != self.current_bid:
            raise ValueError("long position mark must use bid-side liquidation value")
        if self.entry_timestamp > self.snapshot_timestamp:
            raise ValueError("entry timestamp follows snapshot")
        expected = fingerprint(
            self.model_dump(mode="python", exclude={"snapshot_id", "snapshot_fingerprint"})
        )
        if self.snapshot_id != expected or self.snapshot_fingerprint != expected:
            raise ValueError("position snapshot fingerprint is invalid")
        return self


class LifecycleRiskState(LifecycleModel):
    account_snapshot_id: str
    timestamp: datetime
    state_complete: bool
    kill_switch_active: bool = False
    emergency_exit_required: bool = False
    daily_loss_limit_reached: bool = False
    drawdown_limit_reached: bool = False
    risk_limit_breached: bool = False
    lifecycle_halted: bool = False
    reason_codes: tuple[str, ...] = ()

    @field_validator("timestamp")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        return _utc(value)


class ExitDecision(LifecycleModel):
    exit_decision_id: str = Field(min_length=64, max_length=64)
    position_id: str
    deal_id: str
    evaluation_timestamp: datetime
    status: ExitDecisionStatus
    primary_reason: ExitReason
    secondary_reasons: tuple[ExitReason, ...] = ()
    requested_quantity: Decimal = Field(gt=0)
    expected_close_side: CloseSide
    reference_price: Decimal = Field(gt=0)
    stop_level: Decimal | None = Field(default=None, gt=0)
    target_level: Decimal | None = Field(default=None, gt=0)
    holding_duration: timedelta
    current_unrealized_pnl: Decimal
    current_risk: Decimal
    passed_gates: tuple[str, ...]
    failed_gates: tuple[str, ...]
    reason_codes: tuple[str, ...]
    strategy_fingerprint: str = Field(min_length=64, max_length=64)
    risk_fingerprint: str = Field(min_length=64, max_length=64)
    lifecycle_configuration_fingerprint: str = Field(min_length=64, max_length=64)
    position_snapshot_id: str
    market_snapshot_id: str
    account_snapshot_id: str
    decision_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("evaluation_timestamp")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_fingerprint(self) -> Self:
        expected = fingerprint(
            self.model_dump(mode="python", exclude={"exit_decision_id", "decision_fingerprint"})
        )
        if self.exit_decision_id != expected or self.decision_fingerprint != expected:
            raise ValueError("exit decision fingerprint is invalid")
        return self


class CloseRequest(LifecycleModel):
    close_request_id: str = Field(min_length=64, max_length=64)
    exit_decision_id: str
    position_id: str
    deal_id: str = Field(min_length=1, max_length=30)
    instrument: str
    epic: str
    direction: PositionDirection
    requested_quantity: Decimal = Field(gt=0)
    close_side: CloseSide
    order_type: CloseOrderType
    reference_price: Decimal = Field(gt=0)
    exit_reason: ExitReason
    created_at: datetime
    expires_at: datetime
    position_snapshot_id: str
    account_snapshot_id: str
    market_snapshot_id: str
    strategy_fingerprint: str
    risk_fingerprint: str
    execution_fingerprint: str
    lifecycle_configuration_fingerprint: str
    request_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("created_at", "expires_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        if self.expires_at <= self.created_at:
            raise ValueError("close request expiry must follow creation")
        expected = fingerprint(
            self.model_dump(mode="python", exclude={"close_request_id", "request_fingerprint"})
        )
        if self.close_request_id != expected or self.request_fingerprint != expected:
            raise ValueError("close request fingerprint is invalid")
        return self


class ExitPreflightResult(LifecycleModel):
    preflight_id: str = Field(min_length=64, max_length=64)
    close_request_id: str
    status: ExitPreflightStatus
    passed_gates: tuple[str, ...]
    failed_gates: tuple[str, ...]
    reason_codes: tuple[str, ...]
    validated_quantity: Decimal | None = Field(default=None, gt=0)
    position_snapshot_id: str
    account_snapshot_id: str
    market_snapshot_id: str
    lifecycle_configuration_fingerprint: str
    preflight_fingerprint: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_fingerprint(self) -> Self:
        expected = fingerprint(
            self.model_dump(mode="python", exclude={"preflight_id", "preflight_fingerprint"})
        )
        if self.preflight_id != expected or self.preflight_fingerprint != expected:
            raise ValueError("exit preflight fingerprint is invalid")
        return self


class BrokerCloseRequest(LifecycleModel):
    deal_id: str = Field(min_length=1, max_length=30)
    direction: CloseSide
    size: Decimal = Field(gt=0, decimal_places=12)
    order_type: CloseOrderType
    time_in_force: CloseTimeInForce


class BrokerCloseSubmission(LifecycleModel):
    deal_reference: str = Field(pattern=r"[A-Za-z0-9_-]{1,30}")
    safe_request_id: str | None = Field(default=None, max_length=128)


class CloseBrokerConfirmation(LifecycleModel):
    deal_reference: str
    deal_id: str | None = None
    status: CloseConfirmationStatus
    broker_status: str | None = None
    broker_reason: str | None = None
    epic: str | None = None
    direction: CloseSide | None = None
    executed_level: Decimal | None = None
    executed_size: Decimal | None = None
    confirmed_at: datetime

    @field_validator("confirmed_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        return _utc(value)


class CloseExecutionResult(LifecycleModel):
    close_result_id: str = Field(min_length=64, max_length=64)
    close_request_id: str
    exit_decision_id: str
    position_id: str
    submitted_at: datetime | None
    completed_at: datetime
    status: CloseExecutionStatus
    deal_reference: str | None
    broker_status: str | None
    broker_reason: str | None
    requested_quantity: Decimal
    confirmed_quantity: Decimal | None
    confirmed_exit_level: Decimal | None
    confirmation_status: CloseConfirmationStatus | None
    reconciliation_status: CloseReconciliationStatus | None
    safe_error_code: str | None
    safe_request_id: str | None
    request_fingerprint: str
    result_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("submitted_at", "completed_at")
    @classmethod
    def utc_timestamp(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @model_validator(mode="after")
    def validate_fingerprint(self) -> Self:
        expected = fingerprint(
            self.model_dump(mode="python", exclude={"close_result_id", "result_fingerprint"})
        )
        if self.close_result_id != expected or self.result_fingerprint != expected:
            raise ValueError("close result fingerprint is invalid")
        return self


class CloseReconciliationResult(LifecycleModel):
    reconciliation_id: str = Field(min_length=64, max_length=64)
    close_result_id: str
    position_id: str
    status: CloseReconciliationStatus
    checked_at: datetime
    remaining_quantity: Decimal | None = Field(default=None, ge=0)
    discrepancies: tuple[str, ...]
    reconciliation_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("checked_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_fingerprint(self) -> Self:
        expected = fingerprint(
            self.model_dump(
                mode="python", exclude={"reconciliation_id", "reconciliation_fingerprint"}
            )
        )
        if self.reconciliation_id != expected or self.reconciliation_fingerprint != expected:
            raise ValueError("close reconciliation fingerprint is invalid")
        return self


class LifecycleOutcome(LifecycleModel):
    decision: ExitDecision
    request: CloseRequest | None = None
    preflight: ExitPreflightResult | None = None
    result: CloseExecutionResult | None = None
    reconciliation: CloseReconciliationResult | None = None
    automatic_lifecycle_halted: bool = False


class LifecycleJournalRecord(LifecycleModel):
    record_id: str = Field(min_length=64, max_length=64)
    sequence: int = Field(ge=1)
    event_type: LifecycleEventType
    timestamp: datetime
    position_id: str
    exit_decision_id: str | None = None
    close_request_id: str | None = None
    deal_id: str | None = None
    payload_fingerprint: str
    previous_record_fingerprint: str | None = None
    record_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("timestamp")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_fingerprint(self) -> Self:
        expected = fingerprint(
            self.model_dump(mode="python", exclude={"record_id", "record_fingerprint"})
        )
        if self.record_id != expected or self.record_fingerprint != expected:
            raise ValueError("lifecycle journal fingerprint is invalid")
        return self


class LifecyclePostTradeReview(LifecycleModel):
    review_id: str = Field(min_length=64, max_length=64)
    position_id: str
    close_request_id: str
    exit_reason: ExitReason
    entry_level: Decimal = Field(gt=0)
    confirmed_exit_level: Decimal = Field(gt=0)
    confirmed_quantity: Decimal = Field(gt=0)
    gross_pnl: Decimal
    accrued_costs: Decimal = Field(ge=0)
    net_pnl: Decimal
    holding_duration: timedelta = Field(ge=timedelta(0))
    reconciliation_status: CloseReconciliationStatus
    process_classification: str
    created_at: datetime
    review_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("created_at")
    @classmethod
    def review_timestamp(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_review(self) -> Self:
        expected = fingerprint(
            self.model_dump(mode="python", exclude={"review_id", "review_fingerprint"})
        )
        if self.review_id != expected or self.review_fingerprint != expected:
            raise ValueError("lifecycle review fingerprint is invalid")
        return self


class PaperDemoExitComparison(LifecycleModel):
    comparison_id: str = Field(min_length=64, max_length=64)
    position_id: str
    paper_exit_timestamp: datetime
    demo_exit_timestamp: datetime
    paper_exit_price: Decimal = Field(gt=0)
    demo_exit_price: Decimal = Field(gt=0)
    exit_slippage_difference: Decimal
    cost_difference: Decimal
    pnl_difference: Decimal
    holding_period_difference_seconds: Decimal
    exit_reason_difference: bool
    comparison_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("paper_exit_timestamp", "demo_exit_timestamp")
    @classmethod
    def comparison_timestamp(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_comparison(self) -> Self:
        expected = fingerprint(
            self.model_dump(mode="python", exclude={"comparison_id", "comparison_fingerprint"})
        )
        if self.comparison_id != expected or self.comparison_fingerprint != expected:
            raise ValueError("Paper versus Demo exit comparison fingerprint is invalid")
        return self


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("lifecycle timestamps must be timezone-aware UTC")
    return value.astimezone(UTC)


def _contains_float(value: object) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_contains_float(item) for item in value.values())
    if isinstance(value, (tuple, list)):
        return any(_contains_float(item) for item in value)
    return False
