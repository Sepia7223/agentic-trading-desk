"""Read-only facade suitable for human review and AI retrieval."""

from __future__ import annotations

from typing import TYPE_CHECKING

from trading_desk.journal.models import (
    JournalLineage,
    JournalQuery,
    JournalQueryResult,
    JournalRecord,
)

if TYPE_CHECKING:
    from trading_desk.ports.journal import JournalReader


class ReadOnlyJournal:
    def __init__(self, reader: JournalReader) -> None:
        self._reader = reader

    def get(self, journal_record_id: str) -> JournalRecord | None:
        return self._reader.get(journal_record_id)

    def query(self, query: JournalQuery) -> JournalQueryResult:
        return self._reader.query(query)

    def lineage(self, source_record_id: str) -> JournalLineage:
        return self._reader.lineage(source_record_id)
