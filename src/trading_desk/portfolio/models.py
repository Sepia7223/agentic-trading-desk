"""Immutable models for simulated positions, fills, events, and accounting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.risk.models import AssetClass, TradeDirection


class PortfolioModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def reject_floats(cls, value: object) -> object:
        if _contains_float(value):
            raise ValueError("binary floating point is prohibited in portfolio models")
        return value


class PositionStatus(StrEnum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNRESOLVED = "UNRESOLVED"


class EventType(StrEnum):
    PORTFOLIO_CREATED = "PORTFOLIO_CREATED"
    INTENT_ACCEPTED = "INTENT_ACCEPTED"
    INTENT_REJECTED = "INTENT_REJECTED"
    POSITION_OPENED = "POSITION_OPENED"
    POSITION_MARKED = "POSITION_MARKED"
    FUNDING_APPLIED = "FUNDING_APPLIED"
    STOP_TRIGGERED = "STOP_TRIGGERED"
    TARGET_TRIGGERED = "TARGET_TRIGGERED"
    SCHEDULED_EXIT = "SCHEDULED_EXIT"
    POSITION_CLOSED = "POSITION_CLOSED"
    POSITION_UNRESOLVED = "POSITION_UNRESOLVED"
    STATE_SNAPSHOT_CREATED = "STATE_SNAPSHOT_CREATED"


class FillSide(StrEnum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"


class FillReason(StrEnum):
    ENTRY = "ENTRY"
    STOP = "STOP"
    TARGET = "TARGET"
    SCHEDULED_EXIT = "SCHEDULED_EXIT"
    MANUAL_SIMULATED_EXIT = "MANUAL_SIMULATED_EXIT"
    FORCED_END_OF_DATA_LIQUIDATION = "FORCED_END_OF_DATA_LIQUIDATION"


class IntentRejectionCode(StrEnum):
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    APPROVAL_NOT_APPROVED = "APPROVAL_NOT_APPROVED"
    APPROVAL_FINGERPRINT_MISMATCH = "APPROVAL_FINGERPRINT_MISMATCH"
    STRATEGY_FINGERPRINT_MISMATCH = "STRATEGY_FINGERPRINT_MISMATCH"
    RISK_FINGERPRINT_MISMATCH = "RISK_FINGERPRINT_MISMATCH"
    PORTFOLIO_STATE_MISMATCH = "PORTFOLIO_STATE_MISMATCH"
    MARKET_STATE_MISMATCH = "MARKET_STATE_MISMATCH"
    DUPLICATE_INTENT = "DUPLICATE_INTENT"
    POSITION_ALREADY_EXISTS = "POSITION_ALREADY_EXISTS"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    INVALID_QUANTITY = "INVALID_QUANTITY"
    INVALID_STOP = "INVALID_STOP"
    INVALID_TARGET = "INVALID_TARGET"
    MARKET_NOT_TRADEABLE = "MARKET_NOT_TRADEABLE"
    INVALID_BID_ASK = "INVALID_BID_ASK"
    PORTFOLIO_LIMIT_REACHED = "PORTFOLIO_LIMIT_REACHED"
    UNSUPPORTED_DIRECTION = "UNSUPPORTED_DIRECTION"
    INVALID_INPUT = "INVALID_INPUT"


class MarketQuote(PortfolioModel):
    snapshot_id: str = Field(min_length=1, max_length=128)
    timestamp: datetime
    epic: str = Field(min_length=1, max_length=80)
    bid: Decimal | None
    ask: Decimal | None
    market_status: str
    value_per_price_unit: Decimal = Field(default=Decimal("1"), gt=0)

    @field_validator("timestamp")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @property
    def tradeable(self) -> bool:
        return self.market_status == "TRADEABLE"


class MarketBar(PortfolioModel):
    snapshot_id: str = Field(min_length=1, max_length=128)
    timestamp: datetime
    epic: str = Field(min_length=1, max_length=80)
    low_bid: Decimal | None
    high_bid: Decimal | None
    close_bid: Decimal | None
    close_ask: Decimal | None
    market_status: str

    @field_validator("timestamp")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @property
    def tradeable(self) -> bool:
        return self.market_status == "TRADEABLE"


class SimulatedFill(PortfolioModel):
    fill_id: str = Field(min_length=64, max_length=64)
    position_id: str = Field(min_length=64, max_length=64)
    risk_decision_id: str
    side: FillSide
    quantity: Decimal = Field(gt=0)
    reference_price: Decimal = Field(gt=0)
    slippage: Decimal = Field(ge=0)
    fill_price: Decimal = Field(gt=0)
    commission: Decimal = Field(ge=0)
    funding: Decimal = Field(ge=0)
    timestamp: datetime
    fill_reason: FillReason

    @field_validator("timestamp")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        return _require_utc(value)


class PaperPosition(PortfolioModel):
    position_id: str = Field(min_length=64, max_length=64)
    instrument: str
    epic: str
    asset_class: AssetClass
    direction: TradeDirection
    quantity: Decimal = Field(gt=0)
    entry_timestamp: datetime
    entry_price: Decimal = Field(gt=0)
    current_mark_timestamp: datetime
    current_mark_price: Decimal = Field(gt=0)
    stop_price: Decimal = Field(gt=0)
    target_price: Decimal | None = Field(default=None, gt=0)
    gross_unrealized_pnl: Decimal
    net_unrealized_pnl: Decimal
    accrued_funding: Decimal = Field(ge=0)
    entry_commission: Decimal = Field(ge=0)
    entry_slippage_cost: Decimal = Field(ge=0)
    current_exposure: Decimal = Field(ge=0)
    open_risk_amount: Decimal = Field(ge=0)
    value_per_price_unit: Decimal = Field(gt=0)
    maximum_favorable_excursion: Decimal = Field(ge=0)
    maximum_adverse_excursion: Decimal = Field(ge=0)
    risk_decision_id: str
    candidate_id: str
    signal_id: str
    strategy_configuration_fingerprint: str
    risk_configuration_fingerprint: str
    status: PositionStatus

    @field_validator("entry_timestamp", "current_mark_timestamp")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        return _require_utc(value)


class DailyAccounting(PortfolioModel):
    trading_day: str
    start_of_day_equity: Decimal
    realized_daily_pnl: Decimal
    peak_equity: Decimal
    consecutive_losses: int = Field(ge=0)


class PortfolioState(PortfolioModel):
    portfolio_id: str = Field(min_length=1, max_length=128)
    snapshot_id: str = Field(min_length=64, max_length=64)
    timestamp: datetime
    base_currency: str
    initial_cash: Decimal
    cash: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    equity: Decimal
    gross_exposure: Decimal = Field(ge=0)
    net_exposure: Decimal
    open_risk_amount: Decimal = Field(ge=0)
    open_position_count: int = Field(ge=0)
    positions: tuple[PaperPosition, ...]
    daily: DailyAccounting
    ledger_sequence: int = Field(ge=0)
    configuration_fingerprint: str = Field(min_length=64, max_length=64)
    state_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("timestamp")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        return _require_utc(value)


class PortfolioEvent(PortfolioModel):
    event_id: str = Field(min_length=64, max_length=64)
    sequence_number: int = Field(ge=1)
    event_type: EventType
    timestamp: datetime
    portfolio_id: str
    position_id: str | None
    risk_decision_id: str | None
    candidate_id: str | None
    payload: str
    previous_event_fingerprint: str | None
    event_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("timestamp")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        return _require_utc(value)


class ClosedTradeRecord(PortfolioModel):
    trade_id: str = Field(min_length=64, max_length=64)
    position_id: str
    risk_decision_id: str
    candidate_id: str
    signal_id: str
    instrument: str
    direction: TradeDirection
    quantity: Decimal
    entry_timestamp: datetime
    entry_price: Decimal
    exit_timestamp: datetime
    exit_price: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal
    entry_commission: Decimal
    exit_commission: Decimal
    funding: Decimal
    slippage_cost: Decimal
    holding_period: timedelta
    exit_reason: FillReason
    maximum_favorable_excursion: Decimal
    maximum_adverse_excursion: Decimal
    strategy_configuration_fingerprint: str
    risk_configuration_fingerprint: str
    portfolio_configuration_fingerprint: str
    trade_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("entry_timestamp", "exit_timestamp")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        return _require_utc(value)


class IntentRejection(PortfolioModel):
    risk_decision_id: str
    timestamp: datetime
    reason_codes: tuple[IntentRejectionCode, ...]

    @field_validator("timestamp")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        return _require_utc(value)


class PositionOpenResult(PortfolioModel):
    accepted: bool
    position: PaperPosition | None = None
    fill: SimulatedFill | None = None
    rejection: IntentRejection | None = None


class PositionCloseResult(PortfolioModel):
    position: PaperPosition
    fill: SimulatedFill
    trade: ClosedTradeRecord


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("portfolio timestamps must be timezone-aware UTC")
    return value.astimezone(UTC)


def _contains_float(value: object) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_contains_float(item) for item in value.values())
    if isinstance(value, (tuple, list)):
        return any(_contains_float(item) for item in value)
    return False
