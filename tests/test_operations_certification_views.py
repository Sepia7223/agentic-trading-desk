"""Milestone 17: journal-record certification evidence collector."""

from __future__ import annotations

from datetime import UTC, datetime

from trading_desk.operations.certification_views import (
    build_certification_status,
    certification_outcome,
    collect_certification_evidence,
)
from trading_desk.operations.models import RecordProjection

BASE = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)


def record(index: int, record_type: str) -> RecordProjection:
    return RecordProjection(
        journal_record_id=f"jr-{index:03d}",
        source_record_id=f"src-{index:03d}",
        record_type=record_type,
        effective_at=BASE,
        environment="DEMO",
        payload={},
        record_fingerprint="f" * 64,
    )


def software_readonly_records() -> tuple[RecordProjection, ...]:
    return (
        record(1, "SCHEDULER_CYCLE"),
        record(2, "DEMO_CAMPAIGN_STARTED"),
        record(3, "PAPER_PORTFOLIO_EVENT"),
        record(4, "MARKET_CONTEXT"),
        record(5, "ROUTER_DECISION"),
        record(6, "OPPORTUNITY_SCORED"),
        record(7, "PORTFOLIO_BATCH_EVALUATED"),
    )


def full_lifecycle_records() -> tuple[RecordProjection, ...]:
    return software_readonly_records() + (
        record(10, "OPPORTUNITY_RISK_SUBMITTED"),
        record(11, "RISK_DECISION"),
        record(12, "EXECUTION_REQUEST"),
        record(13, "EXECUTION_RECONCILIATION"),
        record(14, "PAPER_FILL"),
        record(15, "POSITION_MONITOR_SNAPSHOT"),
        record(16, "CLOSE_REQUEST"),
        record(17, "CLOSE_RECONCILIATION"),
        record(18, "PAPER_CLOSED_TRADE"),
    )


def test_empty_journal_is_partially_certified_not_failed() -> None:
    status = build_certification_status(())
    assert status["verdict"] == "PARTIALLY_CERTIFIED"
    assert status["authority"] == "READ_ONLY"
    assert status["software_readonly_complete"] is False


def test_software_readonly_records_complete_that_group() -> None:
    outcome = certification_outcome(software_readonly_records())
    assert outcome.verdict.value == "PARTIALLY_CERTIFIED"
    assert outcome.software_readonly_complete is True
    assert outcome.natural_trade_complete is False


def test_compound_context_item_requires_all_of_its_records() -> None:
    missing_portfolio = tuple(
        item
        for item in software_readonly_records()
        if item.record_type != "PORTFOLIO_BATCH_EVALUATED"
    )
    observations = collect_certification_evidence(missing_portfolio)
    context = next(
        obs for obs in observations if obs.item.value == "CONTEXT_ROUTING_SCORING_PORTFOLIO"
    )
    assert context.observed is False


def test_restart_checkpoints_are_never_inferred_from_records() -> None:
    # Even with a complete trade lifecycle, the two restart items stay pending
    # because they require an explicit operator-recorded checkpoint.
    status = build_certification_status(full_lifecycle_records())
    assert "RESTART_WITH_ACTIVE_POSITION" in status["pending_items"]
    assert "FINAL_RESTART_NO_DUPLICATE_MUTATION" in status["pending_items"]
    # Not CERTIFIED precisely because those two are unobserved.
    assert status["verdict"] == "PARTIALLY_CERTIFIED"


def test_unresolved_halt_is_surfaced_as_a_defect_and_fails() -> None:
    records = software_readonly_records() + (record(30, "DEMO_CAMPAIGN_HALTED"),)
    status = build_certification_status(records)
    assert status["verdict"] == "FAILED"
    categories = {defect["category"] for defect in status["defects"]}
    assert "SAFETY" in categories


def test_execution_failure_is_a_reconciliation_defect() -> None:
    records = software_readonly_records() + (record(31, "EXECUTION_FAILURE"),)
    status = build_certification_status(records)
    assert status["verdict"] == "FAILED"
    categories = {defect["category"] for defect in status["defects"]}
    assert "RECONCILIATION" in categories


def test_status_is_deterministic() -> None:
    a = build_certification_status(software_readonly_records())
    b = build_certification_status(tuple(reversed(software_readonly_records())))
    assert a["outcome_id"] == b["outcome_id"]
