from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from journal_helpers import NOW, append_record, configuration, days
from trading_desk.journal.amendments import AmendmentService
from trading_desk.journal.models import (
    AmendmentReasonCode,
    FinancialOutcome,
    JournalRecordType,
    PaperDemoComparisonInput,
    PostTradeReviewInput,
    ProcessClassification,
)
from trading_desk.journal.reviews import compare_paper_and_demo, generate_post_trade_review
from trading_desk.journal.sqlite import SQLiteJournalRepository
from trading_desk.journal.summaries import daily_review, monthly_review, weekly_review


def _trade(**updates: object) -> PostTradeReviewInput:
    values: dict[str, object] = {
        "trade_id": "trade-1",
        "instrument": "EUR/USD",
        "epic": "CS.D.EURUSD.CFD.IP",
        "strategy_variant": "BASELINE",
        "entry_timestamp": NOW,
        "exit_timestamp": days(1),
        "quantity": Decimal("2"),
        "entry_price": Decimal("100"),
        "exit_price": Decimal("110"),
        "gross_pnl": Decimal("20"),
        "commission": Decimal("2"),
        "funding": Decimal("1"),
        "spread_cost": Decimal("1"),
        "slippage_cost": Decimal("1"),
        "initial_risk_amount": Decimal("10"),
        "maximum_favorable_excursion": Decimal("25"),
        "maximum_adverse_excursion": Decimal("4"),
    }
    values.update(updates)
    return PostTradeReviewInput.model_validate(values)


def test_valid_amendment_preserves_original(tmp_path: Path) -> None:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        original = append_record(repository, "signal-1")
        amendment = AmendmentService(repository).append(
            target_journal_record_id=original.journal_record_id,
            created_at=NOW,
            reason_code=AmendmentReasonCode.HUMAN_NOTE_ADDED,
            reason="Reviewed by operator",
            corrected_fields={"note": "market holiday"},
            created_by="operator",
        )
        assert repository.get(original.journal_record_id) == original
        assert amendment.record_type is JournalRecordType.AMENDMENT
        assert len(repository.lineage("signal-1").records) == 2


def test_amendment_requires_existing_target(tmp_path: Path) -> None:
    with (
        SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository,
        pytest.raises(Exception, match="target does not exist"),
    ):
        AmendmentService(repository).append(
            target_journal_record_id="f" * 64,
            created_at=NOW,
            reason_code=AmendmentReasonCode.OTHER,
            reason="correction",
            corrected_fields={"note": "value"},
            created_by="operator",
        )


def test_realized_fact_amendment_requires_approval_evidence(tmp_path: Path) -> None:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        original = append_record(repository, "trade-1")
        with pytest.raises(ValueError, match="approval reference"):
            AmendmentService(repository).append(
                target_journal_record_id=original.journal_record_id,
                created_at=NOW,
                reason_code=AmendmentReasonCode.DATA_CORRECTION,
                reason="correction",
                corrected_fields={"net_pnl": Decimal("10")},
                created_by="operator",
            )


def test_amendment_fingerprint_is_deterministic(tmp_path: Path) -> None:
    paths = (tmp_path / "one.db", tmp_path / "two.db")
    fingerprints = []
    for path in paths:
        with SQLiteJournalRepository(configuration(path)) as repository:
            original = append_record(repository, "signal-1")
            record = AmendmentService(repository).append(
                target_journal_record_id=original.journal_record_id,
                created_at=NOW,
                reason_code=AmendmentReasonCode.HUMAN_NOTE_ADDED,
                reason="same",
                corrected_fields={"note": "same"},
                created_by="operator",
            )
            fingerprints.append(record.source_fingerprint)
    assert fingerprints[0] == fingerprints[1]


def test_winning_valid_process_trade_review() -> None:
    review = generate_post_trade_review(_trade())
    assert review.process_classification is ProcessClassification.VALID_PROCESS
    assert review.financial_outcome is FinancialOutcome.WIN
    assert review.total_costs == Decimal("5")
    assert review.net_pnl == Decimal("15")
    assert review.risk_multiple == Decimal("1.5")
    assert review.holding_period_seconds == 86400


def test_losing_trade_can_still_be_valid_process() -> None:
    review = generate_post_trade_review(_trade(gross_pnl=Decimal("-5")))
    assert review.process_classification is ProcessClassification.VALID_PROCESS
    assert review.financial_outcome is FinancialOutcome.LOSS


