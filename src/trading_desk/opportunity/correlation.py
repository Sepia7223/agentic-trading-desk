"""Deterministic duplicate, position, cooldown, and correlation suppression."""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from trading_desk.opportunity.fingerprints import fingerprint
from trading_desk.opportunity.models import (
    CandidateStatus,
    OpportunityCandidate,
    OpportunityRejectionCode,
)


def suppress_candidates(
    candidates: tuple[OpportunityCandidate, ...],
    *,
    existing_epics: tuple[str, ...] = (),
    occupied_correlation_groups: tuple[str, ...] = (),
    recent_entries: tuple[tuple[str, datetime], ...] = (),
    cooldown_seconds: int = 0,
    maximum_correlated_positions: int = 1,
    current_position_count: int = 0,
    maximum_existing_positions: int = 3,
) -> tuple[OpportunityCandidate, ...]:
    ordered = sorted(candidates, key=_strength)
    seen_ids: set[str] = set()
    seen_bars: set[tuple[str, object, datetime]] = set()
    selected_instruments: set[str] = set()
    selected_groups: dict[str, int] = {}
    occupied_groups = Counter(occupied_correlation_groups)
    recent = dict(recent_entries)
    results: list[OpportunityCandidate] = []
    for candidate in ordered:
        reasons = list(candidate.rejection_reasons)
        bar_key = (
            candidate.instrument_id,
            candidate.timeframe,
            candidate.completed_bar_timestamp,
        )
        if candidate.candidate_fingerprint in seen_ids:
            reasons.append(OpportunityRejectionCode.DUPLICATE_CANDIDATE)
        elif bar_key in seen_bars:
            reasons.append(OpportunityRejectionCode.SAME_BAR_DUPLICATE)
        elif current_position_count >= maximum_existing_positions:
            reasons.append(OpportunityRejectionCode.PORTFOLIO_EXPOSURE_LIMIT)
        elif candidate.epic in existing_epics:
            reasons.append(OpportunityRejectionCode.EXISTING_POSITION_CONFLICT)
        elif candidate.instrument_id in selected_instruments:
            reasons.append(OpportunityRejectionCode.LOWER_RANKED_SAME_INSTRUMENT)
        else:
            previous = recent.get(candidate.epic)
            if (
                previous is not None
                and (candidate.created_at - previous).total_seconds() < cooldown_seconds
            ):
                reasons.append(OpportunityRejectionCode.RECENT_REENTRY_COOLDOWN)
            correlation_count = max(
                (
                    selected_groups.get(group, 0) + occupied_groups[group]
                    for group in candidate.correlation_groups
                ),
                default=0,
            )
            if correlation_count >= maximum_correlated_positions:
                reasons.append(OpportunityRejectionCode.CORRELATED_EXPOSURE_LIMIT)
        seen_ids.add(candidate.candidate_fingerprint)
        seen_bars.add(bar_key)
        if reasons:
            fields = candidate.model_dump(
                mode="python", exclude={"candidate_id", "candidate_fingerprint"}
            )
            fields.update(
                status=CandidateStatus.SUPPRESSED,
                rejection_reasons=tuple(dict.fromkeys(reasons)),
            )
            identity = fingerprint(fields)
            results.append(
                OpportunityCandidate.model_validate(
                    {**fields, "candidate_id": identity, "candidate_fingerprint": identity}
                )
            )
            continue
        selected_instruments.add(candidate.instrument_id)
        for group in candidate.correlation_groups:
            selected_groups[group] = selected_groups.get(group, 0) + 1
        results.append(candidate)
    return tuple(results)


def _strength(candidate: OpportunityCandidate) -> tuple[object, ...]:
    return (
        -candidate.opportunity_score,
        -candidate.net_expected_value,
        -candidate.data_quality_score,
        candidate.costs.total_estimated_cost,
        candidate.candidate_id,
    )
