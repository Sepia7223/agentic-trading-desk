"""Immutable scheduler cadence configuration."""

from pydantic import BaseModel, ConfigDict, Field

from trading_desk.context.fingerprints import fingerprint
from trading_desk.context.models import ContextTimeframe


class SchedulerConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    health_interval_seconds: int = Field(default=60, ge=10, le=3600)
    calendar_interval_seconds: int = Field(default=900, ge=60, le=86400)
    reconciliation_interval_seconds: int = Field(default=180, ge=60, le=3600)
    strategy_timeframes: tuple[ContextTimeframe, ...] = (
        ContextTimeframe.MINUTE_5,
        ContextTimeframe.MINUTE_15,
        ContextTimeframe.HOUR,
    )
    maximum_actions_per_cycle: int = Field(default=16, ge=1, le=100)

    @property
    def configuration_fingerprint(self) -> str:
        return fingerprint(self)
