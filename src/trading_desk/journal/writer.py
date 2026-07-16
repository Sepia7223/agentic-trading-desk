"""Envelope writer that wraps existing immutable source records."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from trading_desk.journal.fingerprints import fingerprint
from trading_desk.journal.models import JournalRecord, JournalRecordType, create_journal_record
from trading_desk.journal.sqlite import SQLiteJournalRepository


class DurableJournalWriter:
    def __init__(self, repository: SQLiteJournalRepository) -> None:
        self.repository = repository

    def append_source(
        self,
        *,
        record_type: JournalRecordType,
        source_record_id: str,
        source: object,
        created_at: datetime,
        effective_at: datetime | None = None,
        source_parent_ids: tuple[str, ...] = (),
        instrument: str | None = None,
        epic: str | None = None,
        strategy_variant: str | None = None,
        environment: str = "LOCAL",
        deferred_linkage: bool = False,
    ) -> JournalRecord:
        record = create_journal_record(
            sequence_number=self.repository.next_sequence(),
            record_type=record_type,
            source_record_id=source_record_id,
            source=source,
            source_parent_ids=source_parent_ids,
            created_at=created_at,
            effective_at=effective_at or created_at,
            previous_record_fingerprint=self.repository.latest_fingerprint(),
            schema_version=self.repository.schema_version,
            instrument=instrument,
            epic=epic,
            strategy_variant=strategy_variant,
            environment=environment,
            deferred_linkage=deferred_linkage,
        )
        return self.repository.append(record)

    def append_sources(self, sources: Sequence[JournalSource]) -> tuple[JournalRecord, ...]:
        sequence = self.repository.next_sequence()
        previous = self.repository.latest_fingerprint()
        records: list[JournalRecord] = []
        group_id = (
            fingerprint(
                {
                    "source_ids": tuple(source.source_record_id for source in sources),
                    "created_at": tuple(source.created_at for source in sources),
                }
            )
            if len(sources) > 1
            else None
        )
        for group_index, source in enumerate(sources, start=1):
            record = create_journal_record(
                sequence_number=sequence,
                record_type=source.record_type,
                source_record_id=source.source_record_id,
                source=source.payload,
                source_parent_ids=source.source_parent_ids,
                created_at=source.created_at,
                effective_at=source.effective_at or source.created_at,
                previous_record_fingerprint=previous,
                schema_version=self.repository.schema_version,
                instrument=source.instrument,
                epic=source.epic,
                strategy_variant=source.strategy_variant,
                environment=source.environment,
                deferred_linkage=source.deferred_linkage,
                atomic_group_id=group_id,
                atomic_group_index=group_index if group_id else None,
                atomic_group_size=len(sources) if group_id else None,
            )
            records.append(record)
            sequence += 1
            previous = record.journal_record_fingerprint
        return self.repository.append_batch(records)


class JournalSource(BaseModel):
    """Immutable source-to-envelope write request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_type: JournalRecordType
    source_record_id: str
    payload: object
    created_at: datetime
    effective_at: datetime | None = None
    source_parent_ids: tuple[str, ...] = ()
    instrument: str | None = None
    epic: str | None = None
    strategy_variant: str | None = None
    environment: str = "LOCAL"
    deferred_linkage: bool = False
