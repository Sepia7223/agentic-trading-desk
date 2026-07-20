"""Collect certification evidence from authoritative journal records.

Maps each certification item to the immutable record type(s) whose presence is
evidence it occurred, then computes the deterministic verdict. Items that cannot
be derived from records alone — the two restart checkpoints — stay pending until
an operator records them explicitly; the collector never infers them. Unresolved
halts and reconciliation errors are surfaced as defects. Nothing here forces a
trade or fabricates evidence.
"""

from __future__ import annotations

from trading_desk.certification import (
    CertificationDefect,
    CertificationItem,
    DefectCategory,
    EvidenceObservation,
    evaluate_certification,
)
from trading_desk.certification.verdict import CertificationOutcome
from trading_desk.journal.models import JournalRecordType
from trading_desk.operations.models import RecordProjection

_ANY = "ANY"
_ALL = "ALL"

_EVIDENCE_MAP: dict[CertificationItem, tuple[str, frozenset[JournalRecordType]]] = {
    CertificationItem.ENVIRONMENT_SECRET_PREFLIGHT: (
        _ANY,
        frozenset({JournalRecordType.SCHEDULER_CYCLE}),
    ),
    CertificationItem.AUTHENTICATION_ACCOUNT_DISCOVERY: (
        _ANY,
        frozenset(
            {
                JournalRecordType.DEMO_CAMPAIGN_STARTED,
                JournalRecordType.DEMO_CAMPAIGN_SNAPSHOT_CREATED,
            }
        ),
    ),
    CertificationItem.AUTHORITATIVE_ACCOUNT_STATE: (
        _ANY,
        frozenset(
            {
                JournalRecordType.PAPER_PORTFOLIO_EVENT,
                JournalRecordType.DEMO_CAMPAIGN_SNAPSHOT_CREATED,
            }
        ),
    ),
    CertificationItem.COMPLETED_BAR_SCHEDULING: (
        _ANY,
        frozenset({JournalRecordType.SCHEDULER_CYCLE}),
    ),
    CertificationItem.CONTEXT_ROUTING_SCORING_PORTFOLIO: (
        _ALL,
        frozenset(
            {
                JournalRecordType.MARKET_CONTEXT,
                JournalRecordType.ROUTER_DECISION,
                JournalRecordType.OPPORTUNITY_SCORED,
                JournalRecordType.PORTFOLIO_BATCH_EVALUATED,
            }
        ),
    ),
    CertificationItem.ACCEPTED_CANDIDATE_TO_RISK: (
        _ANY,
        frozenset({JournalRecordType.OPPORTUNITY_RISK_SUBMITTED}),
    ),
    CertificationItem.RISK_APPROVAL_AND_QUANTITY: (
        _ANY,
        frozenset(
            {
                JournalRecordType.RISK_DECISION,
                JournalRecordType.OPPORTUNITY_EXECUTION_APPROVED,
            }
        ),
    ),
    CertificationItem.CONTROLLED_ORDER_SUBMISSION: (
        _ANY,
        frozenset({JournalRecordType.EXECUTION_REQUEST}),
    ),
    CertificationItem.CONFIRMATION_AND_RECONCILIATION: (
        _ANY,
        frozenset({JournalRecordType.EXECUTION_RECONCILIATION}),
    ),
    CertificationItem.DURABLE_TRADE_STATE: (
        _ANY,
        frozenset({JournalRecordType.PAPER_FILL, JournalRecordType.PAPER_PORTFOLIO_EVENT}),
    ),
    CertificationItem.LIFECYCLE_MONITORING_AFTER_RESTART: (
        _ANY,
        frozenset({JournalRecordType.POSITION_MONITOR_SNAPSHOT}),
    ),
    CertificationItem.NATURAL_OR_GOVERNED_CLOSE: (
        _ANY,
        frozenset({JournalRecordType.CLOSE_REQUEST, JournalRecordType.POSITION_CLOSED}),
    ),
    CertificationItem.CLOSE_CONFIRMATION_AND_RECONCILIATION: (
        _ANY,
        frozenset({JournalRecordType.CLOSE_RECONCILIATION, JournalRecordType.CLOSE_CONFIRMATION}),
    ),
    CertificationItem.REALIZED_PNL_AND_ATTRIBUTION: (
        _ANY,
        frozenset({JournalRecordType.PAPER_CLOSED_TRADE}),
    ),
}

