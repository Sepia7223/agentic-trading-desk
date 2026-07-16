"""Immutable controlled-execution contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.execution.fingerprints import fingerprint


class ExecutionModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def reject_binary_floats(cls, value: object) -> object:
        if _contains_float(value):
            raise ValueError("binary floating point is prohibited in execution models")
        return value


class ExecutionDirection(StrEnum):
    BUY = "BUY"


class ExecutionOrderType(StrEnum):
    MARKET = "MARKET"


class PreflightStatus(StrEnum):
    READY = "READY"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    DISABLED = "DISABLED"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    KILL_SWITCHED = "KILL_SWITCHED"
    INVALID_INPUT = "INVALID_INPUT"


class ExecutionStatus(StrEnum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"
    TIMED_OUT = "TIMED_OUT"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class BrokerConfirmationStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PENDING = "PENDING"
    UNKNOWN = "UNKNOWN"


class ReconciliationStatus(StrEnum):
    RECONCILED = "RECONCILED"
    RECONCILIATION_MISMATCH = "RECONCILIATION_MISMATCH"
    POSITION_NOT_FOUND = "POSITION_NOT_FOUND"
    RECONCILIATION_PENDING = "RECONCILIATION_PENDING"


class ExecutionReasonCode(StrEnum):
    EXECUTION_DISABLED = "EXECUTION_DISABLED"
    AUTOMATIC_EXECUTION_DISABLED = "AUTOMATIC_EXECUTION_DISABLED"
    OPERATOR_CONFIRMATION_REQUIRED = "OPERATOR_CONFIRMATION_REQUIRED"
    OPERATOR_CONFIRMATION_INVALID = "OPERATOR_CONFIRMATION_INVALID"
    APPROVAL_NOT_APPROVED = "APPROVAL_NOT_APPROVED"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    APPROVAL_FINGERPRINT_MISMATCH = "APPROVAL_FINGERPRINT_MISMATCH"
    STRATEGY_FINGERPRINT_MISMATCH = "STRATEGY_FINGERPRINT_MISMATCH"
    RISK_FINGERPRINT_MISMATCH = "RISK_FINGERPRINT_MISMATCH"
    EXECUTION_FINGERPRINT_MISMATCH = "EXECUTION_FINGERPRINT_MISMATCH"
    DUPLICATE_EXECUTION_REQUEST = "DUPLICATE_EXECUTION_REQUEST"
    INTENT_ALREADY_CONSUMED = "INTENT_ALREADY_CONSUMED"
    UNSUPPORTED_DIRECTION = "UNSUPPORTED_DIRECTION"
    UNSUPPORTED_ORDER_TYPE = "UNSUPPORTED_ORDER_TYPE"
    QUANTITY_EXCEEDS_APPROVAL = "QUANTITY_EXCEEDS_APPROVAL"
    QUANTITY_EXCEEDS_EXECUTION_LIMIT = "QUANTITY_EXCEEDS_EXECUTION_LIMIT"
    NOTIONAL_EXCEEDS_EXECUTION_LIMIT = "NOTIONAL_EXCEEDS_EXECUTION_LIMIT"
    MARKET_CLOSED = "MARKET_CLOSED"
    MARKET_DATA_STALE = "MARKET_DATA_STALE"
    ACCOUNT_DATA_STALE = "ACCOUNT_DATA_STALE"
    INVALID_BID_ASK = "INVALID_BID_ASK"
    SPREAD_CHANGED = "SPREAD_CHANGED"
    PRICE_DRIFT_EXCEEDED = "PRICE_DRIFT_EXCEEDED"
    ACCOUNT_STATE_CHANGED = "ACCOUNT_STATE_CHANGED"
    MARKET_STATE_CHANGED = "MARKET_STATE_CHANGED"
    POSITION_ALREADY_EXISTS = "POSITION_ALREADY_EXISTS"
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
    MAX_ORDERS_PER_RUN_REACHED = "MAX_ORDERS_PER_RUN_REACHED"
    MAX_ORDERS_PER_DAY_REACHED = "MAX_ORDERS_PER_DAY_REACHED"
    QUANTITY_BELOW_MINIMUM = "QUANTITY_BELOW_MINIMUM"
    BROKER_REJECTED = "BROKER_REJECTED"
    BROKER_TIMEOUT = "BROKER_TIMEOUT"
    BROKER_RESPONSE_INVALID = "BROKER_RESPONSE_INVALID"
    BROKER_CONFIRMATION_UNKNOWN = "BROKER_CONFIRMATION_UNKNOWN"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    INVALID_INPUT = "INVALID_INPUT"


class ExecutionRequest(ExecutionModel):
    execution_request_id: str = Field(min_length=64, max_length=64)
    approved_intent_id: str = Field(min_length=64, max_length=64)
    risk_decision_id: str = Field(min_length=64, max_length=64)
    candidate_id: str
    signal_id: str
    instrument: str
    epic: str
    direction: ExecutionDirection
    order_type: ExecutionOrderType
    approved_quantity: Decimal = Field(gt=0)
    requested_quantity: Decimal = Field(gt=0)
    entry_reference: Decimal = Field(gt=0)
    stop_reference: Decimal = Field(gt=0)
    target_reference: Decimal | None = Field(default=None, gt=0)
    approved_spread_bps: Decimal = Field(ge=0)
    currency: str = Field(pattern=r"[A-Z]{3}")
    expiry: str = Field(default="-", pattern=r"(?:\d{2}-)?[A-Z]{3}-\d{2}|-|DFB")
    force_open: bool
    guaranteed_stop: bool
    approval_timestamp: datetime
    approval_expiry: datetime
    evaluation_timestamp: datetime
    strategy_configuration_fingerprint: str = Field(min_length=64, max_length=64)
    risk_configuration_fingerprint: str = Field(min_length=64, max_length=64)
    execution_configuration_fingerprint: str = Field(min_length=64, max_length=64)
    account_snapshot_id: str
    market_snapshot_id: str
    decision_fingerprint: str = Field(min_length=64, max_length=64)
    request_fingerprint: str = Field(min_length=64, max_length=64)
    operator_confirmation_id: str | None = Field(default=None, min_length=64, max_length=64)

    @field_validator("approval_timestamp", "approval_expiry", "evaluation_timestamp")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_fingerprint(self) -> Self:
        fields = self.model_dump(
            mode="python",
            exclude={"execution_request_id", "request_fingerprint", "operator_confirmation_id"},
        )
        expected = fingerprint(fields)
        if self.execution_request_id != expected or self.request_fingerprint != expected:
            raise ValueError("execution request fingerprint is invalid")
        return self


class OperatorConfirmation(ExecutionModel):
    confirmation_id: str = Field(min_length=64, max_length=64)
    execution_request_id: str
    request_fingerprint: str = Field(min_length=64, max_length=64)
    exact_quantity: Decimal = Field(gt=0)
    instrument: str
    direction: ExecutionDirection
    maximum_price_drift_bps: Decimal = Field(ge=0)
    confirmed_at: datetime
    expires_at: datetime
    confirmation_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("confirmed_at", "expires_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_confirmation(self) -> Self:
        expected = fingerprint(
            self.model_dump(mode="python", exclude={"confirmation_id", "confirmation_fingerprint"})
        )
        if self.confirmation_id != expected or self.confirmation_fingerprint != expected:
            raise ValueError("operator confirmation fingerprint is invalid")
        if self.expires_at <= self.confirmed_at:
            raise ValueError("operator confirmation expiry must follow confirmation")
        return self


class ExecutionPreflightResult(ExecutionModel):
    preflight_id: str = Field(min_length=64, max_length=64)
    execution_request_id: str
    status: PreflightStatus
    passed_gates: tuple[str, ...]
    failed_gates: tuple[str, ...]
    reason_codes: tuple[ExecutionReasonCode, ...]
    validated_quantity: Decimal | None = Field(default=None, gt=0)
    validated_entry_reference: Decimal | None = Field(default=None, gt=0)
    validated_stop_reference: Decimal | None = Field(default=None, gt=0)
    validated_target_reference: Decimal | None = Field(default=None, gt=0)
    account_snapshot_id: str
    market_snapshot_id: str
    execution_configuration_fingerprint: str = Field(min_length=64, max_length=64)
    preflight_fingerprint: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_fingerprint(self) -> Self:
        expected = fingerprint(
            self.model_dump(mode="python", exclude={"preflight_id", "preflight_fingerprint"})
        )
        if self.preflight_id != expected or self.preflight_fingerprint != expected:
            raise ValueError("execution preflight fingerprint is invalid")
        return self


class BrokerOrderRequest(ExecutionModel):
    deal_reference: str = Field(pattern=r"[A-Za-z0-9_-]{1,30}")
    epic: str = Field(pattern=r"[A-Za-z0-9._]{6,30}")
    direction: ExecutionDirection
    size: Decimal = Field(gt=0, decimal_places=12)
    order_type: ExecutionOrderType
    currency_code: str = Field(pattern=r"[A-Z]{3}")
    expiry: str
    force_open: bool
    guaranteed_stop: bool
    stop_level: Decimal = Field(gt=0)
    limit_level: Decimal | None = Field(default=None, gt=0)


class BrokerSubmission(ExecutionModel):
    deal_reference: str = Field(min_length=1, max_length=30)
    safe_request_id: str | None = Field(default=None, max_length=128)


class BrokerConfirmation(ExecutionModel):
    deal_reference: str
    deal_id: str | None = None
    status: BrokerConfirmationStatus
    broker_status: str | None = None
    broker_reason: str | None = None
    epic: str | None = None
    direction: ExecutionDirection | None = None
    executed_level: Decimal | None = None
    executed_size: Decimal | None = None
    stop_level: Decimal | None = None
    limit_level: Decimal | None = None
    confirmed_at: datetime

    @field_validator("confirmed_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        return _utc(value)


class ExecutionResult(ExecutionModel):
    execution_result_id: str = Field(min_length=64, max_length=64)
    execution_request_id: str
    preflight_id: str
    submitted_at: datetime | None
    completed_at: datetime
    status: ExecutionStatus
    reason_codes: tuple[ExecutionReasonCode, ...]
    deal_reference: str | None
    deal_id: str | None
    broker_status: str | None
    broker_reason: str | None
    requested_quantity: Decimal
    accepted_quantity: Decimal | None
    entry_level: Decimal | None
    stop_level: Decimal | None
    target_level: Decimal | None
    confirmation_status: BrokerConfirmationStatus | None
    safe_error_code: str | None
    safe_request_id: str | None
    account_snapshot_id: str
    market_snapshot_id: str
    request_fingerprint: str
    result_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("submitted_at", "completed_at")
    @classmethod
    def utc_timestamp(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @model_validator(mode="after")
    def require_failure_reason(self) -> Self:
        if self.status is not ExecutionStatus.ACCEPTED and not self.reason_codes:
            raise ValueError("non-accepted execution result requires reason codes")
        expected = fingerprint(
            self.model_dump(mode="python", exclude={"execution_result_id", "result_fingerprint"})
        )
        if self.execution_result_id != expected or self.result_fingerprint != expected:
            raise ValueError("execution result fingerprint is invalid")
        return self


class ReconciliationResult(ExecutionModel):
    reconciliation_id: str = Field(min_length=64, max_length=64)
    execution_result_id: str
    status: ReconciliationStatus
    checked_at: datetime
    deal_reference: str
    deal_id: str | None
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
            raise ValueError("execution reconciliation fingerprint is invalid")
        return self


class DemoPositionRecord(ExecutionModel):
    record_id: str = Field(min_length=64, max_length=64)
    execution_result_id: str
    reconciliation_id: str
    deal_reference: str
    deal_id: str
    instrument: str
    epic: str
    direction: ExecutionDirection
    quantity: Decimal
    entry_level: Decimal
    stop_level: Decimal
    target_level: Decimal | None
    recorded_at: datetime
    record_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("recorded_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_fingerprint(self) -> Self:
        expected = fingerprint(
            self.model_dump(mode="python", exclude={"record_id", "record_fingerprint"})
        )
        if self.record_id != expected or self.record_fingerprint != expected:
            raise ValueError("Demo position record fingerprint is invalid")
        return self


class ExecutionOutcome(ExecutionModel):
    preflight: ExecutionPreflightResult
    result: ExecutionResult
    reconciliation: ReconciliationResult | None = None
    demo_position: DemoPositionRecord | None = None


class ExecutionEventType(StrEnum):
    REQUEST_CREATED = "REQUEST_CREATED"
    PREFLIGHT_COMPLETED = "PREFLIGHT_COMPLETED"
    OPERATOR_CONFIRMED = "OPERATOR_CONFIRMED"
    SUBMISSION_ATTEMPTED = "SUBMISSION_ATTEMPTED"
    BROKER_RESPONDED = "BROKER_RESPONDED"
    CONFIRMATION_COMPLETED = "CONFIRMATION_COMPLETED"
    RECONCILIATION_COMPLETED = "RECONCILIATION_COMPLETED"
    EXECUTION_FAILED = "EXECUTION_FAILED"


class ExecutionJournalRecord(ExecutionModel):
    record_id: str = Field(min_length=64, max_length=64)
    sequence: int = Field(ge=1)
    event_type: ExecutionEventType
    timestamp: datetime
    signal_id: str | None
    candidate_id: str | None
    risk_decision_id: str | None
    approved_intent_id: str | None
    execution_request_id: str | None
    deal_reference: str | None
    deal_id: str | None
    payload_fingerprint: str = Field(min_length=64, max_length=64)
    previous_record_fingerprint: str | None
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
            raise ValueError("execution journal fingerprint is invalid")
        return self


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("execution timestamps must be timezone-aware UTC")
    return value.astimezone(UTC)


def _contains_float(value: object) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_contains_float(item) for item in value.values())
    if isinstance(value, (tuple, list)):
        return any(_contains_float(item) for item in value)
    return False
