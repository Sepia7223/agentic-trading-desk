"""Deterministic structured historical retrieval with cutoff protection."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from trading_desk.ai.models import HistoricalExample, RetrievalFilter


class StructuredHistoricalRepository:
    def __init__(self, records: tuple[HistoricalExample, ...] = ()) -> None:
        self._records = tuple(sorted(records, key=lambda item: (item.timestamp, item.record_id)))

    @property
    def records(self) -> tuple[HistoricalExample, ...]:
        return self._records

    def append(self, record: HistoricalExample) -> None:
        if any(item.record_id == record.record_id for item in self._records):
            raise ValueError("historical record ID already exists")
        self._records = tuple(
            sorted(self._records + (record,), key=lambda item: (item.timestamp, item.record_id))
        )

    def query(
        self,
        filters: RetrievalFilter,
        *,
        cutoff: datetime,
        limit: int,
    ) -> tuple[HistoricalExample, ...]:
        if cutoff.tzinfo is None:
            raise ValueError("historical cutoff must be timezone-aware")
        if limit < 1:
            raise ValueError("historical retrieval limit must be positive")
        selected = [item for item in self._records if item.timestamp <= cutoff]
        selected = [item for item in selected if _matches(item, filters)]
        return tuple(selected[-limit:])


def _matches(record: HistoricalExample, filters: RetrievalFilter) -> bool:
    equal_fields = (
        (filters.instrument, record.instrument),
        (filters.strategy_variant, record.strategy_variant),
        (filters.regime, record.regime),
        (filters.risk_status, record.risk_status),
        (filters.financial_outcome, record.financial_outcome),
        (filters.process_classification, record.process_classification),
    )
    if any(expected is not None and actual != expected for expected, actual in equal_fields):
        return False
    if filters.reason_codes and not set(filters.reason_codes).issubset(record.reason_codes):
        return False
    if filters.start_at is not None and record.timestamp < filters.start_at:
        return False
    if filters.end_at is not None and record.timestamp > filters.end_at:
        return False
    ranges = (
        (record.spread, filters.minimum_spread, filters.maximum_spread),
        (
            record.holding_period_seconds,
            filters.minimum_holding_period_seconds,
            filters.maximum_holding_period_seconds,
        ),
    )
    return all(_within(value, minimum, maximum) for value, minimum, maximum in ranges)


def _within(value: Decimal | None, minimum: Decimal | None, maximum: Decimal | None) -> bool:
    if minimum is not None and (value is None or value < minimum):
        return False
    return not (maximum is not None and (value is None or value > maximum))