# Requires an explicit operator-recorded restart checkpoint; never inferred.
_OPERATOR_OBSERVED = frozenset(
    {
        CertificationItem.RESTART_WITH_ACTIVE_POSITION,
        CertificationItem.FINAL_RESTART_NO_DUPLICATE_MUTATION,
    }
)

_DEFECT_MAP: dict[JournalRecordType, DefectCategory] = {
    JournalRecordType.DEMO_CAMPAIGN_HALTED: DefectCategory.SAFETY,
    JournalRecordType.POSITION_LIFECYCLE_HALTED: DefectCategory.SAFETY,
    JournalRecordType.POSITION_CLOSE_BLOCKED: DefectCategory.SAFETY,
    JournalRecordType.EXECUTION_FAILURE: DefectCategory.RECONCILIATION,
}


def _first_by_type(records: tuple[RecordProjection, ...]) -> dict[str, RecordProjection]:
    index: dict[str, RecordProjection] = {}
    for record in records:
        index.setdefault(record.record_type, record)
    return index


def collect_certification_evidence(
    records: tuple[RecordProjection, ...],
) -> tuple[EvidenceObservation, ...]:
    """Derive an evidence observation for each item from present record types."""

    first = _first_by_type(records)
    observations: list[EvidenceObservation] = []
    for item in CertificationItem:
        if item is CertificationItem.OPERATIONS_CENTER_VISIBILITY:
            observed = len(records) > 0
            source = records[0].source_record_id if records else ""
        elif item in _OPERATOR_OBSERVED:
            observed = False
            source = ""
        else:
            mode, types = _EVIDENCE_MAP[item]
            present = [record_type for record_type in types if record_type.value in first]
            observed = len(present) == len(types) if mode == _ALL else len(present) > 0
            source = first[present[0].value].source_record_id if observed and present else ""
        observations.append(
            EvidenceObservation(
                item=item,
                observed=observed,
                source_evidence_id=source if observed else "",
            )
        )
    return tuple(observations)


def collect_certification_defects(
    records: tuple[RecordProjection, ...],
) -> tuple[CertificationDefect, ...]:
    first = _first_by_type(records)
    defects: list[CertificationDefect] = []
    for record_type, category in _DEFECT_MAP.items():
        record = first.get(record_type.value)
        if record is not None:
            defects.append(
                CertificationDefect(
                    category=category,
                    summary=f"unresolved {record_type.value}",
                    source_evidence_id=record.source_record_id,
                )
            )
    return tuple(defects)


def certification_outcome(records: tuple[RecordProjection, ...]) -> CertificationOutcome:
    return evaluate_certification(
        collect_certification_evidence(records),
        collect_certification_defects(records),
    )


def build_certification_status(records: tuple[RecordProjection, ...]) -> dict[str, object]:
    """Read-only projection of the current deterministic certification state."""

    outcome = certification_outcome(records)
    return {
        "authority": "READ_ONLY",
        "verdict": outcome.verdict.value,
        "outcome_id": outcome.outcome_id,
        "software_readonly_complete": outcome.software_readonly_complete,
        "natural_trade_complete": outcome.natural_trade_complete,
        "satisfied_items": [item.value for item in outcome.satisfied_items],
        "pending_items": [item.value for item in outcome.pending_items],
        "defects": [
            {"category": defect.category.value, "summary": defect.summary}
            for defect in outcome.defects
        ],
        "rationale": outcome.rationale,
        "note": (
            "CERTIFIED requires a naturally occurring bounded Demo trade observed "
            "end-to-end; restart checkpoints are operator-recorded and never inferred."
        ),
    }
