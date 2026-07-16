from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from trading_desk.journal.config import JournalConfiguration
from trading_desk.journal.models import JournalRecord, JournalRecordType
from trading_desk.journal.sqlite import SQLiteJournalRepository
from trading_desk.journal.writer import DurableJournalWriter

NOW = datetime(2025, 1, 15, 12, tzinfo=UTC)


def configuration(path: Path, **updates: object) -> JournalConfiguration:
    values: dict[str, object] = {"database_path": path}
    values.update(updates)
    return JournalConfiguration.model_validate(values)


def append_record(
    repository: SQLiteJournalRepository,
    source_id: str,
    *,
    record_type: JournalRecordType = JournalRecordType.STRATEGY_SIGNAL,
    parents: tuple[str, ...] = (),
    payload: dict[str, object] | None = None,
    at: datetime = NOW,
    deferred: bool = False,
) -> JournalRecord:
    return DurableJournalWriter(repository).append_source(
        record_type=record_type,
        source_record_id=source_id,
        source=payload or {"signal_id": source_id, "action": "NO_TRADE"},
        source_parent_ids=parents,
        created_at=at,
        effective_at=at,
        instrument="EUR/USD",
        epic="CS.D.EURUSD.CFD.IP",
        strategy_variant="BASELINE_KALMAN_HMM",
        environment="DEMO",
        deferred_linkage=deferred,
    )


def days(value: int) -> datetime:
    return NOW + timedelta(days=value)
