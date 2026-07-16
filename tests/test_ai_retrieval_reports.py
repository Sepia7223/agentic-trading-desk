from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from ai_helpers import NOW, historical
from trading_desk.ai.models import (
    EvidenceStrength,
    FinancialOutcome,
    HistoricalExample,
    RetrievalFilter,
)
from trading_desk.ai.reports import summarize_historical_evidence
from trading_desk.ai.retrieval import StructuredHistoricalRepository


def records() -> tuple[HistoricalExample, ...]:
    return (
        historical("old", days_ago=3),
        historical("middle", days_ago=2).model_copy(
            update={
                "instrument": "US 500",
                "regime": "TRANSITIONAL",
                "risk_status": "REJECTED",
                "reason_codes": ("SPREAD_TOO_WIDE",),
                "financial_outcome": FinancialOutcome.LOSS,
                "net_return": Decimal("-0.02"),
                "spread": Decimal("12"),
            }
        ),
        historical("recent", days_ago=1),
        historical("future", days_ago=-1),
    )


def test_retrieval_is_stable_and_excludes_future_records() -> None:
    repository = StructuredHistoricalRepository(tuple(reversed(records())))
    selected = repository.query(RetrievalFilter(), cutoff=NOW, limit=10)
    assert tuple(item.record_id for item in selected) == ("old", "middle", "recent")
    assert all(item.timestamp <= NOW for item in selected)


def test_structured_filters_and_source_traceability() -> None:
    repository = StructuredHistoricalRepository(records())
    selected = repository.query(
        RetrievalFilter(
            instrument="US 500",
            regime="TRANSITIONAL",
            risk_status="REJECTED",
            reason_codes=("SPREAD_TOO_WIDE",),
            financial_outcome=FinancialOutcome.LOSS,
            minimum_spread=Decimal("10"),
            maximum_spread=Decimal("15"),
            start_at=NOW - timedelta(days=3),
            end_at=NOW,
        ),
        cutoff=NOW,
        limit=5,
    )
    assert tuple(item.record_id for item in selected) == ("middle",)


def test_strategy_and_holding_period_filters() -> None:
    repository = StructuredHistoricalRepository(records())
    selected = repository.query(
        RetrievalFilter(
            strategy_variant="BASELINE_KALMAN_HMM",
            minimum_holding_period_seconds=Decimal("3500"),
            maximum_holding_period_seconds=Decimal("3700"),
        ),
        cutoff=NOW,
        limit=10,
    )
    assert len(selected) == 3


def test_repository_rejects_duplicate_records() -> None:
    repository = StructuredHistoricalRepository((historical(),))
    try:
        repository.append(historical())
    except ValueError as error:
        assert "already exists" in str(error)
    else:
        raise AssertionError("duplicate historical record was accepted")


def test_deterministic_historical_summary_labels_small_samples() -> None:
    summary = summarize_historical_evidence(
        (historical("one"), historical("two")), ("instrument=EUR/USD",)
    )
    assert summary.sample_size == 2
    assert summary.evidence_strength is EvidenceStrength.INSUFFICIENT_SAMPLE
    assert summary.average_net_return == Decimal("0.01")
    assert summary.win_rate == Decimal("1")
    assert "too small" in summary.uncertainty


def test_evidence_strength_thresholds_are_deterministic() -> None:
    for count, expected in (
        (5, EvidenceStrength.WEAK_EVIDENCE),
        (20, EvidenceStrength.MODERATE_EVIDENCE),
        (50, EvidenceStrength.STRONGER_HISTORICAL_EVIDENCE),
    ):
        sample = tuple(historical(f"record-{index}") for index in range(count))
        assert summarize_historical_evidence(sample, ()).evidence_strength is expected
