"""Persistent per-strategy entry circuit breakers; lifecycle exits remain independent."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.context.fingerprints import fingerprint


class BreakerState(StrEnum):
    CLEAR = "CLEAR"
    TRIGGERED = "TRIGGERED"


class BreakerTrigger(StrEnum):
    CONSECUTIVE_LOSSES = "CONSECUTIVE_LOSSES"
    ROLLING_DRAWDOWN = "ROLLING_DRAWDOWN"
    DAILY_LOSS = "DAILY_LOSS"
    COST_DEVIATION = "COST_DEVIATION"
    SLIPPAGE_DEVIATION = "SLIPPAGE_DEVIATION"
    EXECUTION_INCIDENTS = "EXECUTION_INCIDENTS"
    DATA_QUALITY = "DATA_QUALITY"


class CircuitBreakerConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    maximum_consecutive_losses: int = Field(default=5, ge=1)
    maximum_rolling_drawdown: Decimal = Field(default=Decimal("0.10"), gt=0)
    maximum_daily_loss: Decimal = Field(default=Decimal("0.03"), gt=0)
    maximum_cost_deviation: Decimal = Field(default=Decimal("0.50"), ge=0)
    maximum_slippage_deviation: Decimal = Field(default=Decimal("0.50"), ge=0)
    maximum_execution_incidents: int = Field(default=2, ge=0)
    minimum_data_quality: Decimal = Field(default=Decimal("0.90"), ge=0, le=1)


class StrategyCircuitBreaker(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    strategy_id: str
    state: BreakerState = BreakerState.CLEAR
    trigger: BreakerTrigger | None = None
    triggered_at: datetime | None = None
    trading_day: date
    consecutive_losses: int = Field(default=0, ge=0)
    rolling_drawdown: Decimal = Field(default=Decimal("0"), ge=0)
    daily_loss: Decimal = Field(default=Decimal("0"), ge=0)
    cost_deviation: Decimal = Field(default=Decimal("0"), ge=0)
    slippage_deviation: Decimal = Field(default=Decimal("0"), ge=0)
    execution_incidents: int = Field(default=0, ge=0)
    data_quality: Decimal = Field(default=Decimal("1"), ge=0, le=1)
    state_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("triggered_at")
    @classmethod
    def utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value)
        ):
            raise ValueError("circuit-breaker timestamp must be UTC")
        return value.astimezone(UTC) if value else None

    @model_validator(mode="after")
    def identity(self) -> Self:
        if (self.state is BreakerState.TRIGGERED) != (
            self.trigger is not None and self.triggered_at is not None
        ):
            raise ValueError("circuit-breaker trigger state is inconsistent")
        if self.state_fingerprint != fingerprint(
            self.model_dump(mode="python", exclude={"state_fingerprint"})
        ):
            raise ValueError("circuit-breaker fingerprint mismatch")
        return self

    @property
    def entries_allowed(self) -> bool:
        return self.state is BreakerState.CLEAR


def evaluate_circuit_breaker(
    state: StrategyCircuitBreaker,
    configuration: CircuitBreakerConfiguration,
    observed_at: datetime,
) -> StrategyCircuitBreaker:
    if state.state is BreakerState.TRIGGERED:
        return state
    checks = (
        (
            state.consecutive_losses >= configuration.maximum_consecutive_losses,
            BreakerTrigger.CONSECUTIVE_LOSSES,
        ),
        (
            state.rolling_drawdown >= configuration.maximum_rolling_drawdown,
            BreakerTrigger.ROLLING_DRAWDOWN,
        ),
        (state.daily_loss >= configuration.maximum_daily_loss, BreakerTrigger.DAILY_LOSS),
        (
            state.cost_deviation > configuration.maximum_cost_deviation,
            BreakerTrigger.COST_DEVIATION,
        ),
        (
            state.slippage_deviation > configuration.maximum_slippage_deviation,
            BreakerTrigger.SLIPPAGE_DEVIATION,
        ),
        (
            state.execution_incidents > configuration.maximum_execution_incidents,
            BreakerTrigger.EXECUTION_INCIDENTS,
        ),
        (state.data_quality < configuration.minimum_data_quality, BreakerTrigger.DATA_QUALITY),
    )
    trigger = next((reason for failed, reason in checks if failed), None)
    fields = state.model_dump(
        mode="python", exclude={"state_fingerprint", "state", "trigger", "triggered_at"}
    )
    fields.update(
        {
            "state": BreakerState.TRIGGERED if trigger else BreakerState.CLEAR,
            "trigger": trigger,
            "triggered_at": observed_at if trigger else None,
        }
    )
    return StrategyCircuitBreaker.model_validate(
        {**fields, "state_fingerprint": fingerprint(fields)}
    )


def clear_circuit_breaker(
    state: StrategyCircuitBreaker, *, authority: str, observed_at: datetime
) -> StrategyCircuitBreaker:
    if not authority.strip():
        raise ValueError("manual circuit-breaker recovery requires named authority")
    fields = {
        "strategy_id": state.strategy_id,
        "state": BreakerState.CLEAR,
        "trigger": None,
        "triggered_at": None,
        "trading_day": observed_at.date(),
        "consecutive_losses": 0,
        "rolling_drawdown": Decimal("0"),
        "daily_loss": Decimal("0"),
        "cost_deviation": Decimal("0"),
        "slippage_deviation": Decimal("0"),
        "execution_incidents": 0,
        "data_quality": Decimal("1"),
    }
    return StrategyCircuitBreaker.model_validate(
        {**fields, "state_fingerprint": fingerprint(fields)}
    )


def initial_circuit_breaker(strategy_id: str, trading_day: date) -> StrategyCircuitBreaker:
    fields = {"strategy_id": strategy_id, "trading_day": trading_day}
    return StrategyCircuitBreaker.model_validate(
        {
            **fields,
            "state_fingerprint": fingerprint(
                {
                    **fields,
                    "state": BreakerState.CLEAR,
                    "trigger": None,
                    "triggered_at": None,
                    "consecutive_losses": 0,
                    "rolling_drawdown": Decimal("0"),
                    "daily_loss": Decimal("0"),
                    "cost_deviation": Decimal("0"),
                    "slippage_deviation": Decimal("0"),
                    "execution_incidents": 0,
                    "data_quality": Decimal("1"),
                }
            ),
        }
    )


class CircuitBreakerStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def save(self, states: tuple[StrategyCircuitBreaker, ...]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps([item.model_dump(mode="json") for item in states], sort_keys=True, indent=2)
            + "\n",
            encoding="utf-8",
        )

    def load(self) -> tuple[StrategyCircuitBreaker, ...]:
        if not self.path.exists():
            return ()
        values = json.loads(self.path.read_text(encoding="utf-8"))
        return tuple(StrategyCircuitBreaker.model_validate(item) for item in values)
