from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.test_risk_integration_security import _strategy_candidate

from context_helpers import market_data
from trading_desk.context.models import (
    ContextQuality,
    ContextReasonCode,
    ContextTimeframe,
    EconomicEvent,
    EventCategory,
    EventImportance,
)
from trading_desk.context.operational import (
    EconomicCalendarSnapshot,
    HolidayCalendarSnapshot,
    HolidayEntry,
    HolidayImpact,
    LocalJSONEconomicCalendar,
    LocalJSONHolidayCalendar,
    ObservableMarketQuote,
    OperationalCandidateContextProvider,
    OperationalContextConfiguration,
    completed_market_data,
)
from trading_desk.router.engine import StrategyRouter
from trading_desk.router.models import RouteStatus
from trading_desk.strategy.models import StrategyMarketData

NOW = datetime(2026, 7, 15, 14, 30, tzinfo=UTC)


class CalendarSource:
    def __init__(self, snapshot: EconomicCalendarSnapshot) -> None:
        self.value = snapshot

    def snapshot(self) -> EconomicCalendarSnapshot:
        return self.value


class HolidaySource:
    def __init__(self, snapshot: HolidayCalendarSnapshot) -> None:
        self.value = snapshot

    def snapshot(self) -> HolidayCalendarSnapshot:
        return self.value


def calendar(*, as_of: datetime = NOW, events: tuple[EconomicEvent, ...] = ()):
    return CalendarSource(
        EconomicCalendarSnapshot(
            source_identifier="calendar-v1",
            as_of=as_of,
            coverage_start=NOW - timedelta(days=7),
            coverage_end=NOW + timedelta(days=7),
            events=events,
        )
    )


def holidays(*, as_of: datetime = NOW, entries: tuple[HolidayEntry, ...] = ()):
    return HolidaySource(
        HolidayCalendarSnapshot(
            source_identifier="holidays-v1",
            as_of=as_of,
            coverage_start=date(2026, 1, 1),
            coverage_end=date(2026, 12, 31),
            entries=entries,
        )
    )


def quote(**updates: object) -> ObservableMarketQuote:
    values: dict[str, object] = {
        "epic": "CS.D.TEST.CFD.IP",
        "bid": Decimal("100"),
        "ask": Decimal("100.01"),
        "market_status": "TRADEABLE",
        "observed_at": NOW,
    }
    values.update(updates)
    return ObservableMarketQuote.model_validate(values)


def provider(**updates: object) -> OperationalCandidateContextProvider:
    configuration = OperationalContextConfiguration.model_validate(
        {
            "market_context": {
                "minimum_history": 30,
                "volatility_window": 5,
                "maximum_data_age_multiple": Decimal("4"),
                "compression_percentile": Decimal("0"),
            },
            **updates,
        }
    )
    return OperationalCandidateContextProvider(calendar(), holidays(), configuration)


def test_provider_requires_both_authoritative_dependencies() -> None:
    with pytest.raises(ValueError, match="event and holiday sources are required"):
        OperationalCandidateContextProvider(None, holidays())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="event and holiday sources are required"):
        OperationalCandidateContextProvider(calendar(), None)  # type: ignore[arg-type]


def test_authoritative_sources_and_quote_produce_fingerprinted_context() -> None:
    data = market_data(end=datetime(2026, 7, 15, 13, tzinfo=UTC), count=40)
    data = data.model_copy(update={"spread_bps": (2.0,) * 39 + (1.0,)})
    result = provider().build_context(
        data,
        _strategy_candidate(),
        evaluation_timestamp=NOW,
        timeframe=ContextTimeframe.HOUR,
        quote=quote(),
    )
    assert result is not None
    assert result.context_quality is ContextQuality.VALID
    assert len(result.source_evidence) == 4
    changed = provider().build_context(
        data,
        _strategy_candidate(),
        evaluation_timestamp=NOW,
        timeframe=ContextTimeframe.HOUR,
        quote=quote(ask=Decimal("100.02")),
    )
    assert changed is not None
    assert changed.context_fingerprint != result.context_fingerprint


