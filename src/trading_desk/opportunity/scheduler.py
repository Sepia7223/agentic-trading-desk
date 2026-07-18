"""Deterministic completed-bar schedule planning for the governed universe."""

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, field_validator

from trading_desk.context.models import ContextTimeframe
from trading_desk.opportunity.config import MarketUniverse
from trading_desk.opportunity.fingerprints import fingerprint


class ScheduledOpportunityEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    evaluation_id: str = Field(min_length=64, max_length=64)
    instrument_id: str
    epic: str
    timeframe: ContextTimeframe
    completed_bar_timestamp: datetime

    @field_validator("completed_bar_timestamp")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("scheduled bar timestamp must be UTC")
        return value.astimezone(UTC)


def plan_completed_bars(
    universe: MarketUniverse,
    observed_at: datetime,
    *,
    last_completed: tuple[tuple[str, ContextTimeframe, datetime], ...] = (),
    maximum_catch_up_bars: int = 3,
    closed_dates: tuple[str, ...] = (),
) -> tuple[ScheduledOpportunityEvaluation, ...]:
    if observed_at.tzinfo is None or observed_at.utcoffset() != UTC.utcoffset(observed_at):
        raise ValueError("scheduler observation must be UTC")
    if maximum_catch_up_bars < 1 or maximum_catch_up_bars > 12:
        raise ValueError("catch-up bound is invalid")
    previous = {
        (instrument, timeframe): timestamp for instrument, timeframe, timestamp in last_completed
    }
    results: list[ScheduledOpportunityEvaluation] = []
    for market in universe.markets:
        if not market.enabled:
            continue
        for timeframe in market.supported_timeframes:
            seconds = timeframe.seconds
            completed_epoch = int(observed_at.timestamp()) // seconds * seconds
            latest = datetime.fromtimestamp(completed_epoch, UTC)
            if latest >= observed_at:
                latest -= timedelta(seconds=seconds)
            floor = previous.get(
                (market.instrument_id, timeframe), latest - timedelta(seconds=seconds)
            )
            pending: list[datetime] = []
            cursor = floor + timedelta(seconds=seconds)
            while cursor <= latest:
                if cursor.date().isoformat() not in closed_dates:
                    pending.append(cursor)
                cursor += timedelta(seconds=seconds)
            for completed_at in pending[-maximum_catch_up_bars:]:
                fields = {
                    "instrument_id": market.instrument_id,
                    "epic": market.epic,
                    "timeframe": timeframe,
                    "completed_bar_timestamp": completed_at,
                }
                results.append(
                    ScheduledOpportunityEvaluation(
                        evaluation_id=fingerprint(fields),
                        instrument_id=market.instrument_id,
                        epic=market.epic,
                        timeframe=timeframe,
                        completed_bar_timestamp=completed_at,
                    )
                )
    return tuple(
        sorted(
            results,
            key=lambda item: (
                item.completed_bar_timestamp,
                item.instrument_id,
                item.timeframe.value,
            ),
        )
    )
