"""Explicit reporting currency with timestamped conversion evidence.

Conversion never fabricates a rate. When no dated rate exists for a currency
at or before the requested instant, conversion returns ``None`` and the caller
must render the dependent measure unavailable rather than inventing a value.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from trading_desk.analytics.models import AnalyticsModel


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("conversion evidence timestamps must be timezone-aware UTC")
    return value.astimezone(UTC)


class ConversionRate(AnalyticsModel):
    """One dated exchange rate traced to an immutable source record."""

    schema_version: Literal["analytics-conversion-rate-v1"] = "analytics-conversion-rate-v1"
    from_currency: str = Field(min_length=3, max_length=3)
    to_currency: str = Field(min_length=3, max_length=3)
    rate: Decimal = Field(gt=0)
    as_of: datetime
    source_record_id: str = Field(min_length=1)

    @field_validator("as_of")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def distinct_currencies(self) -> Self:
        if self.from_currency == self.to_currency:
            raise ValueError("conversion rate currencies must differ")
        return self


class ConversionPolicy(AnalyticsModel):
    """Reporting currency plus the dated rate evidence available for it."""

    schema_version: Literal["analytics-conversion-policy-v1"] = "analytics-conversion-policy-v1"
    reporting_currency: str = Field(min_length=3, max_length=3)
    rates: tuple[ConversionRate, ...] = ()

    @model_validator(mode="after")
    def rates_target_reporting_currency(self) -> Self:
        for rate in self.rates:
            if rate.to_currency != self.reporting_currency:
                raise ValueError("every conversion rate must target the reporting currency")
        return self

    def rate_for(self, currency: str, at: datetime) -> ConversionRate | None:
        """Most recent rate for ``currency`` dated at or before ``at``."""

        if currency == self.reporting_currency:
            return None
        moment = _utc(at)
        candidates = [
            rate for rate in self.rates if rate.from_currency == currency and rate.as_of <= moment
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda rate: (rate.as_of, rate.source_record_id))

    def convert(self, amount: Decimal, currency: str, at: datetime) -> Decimal | None:
        """Convert ``amount`` in ``currency`` to the reporting currency.

        Returns ``None`` when no dated rate exists — the dependent measure is
        then rendered unavailable, never fabricated.
        """

        if currency == self.reporting_currency:
            return amount
        rate = self.rate_for(currency, at)
        if rate is None:
            return None
        return amount * rate.rate
