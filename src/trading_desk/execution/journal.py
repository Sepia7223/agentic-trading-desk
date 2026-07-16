"""Append-only execution journal with a deterministic hash chain."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from trading_desk.execution.fingerprints import fingerprint
from trading_desk.execution.models import ExecutionEventType, ExecutionJournalRecord


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
    def __init__(self) -> None:
        self._records: list[ExecutionJournalRecord] = []

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
