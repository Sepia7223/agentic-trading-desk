"""Immutable models for market, session, event, liquidity, and news context."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.context.fingerprints import fingerprint


class ContextModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class ContextTimeframe(StrEnum):
    MINUTE_5 = "MINUTE_5"
    MINUTE_15 = "MINUTE_15"
    HOUR = "HOUR"
    HOUR_4 = "HOUR_4"
    DAY = "DAY"

    @property
    def seconds(self) -> int:
        return {
            ContextTimeframe.MINUTE_5: 300,
            ContextTimeframe.MINUTE_15: 900,
            ContextTimeframe.HOUR: 3600,
            ContextTimeframe.HOUR_4: 14400,
            ContextTimeframe.DAY: 86400,
        }[self]


class SessionState(StrEnum):
    ASIA = "ASIA"
    LONDON = "LONDON"
    NEW_YORK = "NEW_YORK"
    LONDON_NEW_YORK_OVERLAP = "LONDON_NEW_YORK_OVERLAP"
    ROLLOVER = "ROLLOVER"
    CLOSED = "CLOSED"
    HOLIDAY_OR_THIN = "HOLIDAY_OR_THIN"
    UNKNOWN = "UNKNOWN"


class LiquidityState(StrEnum):
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"
    ABNORMAL = "ABNORMAL"
    UNKNOWN = "UNKNOWN"


class VolatilityState(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    EXTREME = "EXTREME"
    COMPRESSION = "COMPRESSION"
    EXPANSION = "EXPANSION"
    UNKNOWN = "UNKNOWN"


class TrendState(StrEnum):
    STRONG_BULL_TREND = "STRONG_BULL_TREND"
    WEAK_BULL_TREND = "WEAK_BULL_TREND"
    RANGE = "RANGE"
    TRANSITION = "TRANSITION"
    HIGH_VOLATILITY_DISORDER = "HIGH_VOLATILITY_DISORDER"
    UNKNOWN = "UNKNOWN"


class RangeState(StrEnum):
    ESTABLISHED = "ESTABLISHED"
    NOT_RANGE = "NOT_RANGE"
    UNKNOWN = "UNKNOWN"


class CompressionState(StrEnum):
    COMPRESSED = "COMPRESSED"
    NORMAL = "NORMAL"
    UNKNOWN = "UNKNOWN"


class BreakoutState(StrEnum):
    CONFIRMED_UP = "CONFIRMED_UP"
    CONFIRMED_DOWN = "CONFIRMED_DOWN"
    NONE = "NONE"
    UNKNOWN = "UNKNOWN"


class EventCategory(StrEnum):
    CENTRAL_BANK_DECISION = "CENTRAL_BANK_DECISION"
    CENTRAL_BANK_SPEECH = "CENTRAL_BANK_SPEECH"
    INFLATION = "INFLATION"
    EMPLOYMENT = "EMPLOYMENT"
    GDP = "GDP"
    PMI = "PMI"
    RETAIL_SALES = "RETAIL_SALES"
    TRADE_BALANCE = "TRADE_BALANCE"
    OTHER = "OTHER"


class EventImportance(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class ScheduledEventState(StrEnum):
    NO_EVENT = "NO_EVENT"
    PRE_EVENT = "PRE_EVENT"
    INITIAL_REACTION = "INITIAL_REACTION"
    POST_EVENT_STABILIZING = "POST_EVENT_STABILIZING"
    POST_EVENT_ELIGIBLE = "POST_EVENT_ELIGIBLE"
    STALE_EVENT = "STALE_EVENT"
    UNKNOWN = "UNKNOWN"


class NewsState(StrEnum):
    CLEAR = "CLEAR"
    SCHEDULED = "SCHEDULED"
    UNSCHEDULED_CAUTION = "UNSCHEDULED_CAUTION"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class ContextQuality(StrEnum):
    VALID = "VALID"
    DEGRADED = "DEGRADED"
    INVALID = "INVALID"


class ContextReasonCode(StrEnum):
    STALE_DATA = "STALE_DATA"
    FUTURE_DATA = "FUTURE_DATA"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    MARKET_CLOSED = "MARKET_CLOSED"
    UNKNOWN_SESSION = "UNKNOWN_SESSION"
    LOW_LIQUIDITY = "LOW_LIQUIDITY"
    ABNORMAL_SPREAD = "ABNORMAL_SPREAD"
    EXTREME_VOLATILITY = "EXTREME_VOLATILITY"
    REGIME_TRANSITION = "REGIME_TRANSITION"
    PRE_HIGH_IMPACT_EVENT = "PRE_HIGH_IMPACT_EVENT"
    INITIAL_NEWS_REACTION = "INITIAL_NEWS_REACTION"
    UNSCHEDULED_NEWS = "UNSCHEDULED_NEWS"
    CONFLICTING_CONTEXT = "CONFLICTING_CONTEXT"
    MODEL_NOT_READY = "MODEL_NOT_READY"
    EVENT_CONTEXT_UNAVAILABLE = "EVENT_CONTEXT_UNAVAILABLE"
    HOLIDAY_CONTEXT_UNAVAILABLE = "HOLIDAY_CONTEXT_UNAVAILABLE"
    STALE_QUOTE = "STALE_QUOTE"
    INCOMPLETE_QUOTE = "INCOMPLETE_QUOTE"
    UNFINISHED_BAR = "UNFINISHED_BAR"


class ContextSourceEvidence(ContextModel):
    source_identifier: str = Field(min_length=1, max_length=128)
    source_timestamp: datetime
    source_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("source_timestamp")
    @classmethod
    def utc_source_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("context source timestamp must be timezone-aware UTC")
        return value.astimezone(UTC)


class SessionClassification(ContextModel):
    session: SessionState
    session_overlap: bool
    minutes_from_session_open: int | None
    minutes_to_session_close: int | None
    reason: str | None = None


class EconomicEvent(ContextModel):
    event_id: str = Field(min_length=1, max_length=128)
    currency: str = Field(min_length=3, max_length=8)
    country: str = Field(min_length=2, max_length=80)
    category: EventCategory
    importance: EventImportance
    scheduled_timestamp: datetime
    forecast: Decimal | None = None
    previous: Decimal | None = None
    revised_previous: Decimal | None = None
    revised_at: datetime | None = None
    actual: Decimal | None = None
    released_at: datetime | None = None
    source: str = Field(min_length=1, max_length=100)

    @field_validator("scheduled_timestamp", "released_at", "revised_at")
    @classmethod
    def utc_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value)
        ):
            raise ValueError("economic event timestamps must be timezone-aware UTC")
        return value.astimezone(UTC) if value else None


class EventContext(ContextModel):
    state: ScheduledEventState
    event_id: str | None = None
    category: EventCategory | None = None
    minutes_to_next_high_impact_event: int | None = None
    minutes_since_previous_high_impact_event: int | None = None
    completed_post_event_bars: int = Field(default=0, ge=0)


class NewsItem(ContextModel):
    news_item_id: str
    published_at: datetime
    instrument_or_currency: str
    category: str
    source: str
    importance: EventImportance
    scheduled: bool
    event_link: str | None = None
    structured_summary: str

    @field_validator("published_at")
    @classmethod
    def utc_published(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("news timestamp must be timezone-aware UTC")
        return value.astimezone(UTC)


class NewsContext(ContextModel):
    state: NewsState
    latest_news_item_id: str | None = None
    age_seconds: int | None = Field(default=None, ge=0)


class MarketContextSnapshot(ContextModel):
    context_id: str = Field(min_length=64, max_length=64)
    instrument: str
    epic: str
    evaluation_timestamp: datetime
    data_cutoff_timestamp: datetime
    timeframe: ContextTimeframe
    session: SessionState
    session_overlap: bool
    day_of_week: int = Field(ge=0, le=6)
    minutes_from_session_open: int | None
    minutes_to_session_close: int | None
    liquidity_state: LiquidityState
    spread_bps: Decimal
    spread_percentile: Decimal
    volatility_state: VolatilityState
    realized_volatility: Decimal
    atr: Decimal
    volatility_percentile: Decimal
    trend_state: TrendState
    trend_strength: Decimal
    kalman_slope: Decimal | None
    kalman_uncertainty: Decimal | None
    hmm_regime: str
    hmm_probabilities: tuple[tuple[str, Decimal], ...]
    range_state: RangeState
    compression_state: CompressionState
    breakout_state: BreakoutState
    scheduled_event_state: ScheduledEventState
    minutes_to_next_high_impact_event: int | None
    minutes_since_previous_high_impact_event: int | None
    event_category: EventCategory | None
    news_state: NewsState
    market_status: str
    data_freshness_seconds: int = Field(ge=0)
    context_quality: ContextQuality
    reason_codes: tuple[ContextReasonCode, ...]
    configuration_fingerprint: str = Field(min_length=64, max_length=64)
    source_evidence: tuple[ContextSourceEvidence, ...] = ()
    context_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("evaluation_timestamp", "data_cutoff_timestamp")
    @classmethod
    def utc_context_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("context timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.data_cutoff_timestamp > self.evaluation_timestamp:
            raise ValueError("context cutoff cannot be in the future")
        fields = self.model_dump(mode="python", exclude={"context_id", "context_fingerprint"})
        expected = fingerprint(fields)
        if self.context_id != expected or self.context_fingerprint != expected:
            raise ValueError("market context fingerprint mismatch")
        return self
