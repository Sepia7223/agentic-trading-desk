"""Immutable scheduler action and state records."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from trading_desk.context.models import ContextTimeframe


class SchedulerModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ScheduledActionType(StrEnum):
    MARKET_HEALTH = "MARKET_HEALTH"
    STRATEGY_BAR = "STRATEGY_BAR"
    ECONOMIC_CALENDAR = "ECONOMIC_CALENDAR"
    POSITION_RECONCILIATION = "POSITION_RECONCILIATION"
    EXECUTION_STATE_VERIFICATION = "EXECUTION_STATE_VERIFICATION"
    POSITION_MONITOR = "POSITION_MONITOR"
    EXIT_EVALUATION = "EXIT_EVALUATION"
    ACCOUNT_RISK_REFRESH = "ACCOUNT_RISK_REFRESH"


class ScheduledAction(SchedulerModel):
    action_id: str = Field(min_length=64, max_length=64)
    action_type: ScheduledActionType
    due_timestamp: datetime
    timeframe: ContextTimeframe | None = None
    completed_bar_timestamp: datetime | None = None

    @field_validator("due_timestamp", "completed_bar_timestamp")
    @classmethod
    def utc_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value)
        ):
            raise ValueError("scheduler timestamps must be timezone-aware UTC")
        return value


class SchedulerState(SchedulerModel):
    schema_version: int = 1
    completed_action_ids: tuple[str, ...] = ()
    last_completed_bars: tuple[tuple[ContextTimeframe, datetime], ...] = ()
    updated_at: datetime | None = None

    @field_validator("updated_at")
    @classmethod
    def utc_updated(cls, value: datetime | None) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value)
        ):
            raise ValueError("scheduler state timestamp must be timezone-aware UTC")
        return value


class SchedulerCycle(SchedulerModel):
    cycle_id: str = Field(min_length=64, max_length=64)
    evaluated_at: datetime
    actions: tuple[ScheduledAction, ...]
    execution_halted: bool
    configuration_fingerprint: str
