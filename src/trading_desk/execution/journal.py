"""Append-only execution journal with a deterministic hash chain."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from trading_desk.execution.fingerprints import fingerprint
from trading_desk.execution.models import ExecutionEventType, ExecutionJournalRecord
from trading_desk.journal.models import JournalRecordType
from trading_desk.journal.writer import DurableJournalWriter


class ExecutionJournal(Protocol):
    def append(
        self,
        event_type: ExecutionEventType,
        timestamp: datetime,
        payload: object,
        *,
        signal_id: str | None = None,
        candidate_id: str | None = None,
        risk_decision_id: str | None = None,
        approved_intent_id: str | None = None,
        execution_request_id: str | None = None,
        deal_reference: str | None = None,
        deal_id: str | None = None,
    ) -> ExecutionJournalRecord: ...


class InMemoryExecutionJournal:
    def __init__(self, records: tuple[ExecutionJournalRecord, ...] = ()) -> None:
        previous: str | None = None
        for sequence, record in enumerate(records, start=1):
            if record.sequence != sequence or record.previous_record_fingerprint != previous:
                raise ValueError("execution journal hash chain is invalid")
            previous = record.record_fingerprint
        self._records = list(records)

    def append(
        self,
        event_type: ExecutionEventType,
        timestamp: datetime,
        payload: object,
        *,
        signal_id: str | None = None,
        candidate_id: str | None = None,
        risk_decision_id: str | None = None,
        approved_intent_id: str | None = None,
        execution_request_id: str | None = None,
        deal_reference: str | None = None,
        deal_id: str | None = None,
    ) -> ExecutionJournalRecord:
        previous = self._records[-1].record_fingerprint if self._records else None
        fields = {
            "sequence": len(self._records) + 1,
            "event_type": event_type,
            "timestamp": timestamp,
            "signal_id": signal_id,
            "candidate_id": candidate_id,
            "risk_decision_id": risk_decision_id,
            "approved_intent_id": approved_intent_id,
            "execution_request_id": execution_request_id,
            "deal_reference": deal_reference,
            "deal_id": deal_id,
            "payload_fingerprint": fingerprint(payload),
            "previous_record_fingerprint": previous,
        }
        record_fingerprint = fingerprint(fields)
        record = ExecutionJournalRecord.model_validate(
            {
                **fields,
                "record_id": record_fingerprint,
                "record_fingerprint": record_fingerprint,
            }
        )
        self._records.append(record)
        return record

    def records(self) -> tuple[ExecutionJournalRecord, ...]:
        return tuple(self._records)


_DURABLE_TYPES = {
    ExecutionEventType.REQUEST_CREATED: JournalRecordType.EXECUTION_REQUEST,
    ExecutionEventType.PREFLIGHT_COMPLETED: JournalRecordType.EXECUTION_PREFLIGHT,
    ExecutionEventType.OPERATOR_CONFIRMED: JournalRecordType.OPERATOR_CONFIRMATION,
    ExecutionEventType.SUBMISSION_ATTEMPTED: JournalRecordType.BROKER_SUBMISSION,
    ExecutionEventType.BROKER_RESPONDED: JournalRecordType.BROKER_SUBMISSION,
    ExecutionEventType.CONFIRMATION_COMPLETED: JournalRecordType.BROKER_CONFIRMATION,
    ExecutionEventType.RECONCILIATION_COMPLETED: JournalRecordType.EXECUTION_RECONCILIATION,
    ExecutionEventType.EXECUTION_FAILED: JournalRecordType.EXECUTION_FAILURE,
}


class DurableExecutionJournal(InMemoryExecutionJournal):
    """Mirror one controlled execution chain into the durable journal."""

    def __init__(self, writer: DurableJournalWriter) -> None:
        super().__init__()
        self._writer = writer
        self._last_source_by_request: dict[str, str] = {}

    def append(
        self,
        event_type: ExecutionEventType,
        timestamp: datetime,
        payload: object,
        *,
        signal_id: str | None = None,
        candidate_id: str | None = None,
        risk_decision_id: str | None = None,
        approved_intent_id: str | None = None,
        execution_request_id: str | None = None,
        deal_reference: str | None = None,
        deal_id: str | None = None,
    ) -> ExecutionJournalRecord:
        record = super().append(
            event_type,
            timestamp,
            payload,
            signal_id=signal_id,
            candidate_id=candidate_id,
            risk_decision_id=risk_decision_id,
            approved_intent_id=approved_intent_id,
            execution_request_id=execution_request_id,
            deal_reference=deal_reference,
            deal_id=deal_id,
        )
        durable_type = _DURABLE_TYPES.get(event_type)
        if durable_type is None:
            return record
        if execution_request_id is None:
            self._records.pop()
            raise ValueError("durable execution evidence requires an execution request ID")
        parent = self._last_source_by_request.get(execution_request_id) or approved_intent_id
        if parent is None:
            self._records.pop()
            raise ValueError("durable execution evidence requires authoritative parent evidence")
        source_record_id = (
            execution_request_id
            if event_type is ExecutionEventType.REQUEST_CREATED
            else record.record_id
        )
        try:
            self._writer.append_source(
                record_type=durable_type,
                source_record_id=source_record_id,
                source=payload,
                source_parent_ids=(parent,),
                created_at=timestamp,
                effective_at=timestamp,
                environment="DEMO",
            )
        except Exception:
            self._records.pop()
            raise
        self._last_source_by_request[execution_request_id] = source_record_id
        return record
