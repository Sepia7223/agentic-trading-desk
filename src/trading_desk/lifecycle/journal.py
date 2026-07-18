"""Append-only hash-chained lifecycle evidence."""

from datetime import datetime
from typing import Protocol

from trading_desk.journal.models import JournalRecordType
from trading_desk.journal.writer import DurableJournalWriter
from trading_desk.lifecycle.fingerprints import fingerprint
from trading_desk.lifecycle.models import (
    DemoPositionSnapshot,
    LifecycleEventType,
    LifecycleJournalRecord,
)


class LifecycleJournal(Protocol):
    def append(
        self,
        event_type: LifecycleEventType,
        timestamp: datetime,
        payload: object,
        *,
        position_id: str,
        exit_decision_id: str | None = None,
        close_request_id: str | None = None,
        deal_id: str | None = None,
    ) -> LifecycleJournalRecord: ...


class InMemoryLifecycleJournal:
    def __init__(self, records: tuple[LifecycleJournalRecord, ...] = ()) -> None:
        previous: str | None = None
        for sequence, record in enumerate(records, start=1):
            if record.sequence != sequence or record.previous_record_fingerprint != previous:
                raise ValueError("lifecycle journal hash chain is invalid")
            previous = record.record_fingerprint
        self._records = list(records)

    def append(
        self,
        event_type: LifecycleEventType,
        timestamp: datetime,
        payload: object,
        *,
        position_id: str,
        exit_decision_id: str | None = None,
        close_request_id: str | None = None,
        deal_id: str | None = None,
    ) -> LifecycleJournalRecord:
        fields = {
            "sequence": len(self._records) + 1,
            "event_type": event_type,
            "timestamp": timestamp,
            "position_id": position_id,
            "exit_decision_id": exit_decision_id,
            "close_request_id": close_request_id,
            "deal_id": deal_id,
            "payload_fingerprint": fingerprint(payload),
            "previous_record_fingerprint": (
                self._records[-1].record_fingerprint if self._records else None
            ),
        }
        identity = fingerprint(fields)
        record = LifecycleJournalRecord.model_validate(
            {**fields, "record_id": identity, "record_fingerprint": identity}
        )
        self._records.append(record)
        return record

    def records(self) -> tuple[LifecycleJournalRecord, ...]:
        return tuple(self._records)


_DURABLE_TYPES = {
    LifecycleEventType.POSITION_MONITORED: JournalRecordType.POSITION_MONITOR_SNAPSHOT,
    LifecycleEventType.EXIT_DECISION_CREATED: JournalRecordType.EXIT_DECISION,
    LifecycleEventType.EXIT_PREFLIGHT_UPDATED: JournalRecordType.EXIT_PREFLIGHT,
    LifecycleEventType.CLOSE_REQUEST_CREATED: JournalRecordType.CLOSE_REQUEST,
    LifecycleEventType.CLOSE_SUBMITTED: JournalRecordType.CLOSE_SUBMISSION,
    LifecycleEventType.CLOSE_CONFIRMATION_UPDATED: JournalRecordType.CLOSE_CONFIRMATION,
    LifecycleEventType.CLOSE_RECONCILIATION_UPDATED: JournalRecordType.CLOSE_RECONCILIATION,
    LifecycleEventType.POSITION_CLOSED: JournalRecordType.POSITION_CLOSED,
    LifecycleEventType.POSITION_CLOSE_BLOCKED: JournalRecordType.POSITION_CLOSE_BLOCKED,
    LifecycleEventType.POSITION_LIFECYCLE_HALTED: JournalRecordType.POSITION_LIFECYCLE_HALTED,
    LifecycleEventType.POST_TRADE_REVIEW_CREATED: JournalRecordType.POST_TRADE_REVIEW,
}


class DurableLifecycleJournal(InMemoryLifecycleJournal):
    """Mirror the lifecycle hash chain into the durable append-only journal."""

    def __init__(
        self,
        writer: DurableJournalWriter,
        records: tuple[LifecycleJournalRecord, ...] = (),
    ) -> None:
        super().__init__(records)
        self._writer = writer
        self._last_source_by_position: dict[str, str] = {}
        for record in records:
            self._last_source_by_position[record.position_id] = record.record_id

    def append(
        self,
        event_type: LifecycleEventType,
        timestamp: datetime,
        payload: object,
        *,
        position_id: str,
        exit_decision_id: str | None = None,
        close_request_id: str | None = None,
        deal_id: str | None = None,
    ) -> LifecycleJournalRecord:
        record = super().append(
            event_type,
            timestamp,
            payload,
            position_id=position_id,
            exit_decision_id=exit_decision_id,
            close_request_id=close_request_id,
            deal_id=deal_id,
        )
        parent = self._last_source_by_position.get(position_id)
        if parent is None and isinstance(payload, DemoPositionSnapshot):
            parent = payload.source_execution_id
        try:
            self._writer.append_source(
                record_type=_DURABLE_TYPES[event_type],
                source_record_id=record.record_id,
                source=payload,
                source_parent_ids=(parent,) if parent else (),
                created_at=timestamp,
                effective_at=timestamp,
                environment="DEMO",
            )
        except Exception:
            self._records.pop()
            raise
        self._last_source_by_position[position_id] = record.record_id
        return record
