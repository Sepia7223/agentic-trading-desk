"""Strict normalized domain models for read-only IG responses."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field


class ForwardCompatibleStrEnum(StrEnum):
    """Use named values when known while retaining future string values."""

    @classmethod
    def _missing_(cls, value: object) -> Self | None:
        if not isinstance(value, str):
            return None
        member = str.__new__(cls, value)
        member._name_ = f"UNRECOGNIZED_{len(cls.__members__)}"
        member._value_ = value
        return member


class AccountType(ForwardCompatibleStrEnum):
    CFD = "CFD"
    SPREAD_BET = "SPREADBET"
    PHYSICAL = "PHYSICAL"


class Direction(ForwardCompatibleStrEnum):
    BUY = "BUY"
    SELL = "SELL"


class MarketStatus(ForwardCompatibleStrEnum):
    TRADEABLE = "TRADEABLE"
    CLOSED = "CLOSED"
    EDITS_ONLY = "EDITS_ONLY"
    OFFLINE = "OFFLINE"
    ON_AUCTION = "ON_AUCTION"
    ON_AUCTION_NO_EDITS = "ON_AUCTION_NO_EDITS"
    SUSPENDED = "SUSPENDED"


class InstrumentType(ForwardCompatibleStrEnum):
    CURRENCIES = "CURRENCIES"
    INDICES = "INDICES"
    SHARES = "SHARES"
    COMMODITIES = "COMMODITIES"
    RATES = "RATES"
    OPTIONS = "OPTIONS"


class DealingRuleUnit(ForwardCompatibleStrEnum):
    POINTS = "POINTS"
    PERCENTAGE = "PERCENTAGE"


class PriceResolution(StrEnum):
    DAY = "DAY"
    HOUR = "HOUR"
    HOUR_4 = "HOUR_4"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AuthenticatedSessionSummary(StrictModel):
    account_id: str
    client_id: str
    timezone_offset: int | None = None
    lightstreamer_endpoint: str | None = None
    environment: str


class AccountBalance(StrictModel):
    balance: Decimal
    deposit: Decimal
    profit_loss: Decimal
    available_funds: Decimal


class Account(StrictModel):
    account_id: str
    account_name: str
    account_type: AccountType
    preferred: bool
    currency: str
    balance: AccountBalance


class PositionMarketSnapshot(StrictModel):
    epic: str
    instrument_name: str
    bid: Decimal | None = None
    offer: Decimal | None = None
    market_status: MarketStatus
    update_time_utc: datetime | None = None


class OpenPosition(StrictModel):
    deal_id: str
    deal_reference: str | None = None
    direction: Direction
    size: Decimal
    opening_level: Decimal
    stop_level: Decimal | None = None
    limit_level: Decimal | None = None
    controlled_risk: bool
    currency: str
    created_at: datetime
    market: PositionMarketSnapshot


class MarketSearchResult(StrictModel):
    epic: str
    instrument_name: str
    instrument_type: InstrumentType
    market_status: MarketStatus
    bid: Decimal | None = None
    offer: Decimal | None = None
    expiry: str | None = None


class DealingRuleValue(StrictModel):
    value: Decimal
    unit: DealingRuleUnit


class MarketDetails(StrictModel):
    epic: str
    instrument_name: str
    instrument_type: InstrumentType
    expiry: str | None = None
    market_status: MarketStatus
    bid: Decimal | None = None
    offer: Decimal | None = None
    update_time_utc: datetime | None = None
    controlled_risk_allowed: bool | None = None
    min_deal_size: DealingRuleValue | None = None
    min_normal_stop_or_limit_distance: DealingRuleValue | None = None
    max_stop_or_limit_distance: DealingRuleValue | None = None


class HistoricalPriceValue(StrictModel):
    bid: Decimal | None = None
    ask: Decimal | None = None
    last_traded: Decimal | None = None

    @property
    def midpoint(self) -> Decimal | None:
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / Decimal("2")


class HistoricalPriceBar(StrictModel):
    timestamp: datetime
    open: HistoricalPriceValue
    high: HistoricalPriceValue
    low: HistoricalPriceValue
    close: HistoricalPriceValue
    last_traded_volume: Decimal | None = None
    valid_for_strategy: bool
    validation_reason: str | None = None

    @property
    def midpoint_open(self) -> Decimal | None:
        return self.open.midpoint

    @property
    def midpoint_high(self) -> Decimal | None:
        return self.high.midpoint

    @property
    def midpoint_low(self) -> Decimal | None:
        return self.low.midpoint

    @property
    def midpoint_close(self) -> Decimal | None:
        return self.close.midpoint

    @property
    def last_traded(self) -> Decimal | None:
        return self.close.last_traded


class PaginationMetadata(StrictModel):
    page_number: int = Field(ge=1)
    page_size: int = Field(ge=0)
    total_pages: int = Field(ge=0)


class APIAllowanceMetadata(StrictModel):
    allowance_expiry_seconds: int = Field(ge=0)
    remaining_allowance: int = Field(ge=0)
    total_allowance: int = Field(ge=0)


class HistoricalPricePage(StrictModel):
    bars: tuple[HistoricalPriceBar, ...]
    pagination: PaginationMetadata
    allowance: APIAllowanceMetadata

    @property
    def strategy_ready_closes(self) -> tuple[Decimal, ...]:
        closes: list[Decimal] = []
        for bar in self.bars:
            midpoint = bar.midpoint_close
            if bar.valid_for_strategy and midpoint is not None:
                closes.append(midpoint)
        return tuple(closes)
