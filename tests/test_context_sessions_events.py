from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading_desk.context.config import MarketContextConfiguration
from trading_desk.context.events import (
    FixtureEconomicCalendarProvider,
    classify_event_context,
    event_visible_at,
)
from trading_desk.context.models import (
    EconomicEvent,
    EventCategory,
    EventImportance,
    NewsItem,
    NewsState,
    ScheduledEventState,
    SessionState,
)
from trading_desk.context.news import classify_news
from trading_desk.context.sessions import classify_session

CONFIG = MarketContextConfiguration()


@pytest.mark.parametrize(
    ("timestamp", "expected"),
    [
        (datetime(2026, 1, 14, 1, tzinfo=UTC), SessionState.ASIA),
        (datetime(2026, 1, 14, 9, tzinfo=UTC), SessionState.LONDON),
        (datetime(2026, 1, 14, 14, tzinfo=UTC), SessionState.LONDON_NEW_YORK_OVERLAP),
        (datetime(2026, 1, 14, 18, tzinfo=UTC), SessionState.NEW_YORK),
        (datetime(2026, 1, 14, 22, tzinfo=UTC), SessionState.ROLLOVER),
        (datetime(2026, 1, 17, 14, tzinfo=UTC), SessionState.CLOSED),
        (datetime(2026, 1, 16, 22, tzinfo=UTC), SessionState.CLOSED),
    ],
)
def test_session_states(timestamp: datetime, expected: SessionState) -> None:
    assert classify_session(timestamp, CONFIG).session is expected


def test_sessions_follow_london_and_new_york_dst() -> None:
    winter = classify_session(datetime(2026, 1, 14, 8, tzinfo=UTC), CONFIG)
    summer = classify_session(datetime(2026, 7, 15, 7, tzinfo=UTC), CONFIG)
    mismatch_week = classify_session(datetime(2026, 3, 18, 12, 30, tzinfo=UTC), CONFIG)
    assert winter.session is SessionState.LONDON
    assert summer.session is SessionState.LONDON
    assert mismatch_week.session is SessionState.LONDON_NEW_YORK_OVERLAP


def _event() -> EconomicEvent:
    scheduled = datetime(2026, 7, 15, 14, tzinfo=UTC)
    return EconomicEvent(
        event_id="cpi-us-1",
        currency="USD",
        country="United States",
        category=EventCategory.INFLATION,
        importance=EventImportance.HIGH,
        scheduled_timestamp=scheduled,
        forecast=Decimal("3.0"),
        previous=Decimal("2.9"),
        revised_previous=Decimal("2.8"),
        revised_at=scheduled + timedelta(minutes=10),
        actual=Decimal("3.1"),
        released_at=scheduled,
        source="fixture",
    )


@pytest.mark.parametrize(
    ("offset", "state"),
    [
        (-31, ScheduledEventState.NO_EVENT),
        (-30, ScheduledEventState.PRE_EVENT),
        (0, ScheduledEventState.INITIAL_REACTION),
        (4, ScheduledEventState.INITIAL_REACTION),
        (6, ScheduledEventState.POST_EVENT_STABILIZING),
        (16, ScheduledEventState.POST_EVENT_ELIGIBLE),
        (241, ScheduledEventState.STALE_EVENT),
    ],
)
def test_event_windows(offset: int, state: ScheduledEventState) -> None:
    event = _event()
    evaluation = event.scheduled_timestamp + timedelta(minutes=offset)
    assert classify_event_context((event,), evaluation, 300, CONFIG).state is state


def test_event_actual_and_revision_are_cutoff_safe() -> None:
    event = _event()
    before = event_visible_at(event, event.scheduled_timestamp - timedelta(seconds=1))
    released = event_visible_at(event, event.scheduled_timestamp)
    revised = FixtureEconomicCalendarProvider((event,)).events_through(
        event.scheduled_timestamp + timedelta(minutes=10)
    )[0]
    assert before.actual is None and before.revised_previous is None
    assert released.actual == Decimal("3.1") and released.revised_previous is None
    assert revised.revised_previous == Decimal("2.8")


def test_malformed_event_fails_closed() -> None:
    with pytest.raises(ValidationError):
        EconomicEvent(
            event_id="",
            currency="U",
            country="US",
            category=EventCategory.OTHER,
            importance=EventImportance.UNKNOWN,
            scheduled_timestamp=datetime.now(UTC),
            source="fixture",
        )


def test_event_relevance_is_category_specific() -> None:
    event = _event().model_copy(update={"category": EventCategory.CENTRAL_BANK_DECISION})
    evaluation = event.scheduled_timestamp + timedelta(minutes=300)
    assert (
        classify_event_context((event,), evaluation, 300, CONFIG).state
        is ScheduledEventState.POST_EVENT_ELIGIBLE
    )


def test_news_context_preserves_age_without_direction_authority() -> None:
    evaluation = datetime(2026, 7, 15, 14, tzinfo=UTC)
    item = NewsItem(
        news_item_id="fixture-news",
        published_at=evaluation - timedelta(minutes=10),
        instrument_or_currency="USD",
        category="unscheduled",
        source="fixture",
        importance=EventImportance.HIGH,
        scheduled=False,
        structured_summary="Unexpected public announcement.",
    )
    context = classify_news((item,), evaluation, CONFIG)
    assert context.state is NewsState.UNSCHEDULED_CAUTION
    assert context.age_seconds == 600