@pytest.mark.parametrize(
    ("quote_updates", "reason"),
    [
        ({"observed_at": NOW - timedelta(minutes=2)}, ContextReasonCode.STALE_QUOTE),
        ({"bid": None}, ContextReasonCode.INCOMPLETE_QUOTE),
        ({"ask": None}, ContextReasonCode.INCOMPLETE_QUOTE),
        ({"bid": Decimal("101")}, ContextReasonCode.INCOMPLETE_QUOTE),
    ],
)
def test_invalid_quote_fails_context_closed(
    quote_updates: dict[str, object], reason: ContextReasonCode
) -> None:
    data = market_data(end=datetime(2026, 7, 15, 13, tzinfo=UTC), count=40)
    result = provider().build_context(
        data,
        _strategy_candidate(),
        evaluation_timestamp=NOW,
        timeframe=ContextTimeframe.HOUR,
        quote=quote(**quote_updates),
    )
    assert result is not None
    assert result.context_quality is ContextQuality.INVALID
    assert reason in result.reason_codes


def test_missing_quote_or_stale_authoritative_sources_fail_closed() -> None:
    data = market_data(end=datetime(2026, 7, 15, 13, tzinfo=UTC), count=40)
    assert (
        provider().build_context(
            data,
            _strategy_candidate(),
            evaluation_timestamp=NOW,
            timeframe=ContextTimeframe.HOUR,
        )
        is None
    )
    stale = OperationalCandidateContextProvider(
        calendar(as_of=NOW - timedelta(days=3)), holidays()
    ).build_context(
        data,
        _strategy_candidate(),
        evaluation_timestamp=NOW,
        timeframe=ContextTimeframe.HOUR,
        quote=quote(),
    )
    assert stale is not None
    assert ContextReasonCode.EVENT_CONTEXT_UNAVAILABLE in stale.reason_codes
    assert stale.context_quality is ContextQuality.INVALID

    stale_holiday = OperationalCandidateContextProvider(
        calendar(), holidays(as_of=NOW - timedelta(days=8))
    ).build_context(
        data,
        _strategy_candidate(),
        evaluation_timestamp=NOW,
        timeframe=ContextTimeframe.HOUR,
        quote=quote(),
    )
    assert stale_holiday is not None
    assert ContextReasonCode.HOLIDAY_CONTEXT_UNAVAILABLE in stale_holiday.reason_codes


def test_unfinished_and_stale_completed_history_fail_closed() -> None:
    unfinished = market_data(end=datetime(2026, 7, 15, 14, tzinfo=UTC), count=40)
    unfinished_result = provider().build_context(
        unfinished,
        _strategy_candidate(),
        evaluation_timestamp=NOW,
        timeframe=ContextTimeframe.HOUR,
        quote=quote(),
    )
    assert unfinished_result is not None
    assert ContextReasonCode.UNFINISHED_BAR in unfinished_result.reason_codes
    assert unfinished_result.context_quality is ContextQuality.INVALID

    stale = market_data(end=datetime(2026, 7, 10, 13, tzinfo=UTC), count=40)
    stale_result = provider(maximum_completed_bar_age_seconds=3600).build_context(
        stale,
        _strategy_candidate(),
        evaluation_timestamp=NOW,
        timeframe=ContextTimeframe.HOUR,
        quote=quote(),
    )
    assert stale_result is not None
    assert ContextReasonCode.STALE_DATA in stale_result.reason_codes
    assert stale_result.context_quality is ContextQuality.INVALID