def test_profitable_rule_violation_is_bad_process() -> None:
    review = generate_post_trade_review(_trade(rule_violation=True))
    assert review.financial_outcome is FinancialOutcome.WIN
    assert review.process_classification is ProcessClassification.RULE_VIOLATION


@pytest.mark.parametrize(
    ("update", "expected"),
    (
        ({"execution_error": True}, ProcessClassification.EXECUTION_ERROR),
        ({"data_error": True}, ProcessClassification.DATA_ERROR),
        ({"risk_error": True}, ProcessClassification.RISK_ERROR),
        ({"reconciliation_error": True}, ProcessClassification.RECONCILIATION_ERROR),
        ({"unresolved": True, "exit_timestamp": None}, ProcessClassification.UNRESOLVED),
    ),
)
def test_process_classifications(
    update: dict[str, object], expected: ProcessClassification
) -> None:
    assert generate_post_trade_review(_trade(**update)).process_classification is expected


def test_missing_optional_trade_data_is_preserved() -> None:
    review = generate_post_trade_review(
        _trade(gross_pnl=None, initial_risk_amount=None, exit_timestamp=None)
    )
    assert review.net_pnl is None
    assert review.risk_multiple is None
    assert review.financial_outcome is FinancialOutcome.UNREALIZED


def test_paper_demo_comparison_preserves_separate_values() -> None:
    comparison = compare_paper_and_demo(
        PaperDemoComparisonInput(
            comparison_id="comparison-1",
            paper_trade_id="paper-1",
            demo_trade_id="demo-1",
            paper_entry_price=Decimal("100"),
            demo_entry_price=Decimal("101"),
            paper_exit_price=Decimal("110"),
            demo_exit_price=Decimal("109"),
            paper_quantity=Decimal("2"),
            demo_quantity=Decimal("1.5"),
            paper_entry_timestamp=NOW,
            demo_entry_timestamp=NOW.replace(minute=1),
            paper_costs=Decimal("1"),
            demo_costs=Decimal("2"),
            paper_pnl=Decimal("20"),
            demo_pnl=Decimal("12"),
            paper_stop=Decimal("95"),
            demo_stop=Decimal("95.5"),
        )
    )
    assert comparison.entry_slippage_difference == Decimal("1")
    assert comparison.exit_slippage_difference == Decimal("-1")
    assert comparison.quantity_difference == Decimal("-0.5")
    assert comparison.timing_difference_seconds == 60
    assert comparison.pnl_difference == Decimal("-8")


def test_daily_review_uses_strict_utc_day_boundary(tmp_path: Path) -> None:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        append_record(repository, "inside", at=NOW)
        append_record(repository, "outside", at=days(1))
        review = daily_review(repository, date(2025, 1, 15))
        assert review.sample_size == 1
        assert review.period_start == datetime(2025, 1, 15, tzinfo=UTC)


def test_empty_daily_review_is_deterministic(tmp_path: Path) -> None:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        left = daily_review(repository, date(2025, 1, 15))
        right = daily_review(repository, date(2025, 1, 15))
        assert left == right
        assert left.sample_size == 0
        assert left.insufficient_sample


def test_weekly_and_monthly_reviews_exclude_future_records(tmp_path: Path) -> None:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        append_record(repository, "january", at=NOW)
        append_record(repository, "february", at=datetime(2025, 2, 1, tzinfo=UTC))
        assert weekly_review(repository, 2025, 3).sample_size == 1
        assert monthly_review(repository, 2025, 1).sample_size == 1


def test_periodic_review_calculates_bounded_performance_metrics(tmp_path: Path) -> None:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        append_record(repository, "trade-parent")
        append_record(
            repository,
            "review-win",
            record_type=JournalRecordType.POST_TRADE_REVIEW,
            parents=("trade-parent",),
            payload={
                "net_pnl": Decimal("10"),
                "holding_period_seconds": 100,
                "financial_outcome": "WIN",
            },
        )
        append_record(
            repository,
            "review-loss",
            record_type=JournalRecordType.POST_TRADE_REVIEW,
            parents=("trade-parent",),
            payload={
                "net_pnl": Decimal("-5"),
                "holding_period_seconds": 300,
                "financial_outcome": "LOSS",
            },
        )
        review = daily_review(repository, NOW.date())
        assert review.metrics["win_rate"] == Decimal("0.5")
        assert review.metrics["payoff_ratio"] == Decimal("2")
        assert review.metrics["profit_factor"] == Decimal("2")
        assert review.metrics["average_holding_period_seconds"] == Decimal("200")
        assert review.metrics["statistical_strength"] == "INSUFFICIENT"
