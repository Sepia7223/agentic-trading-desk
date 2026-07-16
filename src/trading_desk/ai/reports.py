"""Deterministic historical statistics supplied to advisory analysis."""

from __future__ import annotations

from decimal import Decimal

from trading_desk.ai.models import (
    EvidenceStrength,
    FinancialOutcome,
    HistoricalComparison,
    HistoricalExample,
)

ZERO = Decimal("0")


def summarize_historical_evidence(
    records: tuple[HistoricalExample, ...], matching_criteria: tuple[str, ...]
) -> HistoricalComparison:
    returns = tuple(item.net_return for item in records if item.net_return is not None)
    holding = tuple(
        item.holding_period_seconds for item in records if item.holding_period_seconds is not None
    )
    wins = sum(item.financial_outcome is FinancialOutcome.PROFIT for item in records)
    sample_size = len(records)
    patterns = tuple(sorted({reason for item in records for reason in item.reason_codes}))
    return HistoricalComparison(
        sample_size=sample_size,
        matching_criteria=matching_criteria,
        average_net_return=_average(returns),
        win_rate=(Decimal(wins) / Decimal(sample_size) if sample_size else None),
        average_holding_period_seconds=_average(holding),
        common_failure_patterns=patterns,
        uncertainty=_uncertainty(sample_size),
        evidence_strength=_strength(sample_size),
    )


def _average(values: tuple[Decimal, ...]) -> Decimal | None:
    return sum(values, ZERO) / Decimal(len(values)) if values else None


def _strength(sample_size: int) -> EvidenceStrength:
    if sample_size < 5:
        return EvidenceStrength.INSUFFICIENT_SAMPLE
    if sample_size < 20:
        return EvidenceStrength.WEAK_EVIDENCE
    if sample_size < 50:
        return EvidenceStrength.MODERATE_EVIDENCE
    return EvidenceStrength.STRONGER_HISTORICAL_EVIDENCE


def _uncertainty(sample_size: int) -> str:
    return (
        "Sample is too small for reliable inference."
        if sample_size < 5
        else "Historical association does not establish future performance."
    )
