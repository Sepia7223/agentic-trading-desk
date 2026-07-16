"""Deterministic normalized-distance comparison for completed trades."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, localcontext

from trading_desk.journal.models import (
    FinancialOutcome,
    JournalRecord,
    ProcessClassification,
    SimilarityFeatures,
    SimilarityMatch,
)

_NUMERIC_FIELDS = (
    "kalman_slope",
    "volatility",
    "spread_bps",
    "holding_period_seconds",
    "risk_fraction",
    "entry_distance_to_stop",
    "maximum_favorable_excursion",
    "maximum_adverse_excursion",
    "cost_fraction",
)


def extract_similarity_features(record: JournalRecord) -> SimilarityFeatures:
    payload = record.payload
    raw_probabilities = payload.get("regime_probabilities", ())
    probabilities = raw_probabilities if isinstance(raw_probabilities, (list, tuple)) else ()
    return SimilarityFeatures(
        source_record_id=record.source_record_id,
        timestamp=record.effective_at,
        instrument=record.instrument or str(payload.get("instrument", "UNKNOWN")),
        strategy_variant=record.strategy_variant,
        entry_regime=_text(payload.get("entry_regime")),
        regime_probabilities=tuple(Decimal(str(item)) for item in probabilities),
        kalman_slope=_decimal(payload.get("kalman_slope")),
        volatility=_decimal(payload.get("volatility")),
        spread_bps=_decimal(payload.get("spread_bps")),
        time_of_day=_text(payload.get("time_of_day")),
        session=_text(payload.get("session")),
        holding_period_seconds=_integer(payload.get("holding_period_seconds")),
        risk_fraction=_decimal(payload.get("risk_fraction")),
        entry_distance_to_stop=_decimal(payload.get("entry_distance_to_stop")),
        maximum_favorable_excursion=_decimal(payload.get("maximum_favorable_excursion")),
        maximum_adverse_excursion=_decimal(payload.get("maximum_adverse_excursion")),
        cost_fraction=_decimal(payload.get("cost_fraction")),
        process_classification=ProcessClassification(
            _text(payload.get("process_classification")) or ProcessClassification.UNKNOWN.value
        ),
        financial_outcome=FinancialOutcome(
            _text(payload.get("financial_outcome")) or FinancialOutcome.UNKNOWN.value
        ),
    )


def nearest_records(
    target: SimilarityFeatures,
    records: tuple[SimilarityFeatures, ...],
    *,
    cutoff: datetime,
    limit: int = 5,
) -> tuple[SimilarityMatch, ...]:
    if cutoff.tzinfo is None:
        raise ValueError("similarity cutoff must be timezone-aware")
    if limit < 1:
        raise ValueError("similarity limit must be positive")
    eligible = tuple(item for item in records if item.timestamp <= cutoff and item != target)
    scales = _scales((target, *eligible))
    matches = tuple(
        SimilarityMatch(
            source_record_id=item.source_record_id,
            distance=_distance(target, item, scales),
            features=item,
        )
        for item in eligible
    )
    return tuple(sorted(matches, key=lambda item: (item.distance, item.source_record_id))[:limit])


def _scales(records: tuple[SimilarityFeatures, ...]) -> dict[str, Decimal]:
    scales: dict[str, Decimal] = {}
    for field in _NUMERIC_FIELDS:
        values = tuple(
            value for record in records if (value := _numeric(getattr(record, field))) is not None
        )
        spread = max(values) - min(values) if values else Decimal("0")
        scales[field] = spread if spread > 0 else Decimal("1")
    return scales


def _distance(
    left: SimilarityFeatures, right: SimilarityFeatures, scales: dict[str, Decimal]
) -> Decimal:
    components: list[Decimal] = []
    for field in _NUMERIC_FIELDS:
        a, b = _numeric(getattr(left, field)), _numeric(getattr(right, field))
        if a is not None and b is not None:
            components.append(((a - b) / scales[field]) ** 2)
    categorical = ("instrument", "strategy_variant", "entry_regime", "session")
    components.extend(
        Decimal("0") if getattr(left, field) == getattr(right, field) else Decimal("1")
        for field in categorical
        if getattr(left, field) is not None and getattr(right, field) is not None
    )
    if not components:
        return Decimal("Infinity")
    with localcontext() as context:
        context.prec = 28
        return (sum(components, Decimal("0")) / Decimal(len(components))).sqrt()


def _numeric(value: Decimal | int | None) -> Decimal | None:
    return Decimal(value) if isinstance(value, int) else value


def _decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value)) if value is not None else None
    except Exception:
        return None


def _integer(value: object) -> int | None:
    try:
        return int(str(value)) if value is not None else None
    except Exception:
        return None


def _text(value: object) -> str | None:
    return str(value) if value is not None else None
