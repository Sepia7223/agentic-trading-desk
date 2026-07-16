"""Immutable safety limits for the deterministic risk engine."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.risk.fingerprints import model_fingerprint


class RiskConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    schema_version: Literal["risk-schema-v1"] = "risk-schema-v1"
    risk_per_trade_fraction: Decimal = Field(default=Decimal("0.01"), gt=0, le=1)
    maximum_daily_realized_loss_fraction: Decimal = Field(default=Decimal("0.03"), gt=0, le=1)
    maximum_daily_total_loss_fraction: Decimal = Field(default=Decimal("0.05"), gt=0, le=1)
    maximum_portfolio_drawdown_fraction: Decimal = Field(default=Decimal("0.10"), gt=0, le=1)
    maximum_gross_exposure_fraction: Decimal = Field(default=Decimal("1.00"), gt=0, le=1)
    maximum_instrument_exposure_fraction: Decimal = Field(default=Decimal("0.20"), gt=0, le=1)
    maximum_asset_class_exposure_fraction: Decimal = Field(default=Decimal("0.50"), gt=0, le=1)
    maximum_open_positions: int = Field(default=5, ge=1, le=1000)
    maximum_positions_per_instrument: int = Field(default=1, ge=1, le=100)
    maximum_spread_bps: Decimal = Field(default=Decimal("10"), ge=0)
    minimum_stop_distance: Decimal = Field(default=Decimal("0.0001"), gt=0)
    maximum_stop_distance: Decimal = Field(default=Decimal("1000000"), gt=0)
    maximum_candidate_age: timedelta = timedelta(minutes=5)
    maximum_market_data_age: timedelta = timedelta(minutes=1)
    maximum_account_state_age: timedelta = timedelta(minutes=5)
    maximum_market_signal_lag: timedelta = timedelta(minutes=5)
    maximum_consecutive_losses: int = Field(default=3, ge=1, le=1000)
    consecutive_loss_limit_enabled: bool = True
    quantity_increment: Decimal = Field(default=Decimal("0.01"), gt=0)
    minimum_approved_quantity: Decimal = Field(default=Decimal("0.01"), gt=0)
    maximum_approved_quantity: Decimal = Field(default=Decimal("1000000"), gt=0)
    kill_switch_enabled: Literal[True] = True
    include_unrealized_in_daily_loss: bool = True
    long_only: Literal[True] = True
    required_strategy_configuration_fingerprint: str | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_binary_floats(cls, value: object) -> object:
        if isinstance(value, dict) and any(isinstance(item, float) for item in value.values()):
            raise ValueError("binary floating point is prohibited in risk configuration")
        return value

    @field_validator(
        "maximum_candidate_age",
        "maximum_market_data_age",
        "maximum_account_state_age",
        "maximum_market_signal_lag",
    )
    @classmethod
    def positive_duration(cls, value: timedelta) -> timedelta:
        if value <= timedelta(0):
            raise ValueError("risk durations must be positive")
        return value

    @field_validator("required_strategy_configuration_fingerprint")
    @classmethod
    def valid_optional_fingerprint(cls, value: str | None) -> str | None:
        if value is not None and (
            len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
        ):
            raise ValueError("required strategy fingerprint must be lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def validate_ranges(self) -> Self:
        if self.minimum_stop_distance > self.maximum_stop_distance:
            raise ValueError("stop-distance bounds are reversed")
        if self.minimum_approved_quantity > self.maximum_approved_quantity:
            raise ValueError("quantity bounds are reversed")
        return self

    @property
    def fingerprint(self) -> str:
        return model_fingerprint(self)
