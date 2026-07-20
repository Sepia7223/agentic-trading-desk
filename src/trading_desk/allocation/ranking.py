"""Deterministic candidate ranking with an explicit immutable ordering.

The ordering is fixed by specification and contains no randomness: two
identical batches always rank identically, and ties fall through to stable
identifiers so the final order is total.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from trading_desk.allocation.models import AllocationModel, PortfolioCandidate


class RankingComponents(AllocationModel):
    """Pre-computed, cutoff-safe scoring inputs for one candidate."""

    candidate_id: str = Field(min_length=1)
    eligible: bool
    risk_adjusted_score: Decimal
    regime_fit: Decimal = Field(ge=0, le=1)
    diversification_benefit: Decimal = Field(ge=0, le=1)
    concentration_penalty: Decimal = Field(ge=0)


class RankedCandidate(AllocationModel):
    rank: int = Field(ge=1)
    candidate: PortfolioCandidate
    components: RankingComponents


def rank_candidates(
    candidates: tuple[PortfolioCandidate, ...],
    components: tuple[RankingComponents, ...],
) -> tuple[RankedCandidate, ...]:
    """Total, deterministic ordering of one batch.

    Sort precedence (higher first unless noted): eligibility, positive net
    expected value, risk-adjusted score, regime fit, diversification
    benefit, LOWER concentration penalty, EARLIER completed bar, then stable
    strategy, instrument, and candidate identifiers.
    """

    by_candidate = {item.candidate_id: item for item in components}
    missing = [item.candidate_id for item in candidates if item.candidate_id not in by_candidate]
    if missing:
        raise ValueError(f"ranking components missing for candidates: {missing}")
    duplicate_ids = len({item.candidate_id for item in candidates}) != len(candidates)
    if duplicate_ids:
        raise ValueError("candidate identifiers within a batch must be unique")

    def sort_key(candidate: PortfolioCandidate) -> tuple[object, ...]:
        scores = by_candidate[candidate.candidate_id]
        return (
            0 if scores.eligible else 1,
            0 if candidate.net_expected_value > 0 else 1,
            -scores.risk_adjusted_score,
            -scores.regime_fit,
            -scores.diversification_benefit,
            scores.concentration_penalty,
            candidate.completed_bar_timestamp,
            candidate.strategy_id,
            candidate.instrument,
            candidate.candidate_id,
        )

    ordered = sorted(candidates, key=sort_key)
    return tuple(
        RankedCandidate(
            rank=position,
            candidate=candidate,
            components=by_candidate[candidate.candidate_id],
        )
        for position, candidate in enumerate(ordered, start=1)
    )