def test_pre_event_window_is_preserved_as_capital_preservation_context() -> None:
    event = EconomicEvent(
        event_id="event-1",
        currency="USD",
        country="US",
        category=EventCategory.INFLATION,
        importance=EventImportance.HIGH,
        scheduled_timestamp=NOW + timedelta(minutes=10),
        source="operator-calendar",
    )
    data = market_data(end=datetime(2026, 7, 15, 13, tzinfo=UTC), count=40)
    result = OperationalCandidateContextProvider(
        calendar(events=(event,)), holidays()
    ).build_context(
        data,
        _strategy_candidate(),
        evaluation_timestamp=NOW,
        timeframe=ContextTimeframe.HOUR,
        quote=quote(),
    )
    assert result is not None
    assert ContextReasonCode.PRE_HIGH_IMPACT_EVENT in result.reason_codes
    assert result.context_quality is ContextQuality.INVALID


def test_event_relevance_uses_the_evaluated_currency_pair() -> None:
    gbp_event = EconomicEvent(
        event_id="gbp-event",
        currency="GBP",
        country="GB",
        category=EventCategory.EMPLOYMENT,
        importance=EventImportance.HIGH,
        scheduled_timestamp=NOW + timedelta(minutes=10),
        source="operator-calendar",
    )
    eur_event = gbp_event.model_copy(
        update={"event_id": "eur-event", "currency": "EUR", "category": EventCategory.GDP}
    )
    data = market_data(end=datetime(2026, 7, 15, 13, tzinfo=UTC), count=40).model_copy(
        update={"instrument_name": "GBP/USD"}
    )
    result = OperationalCandidateContextProvider(
        calendar(events=(eur_event, gbp_event)), holidays()
    ).build_context(
        data,
        _strategy_candidate(),
        evaluation_timestamp=NOW,
        timeframe=ContextTimeframe.HOUR,
        quote=quote(),
    )
    assert result is not None
    assert result.event_category is EventCategory.EMPLOYMENT
    assert ContextReasonCode.PRE_HIGH_IMPACT_EVENT in result.reason_codes


def test_authoritative_holiday_routes_to_capital_preservation() -> None:
    entry = HolidayEntry(
        date=NOW.date(),
        name="Test closure",
        currencies=("USD",),
        financial_centres=("New York",),
        impact=HolidayImpact.HOLIDAY,
    )
    data = market_data(end=datetime(2026, 7, 15, 13, tzinfo=UTC), count=220)
    result = OperationalCandidateContextProvider(
        calendar(), holidays(entries=(entry,))
    ).build_context(
        data,
        _strategy_candidate(),
        evaluation_timestamp=NOW,
        timeframe=ContextTimeframe.HOUR,
        quote=quote(),
    )
    assert result is not None
    routed = StrategyRouter().route_candidate(result, data, _strategy_candidate())
    assert routed.candidate is None
    assert routed.decision.route_status is RouteStatus.CAPITAL_PRESERVATION


def test_valid_operational_context_can_select_only_validated_strategy() -> None:
    count = 220
    closes = tuple(100 + index * 0.1 + math.sin(index) for index in range(count))
    timestamps = tuple(
        datetime(2026, 7, 15, 13, tzinfo=UTC) - timedelta(hours=count - 1 - index)
        for index in range(count)
    )
    data = StrategyMarketData(
        epic="CS.D.TEST.CFD.IP",
        instrument_name="Test market",
        timestamps=timestamps,
        open_midpoints=closes,
        high_midpoints=tuple(value + 0.5 for value in closes),
        low_midpoints=tuple(value - 0.5 for value in closes),
        close_midpoints=closes,
        bids=tuple(value - 0.005 for value in closes),
        asks=tuple(value + 0.005 for value in closes),
        spreads=(0.01,) * count,
        spread_bps=(2.0,) * (count - 1) + (1.0,),
        volume=(1000.0,) * count,
        market_status="TRADEABLE",
        data_retrieval_time=NOW,
        source_bar_count=count,
    )
    result = provider().build_context(
        data,
        _strategy_candidate(),
        evaluation_timestamp=NOW,
        timeframe=ContextTimeframe.HOUR,
        quote=quote(),
    )
    assert result is not None
    routed = StrategyRouter().route_candidate(result, data, _strategy_candidate())
    assert routed.candidate is not None, (
        result.context_quality,
        result.reason_codes,
        result.liquidity_state,
        result.volatility_state,
        result.trend_state,
        routed.decision.route_status,
    )
    assert routed.decision.selected_strategy_id == "trend-regime-v1"


