"""Immutable classification and event-window policy."""

from __future__ import annotations

from datetime import time
from decimal import Decimal
from typing import Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trading_desk.context.fingerprints import fingerprint
from trading_desk.context.models import EventCategory


class SessionDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    timezone: str
    local_open: time
    local_close: time

    @model_validator(mode="after")
    def valid_timezone_and_window(self) -> Self:
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("unknown session timezone") from exc
        if self.local_open >= self.local_close:
            raise ValueError("session open must precede close")
        return self


class MarketContextConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    asia_session: SessionDefinition = SessionDefinition(
        timezone="Asia/Tokyo", local_open=time(8), local_close=time(17)
    )
    london_session: SessionDefinition = SessionDefinition(
        timezone="Europe/London", local_open=time(8), local_close=time(17)
    )
    new_york_session: SessionDefinition = SessionDefinition(
        timezone="America/New_York", local_open=time(8), local_close=time(17)
    )
    rollover_start_utc: time = time(21, 55)
    rollover_end_utc: time = time(22, 10)
    friday_cutoff_new_york: time = time(16)
    sunday_reopen_new_york: time = time(17)
    maximum_spread_bps: Decimal = Field(default=Decimal("10"), gt=0)
    abnormal_spread_bps: Decimal = Field(default=Decimal("20"), gt=0)
    low_liquidity_spread_percentile: Decimal = Field(default=Decimal("90"), ge=0, le=100)
    minimum_history: int = Field(default=30, ge=20, le=5000)
    volatility_window: int = Field(default=20, ge=5, le=252)
    compression_percentile: Decimal = Field(default=Decimal("15"), ge=0, le=100)
    high_volatility_percentile: Decimal = Field(default=Decimal("75"), ge=0, le=100)
    extreme_volatility_percentile: Decimal = Field(default=Decimal("97"), ge=0, le=100)
    trend_slope_threshold: Decimal = Field(default=Decimal("0.0001"), gt=0)
    strong_trend_slope_threshold: Decimal = Field(default=Decimal("0.0005"), gt=0)
    range_slope_threshold: Decimal = Field(default=Decimal("0.00005"), gt=0)
    pre_event_block_minutes: int = Field(default=30, ge=1, le=240)
    initial_reaction_minutes: int = Field(default=5, ge=1, le=60)
    post_event_bars_required: int = Field(default=3, ge=1, le=100)
    event_relevance_minutes_by_category: tuple[tuple[EventCategory, int], ...] = (
        (EventCategory.CENTRAL_BANK_DECISION, 360),
        (EventCategory.CENTRAL_BANK_SPEECH, 180),
        (EventCategory.INFLATION, 240),
        (EventCategory.EMPLOYMENT, 240),
        (EventCategory.GDP, 180),
        (EventCategory.PMI, 180),
        (EventCategory.RETAIL_SALES, 180),
        (EventCategory.TRADE_BALANCE, 180),
        (EventCategory.OTHER, 120),
    )
    unscheduled_news_caution_minutes: int = Field(default=60, ge=1, le=1440)
    maximum_data_age_multiple: Decimal = Field(default=Decimal("2"), gt=1)

    @model_validator(mode="after")
    def valid_thresholds(self) -> Self:
        if self.abnormal_spread_bps <= self.maximum_spread_bps:
            raise ValueError("abnormal spread threshold must exceed maximum spread")
        if not (
            self.compression_percentile
            < self.high_volatility_percentile
            < self.extreme_volatility_percentile
        ):
            raise ValueError("volatility percentile thresholds are not ordered")
        if self.strong_trend_slope_threshold <= self.trend_slope_threshold:
            raise ValueError("strong trend threshold must exceed trend threshold")
        categories = tuple(item[0] for item in self.event_relevance_minutes_by_category)
        if set(categories) != set(EventCategory) or len(categories) != len(set(categories)):
            raise ValueError("event relevance must define every category exactly once")
        if any(
            not 30 <= minutes <= 1440 for _, minutes in self.event_relevance_minutes_by_category
        ):
            raise ValueError("event relevance minutes must be between 30 and 1440")
        return self

    def event_relevance_minutes(self, category: EventCategory) -> int:
        return dict(self.event_relevance_minutes_by_category)[category]

    @property
    def configuration_fingerprint(self) -> str:
        return fingerprint(self)
