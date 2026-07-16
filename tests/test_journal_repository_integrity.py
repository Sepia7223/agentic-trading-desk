from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from journal_helpers import NOW, append_record, configuration, days
from trading_desk.journal.errors import (
    JournalDuplicateError,
    JournalIntegrityError,
    JournalParentMissingError,
    JournalReadOnlyRecoveryError,
)
from trading_desk.journal.models import IntegrityStatus, JournalQuery, JournalRecordType
from trading_desk.journal.sqlite import SQLiteJournalRepository
from trading_desk.journal.writer import DurableJournalWriter, JournalSource


def _disable_record_guards(repository: SQLiteJournalRepository) -> None:
    repository.connection.execute("DROP TRIGGER journal_records_no_update")
    repository.connection.execute("DROP TRIGGER journal_records_no_delete")


def test_append_and_deterministic_readback(tmp_path: Path) -> None:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        written = append_record(repository, "signal-1")
        assert repository.get(written.journal_record_id) == written
        assert repository.get_by_source_id("signal-1") == (written,)


def test_append_batch_is_atomic_and_chained(tmp_path: Path) -> None:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        records = DurableJournalWriter(repository).append_sources(
            (
                JournalSource(
                    record_type=JournalRecordType.STRATEGY_SIGNAL,
                    source_record_id="signal-1",
                    payload={"action": "LONG_CANDIDATE"},
                    created_at=NOW,
                ),
                JournalSource(
                    record_type=JournalRecordType.RISK_DECISION,
                    source_record_id="risk-1",
                    source_parent_ids=("signal-1",),
                    payload={"status": "REJECTED"},
                    created_at=NOW,
                ),
            )
        )
        assert len(records) == 2
        assert records[1].previous_record_fingerprint == records[0].journal_record_fingerprint
        assert records[0].atomic_group_id == records[1].atomic_group_id
        assert records[0].atomic_group_size == 2
        assert repository.verify().status is IntegrityStatus.VALID


def test_duplicate_source_identity_is_rejected(tmp_path: Path) -> None:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        append_record(repository, "signal-1")
        with pytest.raises(JournalDuplicateError):
            append_record(repository, "signal-1", payload={"action": "WATCH"})


def test_missing_required_parent_is_rejected(tmp_path: Path) -> None:
    with (
        SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository,
        pytest.raises(JournalParentMissingError),
    ):
        append_record(
            repository,
            "trade-1",
            record_type=JournalRecordType.PAPER_CLOSED_TRADE,
            parents=("missing",),
        )


def test_parent_required_type_rejects_empty_parents(tmp_path: Path) -> None:
    with (
        SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository,
        pytest.raises(JournalParentMissingError),
    ):
        append_record(repository, "fill-1", record_type=JournalRecordType.PAPER_FILL)


def test_deferred_linkage_is_explicit_and_later_resolved(tmp_path: Path) -> None:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        append_record(
            repository,
            "confirmation-1",
            record_type=JournalRecordType.BROKER_CONFIRMATION,
            parents=("request-1",),
            deferred=True,
        )
        row = repository.connection.execute("SELECT deferred FROM journal_parent_links").fetchone()
        assert row[0] == 1
        append_record(repository, "signal-1")
        append_record(
            repository,
            "request-1",
            record_type=JournalRecordType.EXECUTION_REQUEST,
            parents=("signal-1",),
        )
        row = repository.connection.execute("SELECT deferred FROM journal_parent_links").fetchone()
        assert row[0] == 0


def test_deferred_linkage_is_rejected_for_non_permitted_type(tmp_path: Path) -> None:
    with (
        SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository,
        pytest.raises(JournalParentMissingError),
    ):
        append_record(
            repository,
            "fill-1",
            record_type=JournalRecordType.PAPER_FILL,
            parents=("position-1",),
            deferred=True,
        )


def test_batch_failure_rolls_back_all_records(tmp_path: Path) -> None:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        writer = DurableJournalWriter(repository)
        with pytest.raises(JournalDuplicateError):
            writer.append_sources(
                tuple(
                    JournalSource(
                        record_type=JournalRecordType.STRATEGY_SIGNAL,
                        source_record_id="duplicate",
                        payload={"index": index},
                        created_at=NOW,
                    )
                    for index in range(2)
                )
            )
        assert repository.query(JournalQuery()).total_matches == 0


def test_restart_preserves_records_chain_and_lineage(tmp_path: Path) -> None:
    path = tmp_path / "journal.db"
    with SQLiteJournalRepository(configuration(path)) as repository:
        append_record(repository, "signal-1")
        append_record(
            repository,
            "risk-1",
            record_type=JournalRecordType.RISK_DECISION,
            parents=("signal-1",),
        )
    with SQLiteJournalRepository(configuration(path)) as repository:
        assert repository.verify().status is IntegrityStatus.VALID
        assert [item.source_record_id for item in repository.lineage("risk-1").records] == [
            "signal-1",
            "risk-1",
        ]


def test_query_order_pagination_and_date_bounds(tmp_path: Path) -> None:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        for index in range(4):
            append_record(repository, f"signal-{index}", at=days(index))
        query = JournalQuery(start_at=days(1), end_at=days(3), limit=2, offset=0)
        first = repository.query(query)
        assert [item.source_record_id for item in first.records] == ["signal-1", "signal-2"]
        assert first.total_matches == 3
        assert first.next_offset == 2


