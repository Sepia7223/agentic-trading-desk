"""Append-only correction records that preserve original evidence."""

from __future__ import annotations

from datetime import datetime

from trading_desk.journal.errors import JournalParentMissingError
from trading_desk.journal.fingerprints import fingerprint, reject_secret_fields
from trading_desk.journal.models import (
    Amendment,
    AmendmentReasonCode,
    JournalRecord,
    JournalRecordType,
)
from trading_desk.journal.sqlite import SQLiteJournalRepository
from trading_desk.journal.writer import DurableJournalWriter

_REALIZED_FACT_FIELDS = frozenset(
    {"gross_pnl", "net_pnl", "financial_outcome", "fill_price", "quantity", "deal_id"}
)


class AmendmentService:
    def __init__(self, repository: SQLiteJournalRepository) -> None:
        self.repository = repository
        self.writer = DurableJournalWriter(repository)

    def append(
        self,
        *,
        target_journal_record_id: str,
        created_at: datetime,
        reason_code: AmendmentReasonCode,
        reason: str,
        corrected_fields: dict[str, object],
        created_by: str,
        approval_reference: str | None = None,
    ) -> JournalRecord:
        if not self.repository.configuration.allow_amendments:
            raise ValueError("amendments are disabled")
        target = self.repository.get(target_journal_record_id)
        if target is None:
            raise JournalParentMissingError("amendment target does not exist")
        reject_secret_fields(corrected_fields)
        if _REALIZED_FACT_FIELDS.intersection(corrected_fields) and not approval_reference:
            raise ValueError("realized-fact corrections require an approval reference")
        previous_values = {key: target.payload.get(key) for key in sorted(corrected_fields)}
        base = {
            "target_journal_record_id": target_journal_record_id,
            "created_at": created_at,
            "reason_code": reason_code,
            "reason": reason,
            "corrected_fields": corrected_fields,
            "previous_values_fingerprint": fingerprint(previous_values),
            "corrected_values_fingerprint": fingerprint(corrected_fields),
            "created_by": created_by,
            "approval_reference": approval_reference,
        }
        amendment_fingerprint = fingerprint(base)
        amendment = Amendment.model_validate(
            {
                **base,
                "amendment_id": amendment_fingerprint,
                "amendment_fingerprint": amendment_fingerprint,
            }
        )
        return self.writer.append_source(
            record_type=JournalRecordType.AMENDMENT,
            source_record_id=amendment.amendment_id,
            source=amendment,
            source_parent_ids=(target.source_record_id,),
            created_at=created_at,
            effective_at=created_at,
            instrument=target.instrument,
            epic=target.epic,
            strategy_variant=target.strategy_variant,
            environment=target.environment,
        )
