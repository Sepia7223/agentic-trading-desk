"""Storage-neutral ports for append-only journal evidence."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from trading_desk.journal.models import (
    IntegrityReport,
    JournalLineage,
    JournalQuery,
    JournalQueryResult,
    JournalRecord,
)


class JournalWriter(Protocol):
    def append(self, record: JournalRecord) -> JournalRecord: ...

    def append_batch(self, records: Sequence[JournalRecord]) -> tuple[JournalRecord, ...]: ...


class JournalReader(Protocol):
    def get(self, journal_record_id: str) -> JournalRecord | None: ...

    def query(self, query: JournalQuery) -> JournalQueryResult: ...

    def lineage(self, source_record_id: str) -> JournalLineage: ...


class JournalIntegrityVerifier(Protocol):
    def verify(self) -> IntegrityReport: ...


class TradeJournal(JournalWriter, JournalReader, JournalIntegrityVerifier, Protocol):
    """Combined compatibility boundary for a durable journal repository."""