def test_query_cutoff_prevents_future_record_leakage(tmp_path: Path) -> None:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        append_record(repository, "past", at=days(0))
        append_record(repository, "future", at=days(2))
        result = repository.query(JournalQuery(cutoff_at=days(1)))
        assert [item.source_record_id for item in result.records] == ["past"]


def test_query_limit_is_bounded_by_configuration(tmp_path: Path) -> None:
    config = configuration(tmp_path / "journal.db", maximum_query_records=2)
    with (
        SQLiteJournalRepository(config) as repository,
        pytest.raises(ValueError, match="configured maximum"),
    ):
        repository.query(JournalQuery(limit=3))


def test_broken_chain_is_reported_as_invalid(tmp_path: Path) -> None:
    with SQLiteJournalRepository(
        configuration(tmp_path / "journal.db", verify_integrity_on_startup=False)
    ) as repository:
        record = append_record(repository, "signal-1")
        _disable_record_guards(repository)
        repository.connection.execute(
            "UPDATE journal_records SET previous_record_fingerprint = ? "
            "WHERE journal_record_id = ?",
            ("f" * 64, record.journal_record_id),
        )
        report = repository.verify()
        assert report.status is IntegrityStatus.INVALID
        assert "BROKEN_CHAIN" in {item.code for item in report.findings}


def test_altered_payload_and_source_fingerprint_are_reported(tmp_path: Path) -> None:
    with SQLiteJournalRepository(
        configuration(tmp_path / "journal.db", verify_integrity_on_startup=False)
    ) as repository:
        record = append_record(repository, "signal-1")
        _disable_record_guards(repository)
        repository.connection.execute(
            "UPDATE journal_records SET payload_json = ? WHERE journal_record_id = ?",
            ('{"action":"WATCH"}', record.journal_record_id),
        )
        codes = {item.code for item in repository.verify().findings}
        assert {"PAYLOAD_MISMATCH", "SOURCE_MISMATCH"}.issubset(codes)


def test_incomplete_atomic_group_is_reported(tmp_path: Path) -> None:
    with SQLiteJournalRepository(
        configuration(tmp_path / "journal.db", verify_integrity_on_startup=False)
    ) as repository:
        records = DurableJournalWriter(repository).append_sources(
            tuple(
                JournalSource(
                    record_type=JournalRecordType.STRATEGY_SIGNAL,
                    source_record_id=f"signal-{index}",
                    payload={"index": index},
                    created_at=NOW,
                )
                for index in range(2)
            )
        )
        _disable_record_guards(repository)
        repository.connection.execute(
            "DELETE FROM journal_records WHERE journal_record_id = ?",
            (records[1].journal_record_id,),
        )
        assert "INCOMPLETE_ATOMIC_GROUP" in {item.code for item in repository.verify().findings}


def test_non_monotonic_manual_record_is_rejected(tmp_path: Path) -> None:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        record = append_record(repository, "signal-1")
        with pytest.raises(JournalIntegrityError):
            repository.append(record.model_copy(update={"sequence_number": 3}))


def test_startup_integrity_failure_enters_recovery_read_only_mode(tmp_path: Path) -> None:
    path = tmp_path / "journal.db"
    with SQLiteJournalRepository(
        configuration(path, verify_integrity_on_startup=False)
    ) as repository:
        record = append_record(repository, "signal-1")
        _disable_record_guards(repository)
        repository.connection.execute(
            "UPDATE journal_records SET payload_json = ? WHERE journal_record_id = ?",
            ('{"action":"ALTERED"}', record.journal_record_id),
        )
    recovered = SQLiteJournalRepository(configuration(path))
    try:
        assert recovered.recovery_read_only
        with pytest.raises(JournalReadOnlyRecoveryError):
            append_record(recovered, "signal-2")
    finally:
        recovered.close()


def test_sqlite_guards_reject_record_updates_and_deletes(tmp_path: Path) -> None:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        record = append_record(repository, "signal-1")
        with pytest.raises(Exception, match="append-only"):
            repository.connection.execute(
                "UPDATE journal_records SET payload_json = '{}' WHERE journal_record_id = ?",
                (record.journal_record_id,),
            )
        with pytest.raises(Exception, match="append-only"):
            repository.connection.execute(
                "DELETE FROM journal_records WHERE journal_record_id = ?",
                (record.journal_record_id,),
            )


def test_tail_truncation_is_detected_by_chain_anchor(tmp_path: Path) -> None:
    with SQLiteJournalRepository(
        configuration(tmp_path / "journal.db", verify_integrity_on_startup=False)
    ) as repository:
        append_record(repository, "signal-1")
        second = append_record(repository, "signal-2")
        _disable_record_guards(repository)
        repository.connection.execute(
            "DELETE FROM journal_records WHERE journal_record_id = ?",
            (second.journal_record_id,),
        )
        codes = {finding.code for finding in repository.verify().findings}
        assert "RECORD_COUNT_ANCHOR_MISMATCH" in codes
        assert "CHAIN_HEAD_ANCHOR_MISMATCH" in codes


def test_non_mapping_source_uses_wrapped_payload_fingerprint(tmp_path: Path) -> None:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        DurableJournalWriter(repository).append_source(
            record_type=JournalRecordType.STRATEGY_SIGNAL,
            source_record_id="primitive-1",
            source="NO_TRADE",
            created_at=NOW,
        )
        assert repository.verify().status is IntegrityStatus.VALID


def test_utc_timestamps_are_required(tmp_path: Path) -> None:
    with (
        SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository,
        pytest.raises(ValueError, match="timezone-aware UTC"),
    ):
        append_record(repository, "signal-1", at=datetime(2025, 1, 1))
