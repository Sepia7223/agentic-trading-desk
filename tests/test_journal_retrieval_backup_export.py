from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from journal_helpers import NOW, append_record, configuration, days
from trading_desk.journal.backups import create_backup, verify_backup
from trading_desk.journal.exports import export_records
from trading_desk.journal.models import (
    ExportFormat,
    FinancialOutcome,
    JournalQuery,
    JournalRecordType,
    ProcessClassification,
    SimilarityFeatures,
)
from trading_desk.journal.queries import JournalQueryService
from trading_desk.journal.reader import ReadOnlyJournal
from trading_desk.journal.similarity import extract_similarity_features, nearest_records
from trading_desk.journal.sqlite import SQLiteJournalRepository


def test_payload_filters_and_query_fingerprint(tmp_path: Path) -> None:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        append_record(repository, "signal-1")
        append_record(
            repository,
            "risk-1",
            record_type=JournalRecordType.RISK_DECISION,
            parents=("signal-1",),
            payload={
                "candidate_id": "candidate-1",
                "decision_id": "risk-1",
                "status": "REJECTED",
                "reason_codes": ["SPREAD_TOO_WIDE"],
            },
        )
        query = JournalQuery(
            candidate_id="candidate-1",
            risk_status="REJECTED",
            risk_reason_code="SPREAD_TOO_WIDE",
        )
        result = repository.query(query)
        assert result.total_matches == 1
        assert result.query_fingerprint == query.query_fingerprint


def test_read_only_facade_exposes_no_append_or_delete(tmp_path: Path) -> None:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        reader = ReadOnlyJournal(repository)
        assert not hasattr(reader, "append")
        assert not hasattr(reader, "delete")


def test_query_service_enforces_as_of_cutoff(tmp_path: Path) -> None:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        append_record(repository, "past", at=NOW)
        append_record(repository, "future", at=days(2))
        result = JournalQueryService(repository).query(JournalQuery(), as_of=days(1))
        assert [item.source_record_id for item in result.records] == ["past"]


def _features(source_id: str, value: str, *, at: datetime = NOW) -> SimilarityFeatures:
    return SimilarityFeatures(
        source_record_id=source_id,
        timestamp=at,
        instrument="EUR/USD",
        strategy_variant="BASELINE",
        entry_regime="BULL_LOW_VOL",
        kalman_slope=Decimal(value),
        volatility=Decimal(value),
        spread_bps=Decimal(value),
        holding_period_seconds=100,
        process_classification=ProcessClassification.VALID_PROCESS,
        financial_outcome=FinancialOutcome.WIN,
    )


def test_similarity_exact_match_and_deterministic_order() -> None:
    target = _features("target", "1")
    records = (_features("b", "1"), _features("a", "1"), _features("far", "9"))
    matches = nearest_records(target, records, cutoff=NOW, limit=3)
    assert [item.source_record_id for item in matches[:2]] == ["a", "b"]
    assert matches[0].distance == 0


def test_similarity_numeric_distance_and_future_exclusion() -> None:
    target = _features("target", "1")
    records = (_features("near", "2"), _features("far", "8"), _features("future", "1", at=days(1)))
    matches = nearest_records(target, records, cutoff=NOW)
    assert [item.source_record_id for item in matches] == ["near", "far"]


def test_similarity_handles_missing_features_without_mutation() -> None:
    target = _features("target", "1")
    missing = SimilarityFeatures(
        source_record_id="missing",
        timestamp=NOW,
        instrument="EUR/USD",
        strategy_variant=None,
        entry_regime=None,
    )
    before = missing.model_dump()
    assert nearest_records(target, (missing,), cutoff=NOW)[0].source_record_id == "missing"
    assert missing.model_dump() == before


def test_similarity_feature_extraction_is_deterministic(tmp_path: Path) -> None:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        append_record(repository, "trade-1")
        record = append_record(
            repository,
            "review-1",
            record_type=JournalRecordType.POST_TRADE_REVIEW,
            parents=("trade-1",),
            payload={
                "entry_regime": "BULL_LOW_VOL",
                "kalman_slope": Decimal("0.4"),
                "spread_bps": Decimal("1.2"),
                "process_classification": "VALID_PROCESS",
                "financial_outcome": "WIN",
            },
        )
        left = extract_similarity_features(record)
        right = extract_similarity_features(record)
        assert left == right
        assert left.kalman_slope == Decimal("0.4")


