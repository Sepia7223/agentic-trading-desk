"""Stable bounded Opportunity ranking."""

from datetime import datetime

from trading_desk.opportunity.config import OpportunityEngineConfiguration
from trading_desk.opportunity.fingerprints import fingerprint
from trading_desk.opportunity.models import (
    CandidateStatus,
    OpportunityCandidate,
    OpportunityRanking,
)


def rank_candidates(
    cycle_id: str,
    created_at: datetime,
    candidates: tuple[OpportunityCandidate, ...],
    configuration: OpportunityEngineConfiguration,
) -> OpportunityRanking:
    eligible = sorted(
        (
            item
            for item in candidates
            if item.status is CandidateStatus.ELIGIBLE and item.net_expected_value > 0
        ),
        key=lambda item: (
            -item.opportunity_score,
            -item.net_expected_value,
            -item.data_quality_score,
            item.costs.total_estimated_cost,
            item.candidate_id,
        ),
    )
    selected = eligible[: configuration.maximum_candidates_sent_to_risk]
    rejected = [item for item in candidates if item not in selected]
    fields = {
        "cycle_id": cycle_id,
        "created_at": created_at,
        "configuration_fingerprint": configuration.configuration_fingerprint,
        "ordered_candidate_ids": tuple(item.candidate_id for item in eligible),
        "selected_candidate_ids": tuple(item.candidate_id for item in selected),
        "rejected_candidate_ids": tuple(item.candidate_id for item in rejected),
        "rejection_reasons": tuple(
            (item.candidate_id, item.rejection_reasons) for item in rejected
        ),
    }
    identity = fingerprint(fields)
    return OpportunityRanking.model_validate(
        {**fields, "ranking_id": identity, "ranking_fingerprint": identity}
    )
