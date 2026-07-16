"""Immutable disabled-by-default controlled-execution configuration."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trading_desk.config import IG_DEMO_BASE_URL, BrokerSettings
from trading_desk.execution.fingerprints import fingerprint


class ExecutionConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    schema_version: Literal["controlled-execution-v1"] = "controlled-execution-v1"
    execution_enabled: bool = False
    automatic_execution_enabled: Literal[False] = False
    require_operator_confirmation: Literal[True] = True
    maximum_orders_per_run: int = Field(default=1, ge=1, le=1)
    maximum_orders_per_day: int = Field(default=1, ge=1, le=10)
    maximum_order_quantity: Decimal = Field(default=Decimal("1"), gt=0)
    maximum_order_notional: Decimal = Field(default=Decimal("10000"), gt=0)
    maximum_intent_age: timedelta = Field(default=timedelta(minutes=5), gt=timedelta(0))
    maximum_market_snapshot_age: timedelta = Field(default=timedelta(seconds=30), gt=timedelta(0))
    maximum_account_snapshot_age: timedelta = Field(default=timedelta(seconds=30), gt=timedelta(0))
    maximum_confirmation_wait_seconds: Decimal = Field(default=Decimal("10"), gt=0, le=60)
    confirmation_poll_interval_seconds: Decimal = Field(default=Decimal("0.5"), gt=0, le=10)
    allow_market_orders: Literal[True] = True
    allow_limit_orders: Literal[False] = False
    allow_stop_orders: Literal[False] = False
    allow_position_open: Literal[True] = True
    allow_position_close: Literal[False] = False
    allow_position_amendment: Literal[False] = False
    allow_working_orders: Literal[False] = False
    allow_account_switch: Literal[False] = False
    force_open: Literal[True] = True
    guaranteed_stop: Literal[False] = False
    reject_on_price_drift_bps: Decimal = Field(default=Decimal("10"), ge=0)
    reject_on_spread_change_bps: Decimal = Field(default=Decimal("5"), ge=0)
    reject_on_account_state_change: Literal[True] = True
    reject_on_market_state_change: Literal[True] = True
    demo_gateway: str = IG_DEMO_BASE_URL

    @model_validator(mode="before")
    @classmethod
    def reject_binary_floats(cls, value: object) -> object:
        if _contains_float(value):
            raise ValueError("binary floating point is prohibited in execution configuration")
        return value

    @model_validator(mode="after")
    def validate_safety_boundary(self) -> Self:
        canonical = BrokerSettings(base_url=self.demo_gateway).base_url
        if canonical != IG_DEMO_BASE_URL:
            raise ValueError("execution requires the canonical IG Demo gateway")
        if self.confirmation_poll_interval_seconds > self.maximum_confirmation_wait_seconds:
            raise ValueError("confirmation poll interval exceeds confirmation wait")
        return self

    @property
    def fingerprint(self) -> str:
        return fingerprint(self)


def _contains_float(value: object) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_contains_float(item) for item in value.values())
    if isinstance(value, (tuple, list)):
        return any(_contains_float(item) for item in value)
    return False
