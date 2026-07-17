"""Bounded query construction for monitoring views."""

from datetime import datetime

from trading_desk.journal.models import JournalQuery, JournalRecordType


def bounded_query(
    *,
    limit: int,
    offset: int,
    maximum: int,
    cutoff_at: datetime | None = None,
    record_type: JournalRecordType | None = None,
    source_record_id: str | None = None,
) -> JournalQuery:
    if limit > maximum:
        raise ValueError("query limit exceeds Operations Center maximum")
    return JournalQuery(
        limit=limit,
        offset=offset,
        cutoff_at=cutoff_at,
        record_type=record_type,
        source_record_id=source_record_id,
    )
