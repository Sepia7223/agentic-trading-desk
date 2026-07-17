"""UTC and DST-aware deterministic trading-session classification."""

from __future__ import annotations

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from trading_desk.context.config import MarketContextConfiguration, SessionDefinition
from trading_desk.context.models import SessionClassification, SessionState


def classify_session(
    timestamp: datetime,
    config: MarketContextConfiguration,
    *,
    holiday: bool = False,
) -> SessionClassification:
    now = _utc(timestamp)
    new_york = now.astimezone(ZoneInfo(config.new_york_session.timezone))
    if new_york.weekday() == 5 or (
        new_york.weekday() == 6 and new_york.time() < config.sunday_reopen_new_york
    ):
        return _closed()
    if new_york.weekday() == 4 and new_york.time() >= config.friday_cutoff_new_york:
        return _closed()
    if _time_in_wrapped_window(now.time(), config.rollover_start_utc, config.rollover_end_utc):
        return SessionClassification(
            session=SessionState.ROLLOVER,
            session_overlap=False,
            minutes_from_session_open=None,
            minutes_to_session_close=None,
        )
    if holiday:
        return SessionClassification(
            session=SessionState.HOLIDAY_OR_THIN,
            session_overlap=False,
            minutes_from_session_open=None,
            minutes_to_session_close=None,
        )
    active = {
        SessionState.ASIA: _bounds(now, config.asia_session),
        SessionState.LONDON: _bounds(now, config.london_session),
        SessionState.NEW_YORK: _bounds(now, config.new_york_session),
    }
    london, new_york_bounds = active[SessionState.LONDON], active[SessionState.NEW_YORK]
    if london and new_york_bounds:
        start = max(london[0], new_york_bounds[0])
        end = min(london[1], new_york_bounds[1])
        return _classification(SessionState.LONDON_NEW_YORK_OVERLAP, now, start, end, True)
    for state in (SessionState.LONDON, SessionState.NEW_YORK, SessionState.ASIA):
        if bounds := active[state]:
            return _classification(state, now, bounds[0], bounds[1], False)
    return _closed()


def _bounds(now: datetime, definition: SessionDefinition) -> tuple[datetime, datetime] | None:
    zone = ZoneInfo(definition.timezone)
    local = now.astimezone(zone)
    if local.weekday() >= 5 or not definition.local_open <= local.time() < definition.local_close:
        return None
    opened = datetime.combine(local.date(), definition.local_open, tzinfo=zone).astimezone(UTC)
    closed = datetime.combine(local.date(), definition.local_close, tzinfo=zone).astimezone(UTC)
    return opened, closed


def _classification(
    state: SessionState,
    now: datetime,
    opened: datetime,
    closed: datetime,
    overlap: bool,
) -> SessionClassification:
    return SessionClassification(
        session=state,
        session_overlap=overlap,
        minutes_from_session_open=int((now - opened).total_seconds() // 60),
        minutes_to_session_close=max(0, int((closed - now).total_seconds() // 60)),
    )


def _closed() -> SessionClassification:
    return SessionClassification(
        session=SessionState.CLOSED,
        session_overlap=False,
        minutes_from_session_open=None,
        minutes_to_session_close=None,
    )


def _time_in_wrapped_window(value: time, start: time, end: time) -> bool:
    return start <= value < end if start < end else value >= start or value < end


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("session timestamp must be timezone-aware")
    return value.astimezone(UTC)
