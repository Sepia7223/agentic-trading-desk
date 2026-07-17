"""Authoritative, file-backed operational context for bounded IG Demo analysis."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trading_desk.context.classifier import MarketContextEngine
from trading_desk.context.config import MarketContextConfiguration
from trading_desk.context.events import event_visible_at
from trading_desk.context.fingerprints import fingerprint
from trading_desk.context.models import (
    ContextReasonCode,
    ContextSourceEvidence,
    ContextTimeframe,
    EconomicEvent,
    MarketContextSnapshot,
)
from trading_desk.scheduler.clock import completed_bar_boundary
from trading_desk.strategy.models import (
    HMMRegimeResult,
    KalmanTrendResult,
    StrategyMarketData,
    TradeCandidate,
)


class OperationalContextModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class ObservableMarketQuote(OperationalContextModel):
    epic: str
    bid: Decimal | None
    ask: Decimal | None
    market_status: str
    observed_at: datetime
    source_identifier: str = "IG_DEMO_MARKET_DETAILS"

    @model_validator(mode="after")
    def validate_timestamp(self) -> Self:
        _utc(self.observed_at)
        return self


class EconomicCalendarSnapshot(OperationalContextModel):
    source_identifier: str
    as_of: datetime
    coverage_start: datetime
    coverage_end: datetime
    events: tuple[EconomicEvent, ...]

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        _utc(self.as_of)
        if _utc(self.coverage_end) < _utc(self.coverage_start):
            raise ValueError("economic calendar coverage is invalid")
        if len({item.event_id for item in self.events}) != len(self.events):
            raise ValueError("economic calendar event IDs must be unique")
        return self

    @property
    def source_fingerprint(self) -> str:
        return fingerprint(self)


class HolidayImpact(StrEnum):
    HOLIDAY = "HOLIDAY"
    THIN = "THIN"


class HolidayEntry(OperationalContextModel):
    calendar_date: date = Field(alias="date")
    name: str
    currencies: tuple[str, ...] = ()
    financial_centres: tuple[str, ...] = ()
    impact: HolidayImpact


class HolidayCalendarSnapshot(OperationalContextModel):
    source_identifier: str
    as_of: datetime
    coverage_start: date
    coverage_end: date
    entries: tuple[HolidayEntry, ...]

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        _utc(self.as_of)
        if self.coverage_end < self.coverage_start:
            raise ValueError("holiday calendar coverage is invalid")
        if any(
            not self.coverage_start <= item.calendar_date <= self.coverage_end
            for item in self.entries
        ):
            raise ValueError("holiday entry is outside declared coverage")
        return self

    @property
    def source_fingerprint(self) -> str:
        return fingerprint(self)


class EconomicCalendarSource(Protocol):
    def snapshot(self) -> EconomicCalendarSnapshot: ...


class HolidayCalendarSource(Protocol):
    def snapshot(self) -> HolidayCalendarSnapshot: ...


class LocalJSONEconomicCalendar:
    def __init__(self, path: Path) -> None:
        self._snapshot = _load_model(path, EconomicCalendarSnapshot, "economic calendar")

    def snapshot(self) -> EconomicCalendarSnapshot:
        return self._snapshot


class LocalJSONHolidayCalendar:
    def __init__(self, path: Path) -> None:
        self._snapshot = _load_model(path, HolidayCalendarSnapshot, "holiday calendar")

    def snapshot(self) -> HolidayCalendarSnapshot:
        return self._snapshot


class OperationalContextConfiguration(OperationalContextModel):
    market_context: MarketContextConfiguration = MarketContextConfiguration()
    maximum_quote_age_seconds: int = Field(default=60, ge=1, le=3600)
    maximum_calendar_age_seconds: int = Field(default=172800, ge=60, le=2592000)
    maximum_holiday_age_seconds: int = Field(default=604800, ge=60, le=7776000)
    maximum_completed_bar_age_seconds: int = Field(default=345600, ge=300, le=1209600)
    relevant_currencies: tuple[str, ...] = ("EUR", "USD")
    relevant_financial_centres: tuple[str, ...] = ("London", "New York")

    @property
    def configuration_fingerprint(self) -> str:
        return fingerprint(self)


class OperationalCandidateContextProvider:
    """Combine typed read-only observations with authoritative local calendars."""

    def __init__(
        self,
        economic_calendar: EconomicCalendarSource,
        holiday_calendar: HolidayCalendarSource,
        configuration: OperationalContextConfiguration | None = None,
    ) -> None:
        if economic_calendar is None or holiday_calendar is None:
            raise ValueError("authoritative event and holiday sources are required")
        self.economic_calendar = economic_calendar
        self.holiday_calendar = holiday_calendar
        self.configuration = configuration or OperationalContextConfiguration()
        self.engine = MarketContextEngine(self.configuration.market_context)

    def build_context(
        self,
        data: StrategyMarketData,
        candidate: TradeCandidate,
        *,
        evaluation_timestamp: datetime,
        timeframe: ContextTimeframe,
        quote: ObservableMarketQuote | None = None,
    ) -> MarketContextSnapshot | None:
        evaluation = _utc(evaluation_timestamp)
        calendar = self.economic_calendar.snapshot()
        holidays = self.holiday_calendar.snapshot()
        reasons: list[ContextReasonCode] = []
        if not data.timestamps:
            return None
        if quote is None or quote.epic != data.epic:
            return None
        quote_age = (evaluation - _utc(quote.observed_at)).total_seconds()
        if quote_age < 0 or quote_age > self.configuration.maximum_quote_age_seconds:
            reasons.append(ContextReasonCode.STALE_QUOTE)
        if (
            quote.bid is None
            or quote.ask is None
            or quote.bid <= 0
            or quote.ask <= 0
            or quote.bid > quote.ask
        ):
            reasons.append(ContextReasonCode.INCOMPLETE_QUOTE)
            context_data = data.model_copy(update={"market_status": quote.market_status})
        else:
            quote_spread = quote.ask - quote.bid
            quote_midpoint = (quote.ask + quote.bid) / Decimal("2")
            quote_spread_bps = Decimal("10000") * quote_spread / quote_midpoint
            context_data = data.model_copy(
                update={
                    "bids": (*data.bids[:-1], float(quote.bid)),
                    "asks": (*data.asks[:-1], float(quote.ask)),
                    "spreads": (*data.spreads[:-1], float(quote_spread)),
                    "spread_bps": (*data.spread_bps[:-1], float(quote_spread_bps)),
                    "market_status": quote.market_status,
                }
            )
        boundary = completed_bar_boundary(evaluation, timeframe)
        if not data.timestamps or data.timestamps[-1] >= boundary:
            reasons.append(ContextReasonCode.UNFINISHED_BAR)
        elif (
            boundary - (data.timestamps[-1] + _timeframe_delta(timeframe))
        ).total_seconds() > self.configuration.maximum_completed_bar_age_seconds:
            reasons.append(ContextReasonCode.STALE_DATA)
        calendar_age = (evaluation - _utc(calendar.as_of)).total_seconds()
        if (
            calendar_age < 0
            or calendar_age > self.configuration.maximum_calendar_age_seconds
            or not _utc(calendar.coverage_start) <= evaluation <= _utc(calendar.coverage_end)
        ):
            reasons.append(ContextReasonCode.EVENT_CONTEXT_UNAVAILABLE)
        holiday_age = (evaluation - _utc(holidays.as_of)).total_seconds()
        if (
            holiday_age < 0
            or holiday_age > self.configuration.maximum_holiday_age_seconds
            or not holidays.coverage_start <= evaluation.date() <= holidays.coverage_end
        ):
            reasons.append(ContextReasonCode.HOLIDAY_CONTEXT_UNAVAILABLE)
        relevant_events = tuple(
            event_visible_at(item, evaluation)
            for item in calendar.events
            if item.currency.upper() in self.configuration.relevant_currencies
        )
        holiday = any(
            item.calendar_date == evaluation.date()
            and (
                set(map(str.upper, item.currencies)) & set(self.configuration.relevant_currencies)
                or set(map(str.lower, item.financial_centres))
                & set(map(str.lower, self.configuration.relevant_financial_centres))
            )
            for item in holidays.entries
        )
        evidence = (
            _evidence("IG_DEMO_HISTORICAL_PRICES", data.data_retrieval_time, data),
            _evidence(quote.source_identifier, quote.observed_at, quote),
            _evidence(calendar.source_identifier, calendar.as_of, calendar),
            _evidence(holidays.source_identifier, holidays.as_of, holidays),
        )
        kalman, regime = _candidate_models(candidate, len(data.timestamps))
        result = self.engine.classify(
            context_data,
            kalman,
            regime,
            evaluation_timestamp=evaluation,
            timeframe=timeframe,
            events=relevant_events,
            holiday=holiday,
            source_evidence=evidence,
            inherited_reasons=tuple(dict.fromkeys(reasons)),
        )
        fields = result.model_dump(mode="python", exclude={"context_id", "context_fingerprint"})
        fields["configuration_fingerprint"] = self.configuration.configuration_fingerprint
        identity = fingerprint(fields)
        return MarketContextSnapshot.model_validate(
            {**fields, "context_id": identity, "context_fingerprint": identity}
        )


def completed_market_data(
    data: StrategyMarketData,
    evaluation_timestamp: datetime,
    timeframe: ContextTimeframe,
) -> StrategyMarketData:
    """Return bars whose start precedes the current UTC bar boundary."""
    boundary = completed_bar_boundary(_utc(evaluation_timestamp), timeframe)
    indexes = [index for index, timestamp in enumerate(data.timestamps) if timestamp < boundary]
    if not indexes:
        raise ValueError("no completed historical bars are available")
    return data.sliced_through(indexes[-1]).model_copy(
        update={"data_retrieval_time": data.data_retrieval_time}
    )


def _candidate_models(
    candidate: TradeCandidate, observations: int
) -> tuple[KalmanTrendResult, HMMRegimeResult]:
    kalman = KalmanTrendResult(
        ready=candidate.kalman_level is not None and candidate.kalman_slope is not None,
        current_filtered_level=candidate.kalman_level,
        current_slope=candidate.kalman_slope,
        current_slope_uncertainty=candidate.kalman_slope_uncertainty,
        current_normalized_slope=candidate.kalman_normalized_slope,
        current_normalized_slope_uncertainty=candidate.kalman_normalized_slope_uncertainty,
        normalized_price_deviation=candidate.normalized_price_deviation,
        observations_used=observations,
    )
    ready = candidate.current_regime.value != "UNKNOWN"
    regime = HMMRegimeResult(
        ready=ready,
        current_regime=candidate.current_regime,
        probabilities=candidate.regime_probabilities,
        selected_regime_probability=max(
            (item.probability for item in candidate.regime_probabilities), default=0
        ),
        uncertainty=candidate.regime_uncertainty,
        converged=ready,
        observations_used=observations,
    )
    return kalman, regime


def _evidence(identifier: str, timestamp: datetime, value: object) -> ContextSourceEvidence:
    return ContextSourceEvidence(
        source_identifier=identifier,
        source_timestamp=_utc(timestamp),
        source_fingerprint=fingerprint(value),
    )


def _load_model[OperationalModelT: OperationalContextModel](
    path: Path, model_type: type[OperationalModelT], label: str
) -> OperationalModelT:
    if not path.is_file():
        raise ValueError(f"authoritative {label} source is unavailable")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return model_type.model_validate(payload)
    except (OSError, ValueError, TypeError):
        raise ValueError(f"authoritative {label} source is invalid") from None


def _timeframe_delta(timeframe: ContextTimeframe) -> timedelta:
    return timedelta(seconds=timeframe.seconds)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("operational context timestamps must be timezone-aware UTC")
    return value.astimezone(UTC)
