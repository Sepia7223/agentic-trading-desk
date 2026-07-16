"""Query construction helpers with explicit UTC cutoff enforcement."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from trading_desk.journal.models import JournalQuery, JournalQueryResult

if TYPE_CHECKING:
    from trading_desk.ports.journal import JournalReader


class JournalQueryService:
    def __init__(self, reader: JournalReader) -> None:
        self._reader = reader

    def query(self, query: JournalQuery, *, as_of: datetime) -> JournalQueryResult:
        if as_of.tzinfo is None or as_of.utcoffset() != UTC.utcoffset(as_of):
            raise ValueError("journal query cutoff must be timezone-aware UTC")
        cutoff = min(item for item in (query.cutoff_at, as_of) if item is not None)
        return self._reader.query(query.model_copy(update={"cutoff_at": cutoff}))
