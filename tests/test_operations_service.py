from datetime import datetime, timedelta
from pathlib import Path

from journal_helpers import NOW, append_record, configuration
from trading_desk.journal.models import JournalRecordType
from trading_desk.journal.reader import ReadOnlyJournal
from trading_desk.journal.sqlite import SQLiteJournalRepository
from trading_desk.operations.config import OperationsConfiguration
from trading_desk.operations.projections import project_record, safe_reference
from trading_desk.operations.service import OperationsService


def test_latest_returns_newest_record_and_snapshot_is_deterministic(tmp_path: Path) -> None:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        append_record(repository, "old-signal", at=NOW)
        append_record(repository, "new-signal", at=NOW + timedelta(minutes=1))
        service = OperationsService(ReadOnlyJournal(repository), OperationsConfiguration())
        assert service.latest(JournalRecordType.STRATEGY_SIGNAL).source_record_id == "new-signal"  # type: ignore[union-attr]
        first = service.snapshot(NOW + timedelta(minutes=2))
        second = service.snapshot(NOW + timedelta(minutes=2))
        assert first == second
        assert first.snapshot_id == first.snapshot_fingerprint
        assert first.environment == "IG DEMO"


def test_projection_removes_secret_fields_and_local_paths(tmp_path: Path) -> None:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        record = append_record(
            repository,
            "safe-signal",
            payload={"action": "NO_TRADE"},
        )
        unsafe_transport_record = record.model_copy(
            update={
                "payload": {
                    "action": "NO_TRADE",
                    "api_key": "do-not-expose",
                    "nested": {"authorization": "do-not-expose"},
                    "path": "C:/Users/example/private.db",
                }
            }
        )
        projected = project_record(unsafe_transport_record)
        assert "do-not-expose" not in projected.model_dump_json()
        assert "api_key" not in projected.payload
        assert projected.payload["path"] == "[REDACTED]"
        assert safe_reference("ABCDEF1234") == "***1234"


def test_why_no_trade_preserves_deterministic_reason_order(tmp_path: Path) -> None:
    payload = {
        "action": "WATCH",
        "rejection_reasons": ["MOMENTUM_THRESHOLD", "REBOUND_MISSING"],
        "mandatory_gates": [
            {"name": "SPREAD_ACCEPTABLE", "passed": True},
            {"name": "MOMENTUM", "passed": False},
        ],
    }
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        append_record(repository, "watch-signal", payload=payload)
        service = OperationsService(ReadOnlyJournal(repository), OperationsConfiguration())
        result = service.why_no_trade()
        assert result[0].primary_reason == "MOMENTUM_THRESHOLD"
        assert result[0].secondary_reasons == ("REBOUND_MISSING",)
        assert result[0].passed_gates == ("SPREAD_ACCEPTABLE",)
        assert result[0].failed_gates == ("MOMENTUM",)
        assert result[0].final_action == "NO ORDER"


def test_replay_uses_strict_cutoff_and_stable_ordering(tmp_path: Path) -> None:
    cutoff = NOW + timedelta(minutes=1)
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        append_record(repository, "before", at=NOW)
        append_record(repository, "future", at=cutoff + timedelta(minutes=1))
        service = OperationsService(ReadOnlyJournal(repository), OperationsConfiguration())
        replay = service.replay(cutoff_at=cutoff)
        assert tuple(item.source_record_id for item in replay.events) == ("before",)
        assert replay.replay_mode == "REPLAY MODE - NO OPERATIONAL AUTHORITY"


def test_search_is_bounded_and_performance_is_authoritative_empty_state(tmp_path: Path) -> None:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        append_record(repository, "eur-signal")
        service = OperationsService(ReadOnlyJournal(repository), OperationsConfiguration())
        assert service.search("EUR/USD").total_matches == 1
        summary = service.performance()
        assert summary.sample_size == 0
        assert summary.realized_pnl == 0


def test_configuration_view_sanitizes_caller_supplied_metadata(tmp_path: Path) -> None:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        service = OperationsService(
            ReadOnlyJournal(repository),
            OperationsConfiguration(),
            safe_configurations={
                "strategy": {"version": "1"},
                "provider_api_key": "must-not-appear",
                "database_path": "C:/Users/example/private.db",
            },
        )
        serialized = str(service.configuration_view())
        assert "must-not-appear" not in serialized
        assert "provider_api_key" not in serialized
        assert "C:/Users" not in serialized


def test_naive_operations_timestamps_are_rejected(tmp_path: Path) -> None:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        service = OperationsService(ReadOnlyJournal(repository), OperationsConfiguration())
        try:
            service.snapshot(datetime(2026, 1, 1))
        except ValueError as error:
            assert "timezone-aware" in str(error)
        else:
            raise AssertionError("naive timestamp was accepted")