def test_backup_creation_checksum_and_verification(tmp_path: Path) -> None:
    database = tmp_path / "journal.db"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    with SQLiteJournalRepository(configuration(database)) as repository:
        append_record(repository, "signal-1")
        result = create_backup(repository, backup_dir)
    assert result.verified
    assert verify_backup(result.path, result.checksum)


def test_backup_retention_removes_oldest(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        append_record(repository, "signal-1")
        create_backup(repository, backup_dir, retention_count=1)
        create_backup(repository, backup_dir, retention_count=1)
    assert len(tuple(backup_dir.glob("journal-*.db"))) == 1


def test_corrupted_backup_fails_verification(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.db"
    path.write_bytes(b"not sqlite")
    assert not verify_backup(path, "0" * 64)


@pytest.mark.parametrize("export_format", tuple(ExportFormat))
def test_sanitized_bounded_exports(tmp_path: Path, export_format: ExportFormat) -> None:
    config = configuration(tmp_path / "journal.db")
    with SQLiteJournalRepository(config) as repository:
        append_record(repository, "signal-1")
        output = tmp_path / f"export.{export_format.value}"
        result = export_records(
            repository,
            config,
            JournalQuery(limit=1, cutoff_at=datetime.now(UTC)),
            output_path=output,
            export_format=export_format,
        )
        content = output.read_text(encoding="utf-8")
    assert result.source_record_count == 1
    assert result.checksum
    assert "password" not in content.lower()
    assert "access_token" not in content.lower()


def test_secret_bearing_payload_is_rejected_before_storage(tmp_path: Path) -> None:
    with (
        SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository,
        pytest.raises(ValueError, match="secret-bearing field"),
    ):
        append_record(repository, "unsafe", payload={"access_token": "redacted"})


def test_machine_path_is_rejected_from_historical_payload(tmp_path: Path) -> None:
    with (
        SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository,
        pytest.raises(ValueError, match="filesystem path"),
    ):
        append_record(repository, "unsafe", payload={"output_path": tmp_path / "local.json"})


@pytest.mark.parametrize(
    "value",
    (
        "diagnostic loaded from /etc/trading/config.json",
        "Authorization: Bearer redacted-example",
    ),
)
def test_unsafe_embedded_values_are_rejected_before_storage(tmp_path: Path, value: str) -> None:
    with (
        SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository,
        pytest.raises(ValueError, match="prohibited"),
    ):
        append_record(repository, "unsafe", payload={"diagnostic": value})


def test_csv_and_markdown_exports_neutralize_active_cells(tmp_path: Path) -> None:
    config = configuration(tmp_path / "journal.db")
    with SQLiteJournalRepository(config) as repository:
        append_record(repository, "=FORMULA|next\nrow")
        csv_path = tmp_path / "journal.csv"
        export_records(
            repository,
            config,
            JournalQuery(),
            output_path=csv_path,
            export_format=ExportFormat.CSV,
        )
        assert "'=FORMULA|next" in csv_path.read_text(encoding="utf-8")

        markdown_path = tmp_path / "journal.md"
        export_records(
            repository,
            config,
            JournalQuery(),
            output_path=markdown_path,
            export_format=ExportFormat.MARKDOWN,
        )
        markdown = markdown_path.read_text(encoding="utf-8")
        assert "=FORMULA\\|next row" in markdown


def test_raw_provider_response_is_rejected_by_default(tmp_path: Path) -> None:
    with (
        SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository,
        pytest.raises(ValueError, match="raw provider data"),
    ):
        append_record(repository, "unsafe", payload={"raw_provider_response": {"result": "x"}})


def test_full_account_identifier_is_rejected(tmp_path: Path) -> None:
    with (
        SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository,
        pytest.raises(ValueError, match="account identifier"),
    ):
        append_record(repository, "unsafe", payload={"account_id": "redacted-example"})


def test_export_requires_explicit_existing_parent(tmp_path: Path) -> None:
    config = configuration(tmp_path / "journal.db")
    with (
        SQLiteJournalRepository(config) as repository,
        pytest.raises(Exception, match="parent directory"),
    ):
        export_records(
            repository,
            config,
            JournalQuery(),
            output_path=tmp_path / "absent" / "export.jsonl",
            export_format=ExportFormat.JSONL,
        )
