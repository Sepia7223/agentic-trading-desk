"""Immutable deterministic paper portfolio configuration."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trading_desk.portfolio.fingerprints import model_fingerprint


class MarkPricePolicy(StrEnum):
    LIQUIDATION_SIDE = "LIQUIDATION_SIDE"


class EndOfDataPolicy(StrEnum):
    UNRESOLVED = "UNRESOLVED"
    LIQUIDATE_IF_TRADEABLE = "LIQUIDATE_IF_TRADEABLE"


class CommissionPolicy(StrEnum):
    FIXED_PLUS_BPS = "FIXED_PLUS_BPS"


class FundingPolicy(StrEnum):
    UTC_DAILY = "UTC_DAILY"


class SlippagePolicy(StrEnum):
    ADVERSE_BPS = "ADVERSE_BPS"


class IntrabarPolicy(StrEnum):
    ADVERSE_FIRST = "ADVERSE_FIRST"
    FAVORABLE_FIRST = "FAVORABLE_FIRST"
    REJECT_AMBIGUOUS = "REJECT_AMBIGUOUS"


class PaperPortfolioConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    schema_version: Literal["paper-portfolio-v1"] = "paper-portfolio-v1"
    base_currency: str = Field(default="USD", min_length=3, max_length=3)
    initial_cash: Decimal = Field(default=Decimal("100000"), gt=0)
    allow_partial_fills: bool = False
    allow_pyramiding: bool = False
    allow_multiple_positions_per_instrument: bool = False
    mark_price_policy: Literal[MarkPricePolicy.LIQUIDATION_SIDE] = MarkPricePolicy.LIQUIDATION_SIDE
    end_of_data_policy: EndOfDataPolicy = EndOfDataPolicy.UNRESOLVED
    maximum_open_positions: int = Field(default=5, ge=1, le=1000)
    maximum_positions_per_instrument: int = Field(default=1, ge=1, le=100)
    quantity_precision: int = Field(default=2, ge=0, le=12)
    price_precision: int = Field(default=6, ge=0, le=12)
    cash_precision: int = Field(default=2, ge=0, le=12)
    commission_policy: CommissionPolicy = CommissionPolicy.FIXED_PLUS_BPS
    fixed_commission_per_fill: Decimal = Field(default=Decimal("0"), ge=0)
    commission_bps: Decimal = Field(default=Decimal("0"), ge=0)
    funding_policy: FundingPolicy = FundingPolicy.UTC_DAILY
    funding_bps_per_utc_day: Decimal = Field(default=Decimal("0"), ge=0)
    slippage_policy: SlippagePolicy = SlippagePolicy.ADVERSE_BPS
    slippage_bps: Decimal = Field(default=Decimal("0"), ge=0)
    intrabar_policy: IntrabarPolicy = IntrabarPolicy.ADVERSE_FIRST
    valuation_timestamp_tolerance_seconds: int = Field(default=300, ge=0)
    approval_expiry_enforced: Literal[True] = True
    state_persistence_enabled: Literal[False] = False

    @model_validator(mode="before")
    @classmethod
    def reject_floats(cls, value: object) -> object:
        if isinstance(value, dict) and any(isinstance(item, float) for item in value.values()):
            raise ValueError("binary floating point is prohibited in portfolio configuration")
        return value

    @model_validator(mode="after")
    def validate_position_limits(self) -> Self:
        if self.maximum_positions_per_instrument > self.maximum_open_positions:
            raise ValueError("per-instrument position limit exceeds portfolio limit")
        return self

    @property
    def fingerprint(self) -> str:
        return model_fingerprint(self)
