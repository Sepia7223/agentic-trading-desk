"""Immutable disabled-by-default Demo position lifecycle configuration."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trading_desk.config import IG_DEMO_BASE_URL, BrokerEnvironment, BrokerSettings
from trading_desk.lifecycle.fingerprints import fingerprint


class LifecycleConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    schema_version: Literal["demo-position-lifecycle-v1"] = "demo-position-lifecycle-v1"
    enabled: bool = False
    automatic_exit_enabled: bool = False
    broker_environment: Literal[BrokerEnvironment.DEMO] = BrokerEnvironment.DEMO
    maximum_positions_monitored: int = Field(default=10, ge=1, le=100)
    maximum_close_requests_per_cycle: int = Field(default=1, ge=1, le=1)
    maximum_close_requests_per_day: int = Field(default=2, ge=1, le=2)
    maximum_position_age: timedelta = Field(default=timedelta(days=30), gt=timedelta(0))
    maximum_market_data_age: timedelta = Field(default=timedelta(seconds=60), gt=timedelta(0))
    maximum_account_state_age: timedelta = Field(default=timedelta(seconds=60), gt=timedelta(0))
    maximum_confirmation_wait_seconds: Decimal = Field(default=Decimal("10"), gt=0, le=60)
    confirmation_poll_interval_seconds: Decimal = Field(default=Decimal("0.5"), gt=0, le=10)
    allow_full_close: Literal[True] = True
    allow_partial_close: Literal[False] = False
    allow_stop_exit: Literal[True] = True
    allow_target_exit: Literal[True] = True
    allow_strategy_exit: Literal[True] = True
    allow_max_holding_exit: Literal[True] = True
    allow_risk_exit: Literal[True] = True
    allow_emergency_exit: Literal[True] = True
    allow_position_amendment: Literal[False] = False
    allow_stop_tightening: Literal[False] = False
    allow_stop_loosening: Literal[False] = False
    allow_target_amendment: Literal[False] = False
    allow_short_positions: Literal[False] = False
    allow_live_trading: Literal[False] = False
    stop_after_ambiguous_close: Literal[True] = True
    stop_after_reconciliation_mismatch: Literal[True] = True
    require_exact_position_match: Literal[True] = True
    adverse_first: Literal[True] = True
    demo_gateway: str = IG_DEMO_BASE_URL

    @model_validator(mode="before")
    @classmethod
    def reject_binary_floats(cls, value: object) -> object:
        if _contains_float(value):
            raise ValueError("binary floating point is prohibited in lifecycle configuration")
        return value

    @model_validator(mode="after")
    def validate_boundary(self) -> Self:
        if BrokerSettings(base_url=self.demo_gateway).base_url != IG_DEMO_BASE_URL:
            raise ValueError("position lifecycle requires the canonical IG Demo gateway")
        if self.confirmation_poll_interval_seconds > self.maximum_confirmation_wait_seconds:
            raise ValueError("confirmation poll interval exceeds confirmation wait")
        return self

    @property
    def configuration_fingerprint(self) -> str:
        return fingerprint(self)


def _contains_float(value: object) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_contains_float(item) for item in value.values())
    if isinstance(value, (tuple, list)):
        return any(_contains_float(item) for item in value)
    return False
