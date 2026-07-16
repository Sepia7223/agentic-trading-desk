"""Immutable domain contracts for deterministic risk evaluation."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RiskModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=True)

    @model_validator(mode="before")
    @classmethod
    def reject_binary_floats(cls, value: object) -> object:
        if _contains_float(value):
            raise ValueError("binary floating point is prohibited in risk models")
        return value


class TradeDirection(StrEnum):
    LONG = "LONG"


class AssetClass(StrEnum):
    FOREX = "FOREX"
    INDEX = "INDEX"
    SHARE = "SHARE"
    COMMODITY = "COMMODITY"
    RATE = "RATE"
    OTHER = "OTHER"


class RiskMarketStatus(StrEnum):
    TRADEABLE = "TRADEABLE"
    CLOSED = "CLOSED"
    OFFLINE = "OFFLINE"
    SUSPENDED = "SUSPENDED"
    UNKNOWN = "UNKNOWN"


class RiskDecisionStatus(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    KILL_SWITCHED = "KILL_SWITCHED"
    INVALID_INPUT = "INVALID_INPUT"


class DailyLossPolicy(StrEnum):
    REALIZED_ONLY = "REALIZED_ONLY"
    REALIZED_AND_UNREALIZED = "REALIZED_AND_UNREALIZED"


class RiskGate(StrEnum):
    INPUT_INTEGRITY = "INPUT_INTEGRITY"
    KILL_SWITCH = "KILL_SWITCH"
    CONFIGURATION = "CONFIGURATION"
    CANDIDATE_FRESHNESS = "CANDIDATE_FRESHNESS"
    MARKET_DATA_FRESHNESS = "MARKET_DATA_FRESHNESS"
    MARKET_ELIGIBILITY = "MARKET_ELIGIBILITY"
    HOLDING_STATE = "HOLDING_STATE"
    ENTRY_STOP = "ENTRY_STOP"
    ACCOUNT_STATE = "ACCOUNT_STATE"
    LOSS_AND_DRAWDOWN = "LOSS_AND_DRAWDOWN"
    POSITION_COUNTS = "POSITION_COUNTS"
    RISK_BUDGET = "RISK_BUDGET"
    RAW_SIZING = "RAW_SIZING"
    QUANTITY_CONSTRAINTS = "QUANTITY_CONSTRAINTS"
    EXPOSURE = "EXPOSURE"
    FINAL_RISK = "FINAL_RISK"


class RiskReasonCode(StrEnum):
    CANDIDATE_EXPIRED = "CANDIDATE_EXPIRED"
    SIGNAL_TIMESTAMP_IN_FUTURE = "SIGNAL_TIMESTAMP_IN_FUTURE"
    MARKET_DATA_STALE = "MARKET_DATA_STALE"
    MARKET_CLOSED = "MARKET_CLOSED"
    INVALID_BID_ASK = "INVALID_BID_ASK"
    SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
    UNKNOWN_HOLDING_STATE = "UNKNOWN_HOLDING_STATE"
    POSITION_ALREADY_OPEN = "POSITION_ALREADY_OPEN"
    INVALID_STOP_DIRECTION = "INVALID_STOP_DIRECTION"
    STOP_TOO_CLOSE = "STOP_TOO_CLOSE"
    STOP_TOO_FAR = "STOP_TOO_FAR"
    ACCOUNT_STATE_UNKNOWN = "ACCOUNT_STATE_UNKNOWN"
    MARKET_STATE_UNKNOWN = "MARKET_STATE_UNKNOWN"
    INSUFFICIENT_EQUITY = "INSUFFICIENT_EQUITY"
    INSUFFICIENT_AVAILABLE_CAPITAL = "INSUFFICIENT_AVAILABLE_CAPITAL"
    DAILY_REALIZED_LOSS_LIMIT_REACHED = "DAILY_REALIZED_LOSS_LIMIT_REACHED"
    DAILY_TOTAL_LOSS_LIMIT_REACHED = "DAILY_TOTAL_LOSS_LIMIT_REACHED"
    DRAWDOWN_LIMIT_REACHED = "DRAWDOWN_LIMIT_REACHED"
    MAX_OPEN_POSITIONS_REACHED = "MAX_OPEN_POSITIONS_REACHED"
    MAX_INSTRUMENT_POSITIONS_REACHED = "MAX_INSTRUMENT_POSITIONS_REACHED"
    GROSS_EXPOSURE_LIMIT = "GROSS_EXPOSURE_LIMIT"
    INSTRUMENT_EXPOSURE_LIMIT = "INSTRUMENT_EXPOSURE_LIMIT"
    ASSET_CLASS_EXPOSURE_LIMIT = "ASSET_CLASS_EXPOSURE_LIMIT"
    MAX_CONSECUTIVE_LOSSES_REACHED = "MAX_CONSECUTIVE_LOSSES_REACHED"
    SIZE_BELOW_MINIMUM = "SIZE_BELOW_MINIMUM"
    SIZE_ABOVE_MAXIMUM = "SIZE_ABOVE_MAXIMUM"
    INVALID_QUANTITY_INCREMENT = "INVALID_QUANTITY_INCREMENT"
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
    CONFIGURATION_MISMATCH = "CONFIGURATION_MISMATCH"
    INVALID_INPUT = "INVALID_INPUT"


class ExposureAmount(RiskModel):
    key: str = Field(min_length=1, max_length=100)
    amount: Decimal


class PositionCount(RiskModel):
    key: str = Field(min_length=1, max_length=100)
    count: int


class TradeCandidate(RiskModel):
    candidate_id: str = Field(min_length=1, max_length=128)
    signal_id: str = Field(min_length=1, max_length=128)
    instrument: str = Field(min_length=1, max_length=200)
    epic: str = Field(min_length=1, max_length=80)
    asset_class: AssetClass
    direction: TradeDirection = TradeDirection.LONG
    strategy_variant: str = Field(min_length=1, max_length=80)
    signal_timestamp: datetime
    data_cutoff_timestamp: datetime
    candidate_expiry: datetime
    entry_reference: Decimal | None
    stop_reference: Decimal | None
    target_reference: Decimal | None = None
    bid: Decimal | None
    ask: Decimal | None
    spread_bps: Decimal | None
    volatility_or_atr: Decimal | None
    market_status: RiskMarketStatus
    holding_state: bool | None
    strategy_configuration_fingerprint: str

    @field_validator("signal_timestamp", "data_cutoff_timestamp", "candidate_expiry")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("risk timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)


class AccountRiskState(RiskModel):
    snapshot_id: str = Field(min_length=1, max_length=128)
    timestamp: datetime
    account_equity: Decimal | None
    available_capital: Decimal | None
    realized_daily_pnl: Decimal | None
    unrealized_pnl: Decimal | None
    current_drawdown_fraction: Decimal | None
    gross_exposure: Decimal | None
    open_risk_amount: Decimal | None
    open_position_count: int | None
    instrument_exposure: tuple[ExposureAmount, ...]
    asset_class_exposure: tuple[ExposureAmount, ...]
    instrument_position_count: tuple[PositionCount, ...]
    consecutive_losses: int | None
    kill_switch_active: bool
    state_complete: bool

    @field_validator("timestamp")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("account timestamp must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def unique_exposure_keys(self) -> Self:
        for items in (
            self.instrument_exposure,
            self.asset_class_exposure,
            self.instrument_position_count,
        ):
            keys = [item.key for item in items]
            if len(keys) != len(set(keys)):
                raise ValueError("account exposure keys must be unique")
        return self

    def instrument_exposure_for(self, epic: str) -> Decimal | None:
        return next((item.amount for item in self.instrument_exposure if item.key == epic), None)

    def asset_class_exposure_for(self, asset_class: AssetClass) -> Decimal | None:
        return next(
            (item.amount for item in self.asset_class_exposure if item.key == asset_class.value),
            None,
        )

    def instrument_positions_for(self, epic: str) -> int | None:
        return next(
            (item.count for item in self.instrument_position_count if item.key == epic), None
        )


class MarketRiskState(RiskModel):
    snapshot_id: str = Field(min_length=1, max_length=128)
    instrument: str = Field(min_length=1, max_length=200)
    epic: str = Field(min_length=1, max_length=80)
    timestamp: datetime
    market_status: RiskMarketStatus
    bid: Decimal | None
    ask: Decimal | None
    spread_bps: Decimal | None
    minimum_deal_size: Decimal | None
    quantity_increment: Decimal | None
    minimum_stop_distance: Decimal | None
    maximum_stop_distance: Decimal | None
    value_per_price_unit: Decimal | None
    state_complete: bool

    @field_validator("timestamp")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("market timestamp must be timezone-aware UTC")
        return value.astimezone(UTC)


class GateResult(RiskModel):
    gate: RiskGate
    passed: bool
    reason_codes: tuple[RiskReasonCode, ...] = ()


class ApprovedTradeIntent(RiskModel):
    risk_decision_id: str = Field(min_length=64, max_length=64)
    candidate_id: str
    instrument: str
    epic: str
    direction: TradeDirection
    approved_quantity: Decimal
    entry_reference: Decimal
    stop_reference: Decimal
    target_reference: Decimal | None
    risk_amount: Decimal
    notional_exposure: Decimal
    approval_timestamp: datetime
    expiry_timestamp: datetime
    strategy_configuration_fingerprint: str
    risk_configuration_fingerprint: str = Field(min_length=64, max_length=64)
    account_snapshot_id: str
    market_snapshot_id: str

    @field_validator("approval_timestamp", "expiry_timestamp")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("approved intent timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    def is_valid_at(self, evaluation_timestamp: datetime) -> bool:
        if evaluation_timestamp.tzinfo is None:
            raise ValueError("intent evaluation timestamp must be timezone-aware")
        return self.approval_timestamp <= evaluation_timestamp < self.expiry_timestamp


class RiskDecision(RiskModel):
    decision_id: str = Field(min_length=64, max_length=64)
    candidate_id: str
    signal_id: str
    decision_timestamp: datetime
    status: RiskDecisionStatus
    proposed_quantity: Decimal | None
    approved_quantity: Decimal | None
    approved_entry_reference: Decimal | None
    approved_stop_reference: Decimal | None
    approved_target_reference: Decimal | None
    risk_budget: Decimal | None
    risk_amount: Decimal | None
    risk_fraction: Decimal | None
    notional_exposure: Decimal | None
    daily_loss_policy: DailyLossPolicy
    passed_gates: tuple[RiskGate, ...]
    failed_gates: tuple[RiskGate, ...]
    gate_results: tuple[GateResult, ...]
    reason_codes: tuple[RiskReasonCode, ...]
    candidate_expiry: datetime
    strategy_configuration_fingerprint: str
    risk_configuration_fingerprint: str = Field(min_length=64, max_length=64)
    account_snapshot_id: str
    market_snapshot_id: str
    approved_intent: ApprovedTradeIntent | None
    decision_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("decision_timestamp", "candidate_expiry")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("decision timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_decision_contract(self) -> Self:
        if self.status is RiskDecisionStatus.APPROVED:
            required = (
                self.approved_quantity,
                self.approved_entry_reference,
                self.approved_stop_reference,
                self.risk_budget,
                self.risk_amount,
                self.risk_fraction,
                self.notional_exposure,
                self.approved_intent,
            )
            if any(value is None for value in required):
                raise ValueError("approved decision is incomplete")
            if self.reason_codes or self.failed_gates:
                raise ValueError("approved decision cannot contain failures")
        elif not self.reason_codes or not self.failed_gates:
            raise ValueError("non-approved decision requires stable failure reasons")
        return self


def _contains_float(value: object) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_contains_float(item) for item in value.values())
    if isinstance(value, (tuple, list)):
        return any(_contains_float(item) for item in value)
    return False
