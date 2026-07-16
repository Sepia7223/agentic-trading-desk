"""Provider-neutral economic events and deterministic release windows."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from trading_desk.context.config import MarketContextConfiguration
from trading_desk.context.models import (
    EconomicEvent,
    EventContext,
    EventImportance,
    ScheduledEventState,
)


class EconomicCalendarProvider(Protocol):
    def events_through(self, cutoff: datetime) -> tuple[EconomicEvent, ...]: ...


class FixtureEconomicCalendarProvider:
    def __init__(self, events: tuple[EconomicEvent, ...]) -> None:
        self._events = tuple(
            sorted(events, key=lambda item: (item.scheduled_timestamp, item.event_id))
        )

    def events_through(self, cutoff: datetime) -> tuple[EconomicEvent, ...]:
        return tuple(event_visible_at(item, cutoff) for item in self._events)


def event_visible_at(event: EconomicEvent, cutoff: datetime) -> EconomicEvent:
    if cutoff.tzinfo is None:
        raise ValueError("event cutoff must be timezone-aware")
    return event.model_copy(
        update={
            "actual": event.actual if event.released_at and event.released_at <= cutoff else None,
            "released_at": event.released_at
            if event.released_at and event.released_at <= cutoff
            else None,
            "revised_previous": (
                event.revised_previous if event.revised_at and event.revised_at <= cutoff else None
            ),
            "revised_at": event.revised_at
            if event.revised_at and event.revised_at <= cutoff
            else None,
        }
    )


def classify_event_context(
    events: tuple[EconomicEvent, ...],
    evaluation_timestamp: datetime,
    timeframe_seconds: int,
    config: MarketContextConfiguration,
) -> EventContext:
    if evaluation_timestamp.tzinfo is None:
        raise ValueError("event evaluation timestamp must be timezone-aware")
    high = tuple(item for item in events if item.importance is EventImportance.HIGH)
    future = tuple(item for item in high if item.scheduled_timestamp > evaluation_timestamp)
    past = tuple(item for item in high if item.scheduled_timestamp <= evaluation_timestamp)
    next_event = min(future, key=lambda item: item.scheduled_timestamp, default=None)
    previous = max(past, key=lambda item: item.scheduled_timestamp, default=None)
    minutes_to = (
        int((next_event.scheduled_timestamp - evaluation_timestamp).total_seconds() // 60)
        if next_event
        else None
    )
    minutes_since = (
        int((evaluation_timestamp - previous.scheduled_timestamp).total_seconds() // 60)
        if previous
        else None
    )
    if next_event and minutes_to is not None and minutes_to <= config.pre_event_block_minutes:
        return EventContext(
            state=ScheduledEventState.PRE_EVENT,
            event_id=next_event.event_id,
            category=next_event.category,
            minutes_to_next_high_impact_event=minutes_to,
            minutes_since_previous_high_impact_event=minutes_since,
        )
    if previous and minutes_since is not None:
        elapsed_seconds = int((evaluation_timestamp - previous.scheduled_timestamp).total_seconds())
        completed_bars = max(0, elapsed_seconds // timeframe_seconds)
        if minutes_since < config.initial_reaction_minutes:
            state = ScheduledEventState.INITIAL_REACTION
        elif completed_bars < config.post_event_bars_required:
            state = ScheduledEventState.POST_EVENT_STABILIZING
        elif minutes_since <= config.event_relevance_minutes(previous.category):
            state = ScheduledEventState.POST_EVENT_ELIGIBLE
        else:
            state = ScheduledEventState.STALE_EVENT
        return EventContext(
            state=state,
            event_id=previous.event_id,
            category=previous.category,
            minutes_to_next_high_impact_event=minutes_to,
            minutes_since_previous_high_impact_event=minutes_since,
            completed_post_event_bars=completed_bars,
        )
    return EventContext(
        state=ScheduledEventState.NO_EVENT,
        minutes_to_next_high_impact_event=minutes_to,
    )