def test_completed_bar_boundary_before_at_and_after_close() -> None:
    data = market_data(end=datetime(2026, 7, 15, 14, tzinfo=UTC), count=40)
    before = completed_market_data(
        data, datetime(2026, 7, 15, 14, 59, 59, tzinfo=UTC), ContextTimeframe.HOUR
    )
    exact = completed_market_data(
        data, datetime(2026, 7, 15, 15, 0, 0, tzinfo=UTC), ContextTimeframe.HOUR
    )
    after = completed_market_data(
        data, datetime(2026, 7, 15, 15, 0, 1, tzinfo=UTC), ContextTimeframe.HOUR
    )
    assert before.timestamps[-1] == datetime(2026, 7, 15, 13, tzinfo=UTC)
    assert exact.timestamps[-1] == datetime(2026, 7, 15, 14, tzinfo=UTC)
    assert after.timestamps == exact.timestamps


def test_appended_future_bars_do_not_change_completed_input() -> None:
    base = market_data(end=datetime(2026, 7, 15, 13, tzinfo=UTC), count=39)
    extended = market_data(end=datetime(2026, 7, 15, 15, tzinfo=UTC), count=41)
    base_completed = completed_market_data(base, NOW, ContextTimeframe.HOUR)
    extended_completed = completed_market_data(extended, NOW, ContextTimeframe.HOUR)
    assert extended_completed.timestamps == base_completed.timestamps
    assert extended_completed.close_midpoints == base_completed.close_midpoints


def test_duplicate_chronology_is_rejected_by_market_model() -> None:
    data = market_data(count=40)
    with pytest.raises(ValidationError, match="unique and increasing"):
        data.model_copy(
            update={"timestamps": (*data.timestamps[:-1], data.timestamps[-2])}
        ).model_validate(
            data.model_copy(
                update={"timestamps": (*data.timestamps[:-1], data.timestamps[-2])}
            ).model_dump()
        )


def test_local_json_sources_are_strict_and_do_not_require_environment(
    tmp_path: Path,
) -> None:
    event_path = tmp_path / "events.json"
    holiday_path = tmp_path / "holidays.json"
    event_path.write_text(
        json.dumps(
            {
                "source_identifier": "events-v1",
                "as_of": NOW.isoformat(),
                "coverage_start": (NOW - timedelta(days=7)).isoformat(),
                "coverage_end": (NOW + timedelta(days=7)).isoformat(),
                "events": [],
            }
        ),
        encoding="utf-8",
    )
    holiday_path.write_text(
        json.dumps(
            {
                "source_identifier": "holidays-v1",
                "as_of": NOW.isoformat(),
                "coverage_start": "2026-01-01",
                "coverage_end": "2026-12-31",
                "entries": [],
            }
        ),
        encoding="utf-8",
    )
    assert LocalJSONEconomicCalendar(event_path).snapshot().events == ()
    assert LocalJSONHolidayCalendar(holiday_path).snapshot().entries == ()
    with pytest.raises(ValueError, match="source is unavailable"):
        LocalJSONEconomicCalendar(tmp_path / "missing.json")


def test_operational_provider_has_no_mutation_or_ai_dependency() -> None:
    source = Path("src/trading_desk/context/operational.py").read_text(encoding="utf-8")
    assert "IGDemoExecutionAdapter" not in source
    assert "submit_market_position" not in source
    assert "/positions/otc" not in source
    assert "OPENAI" not in source
    assert ".env" not in source
