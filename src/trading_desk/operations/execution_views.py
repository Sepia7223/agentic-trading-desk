"""Joined read-only execution lifecycle projections."""

from decimal import Decimal, InvalidOperation

from trading_desk.journal.models import JournalRecordType
from trading_desk.operations.fingerprints import fingerprint
from trading_desk.operations.lineage import connected_records
from trading_desk.operations.models import (
    ExecutionLifecycleProjection,
    ExecutionStageProjection,
    RecordProjection,
)
from trading_desk.operations.projections import safe_reference

_STAGES = {
    JournalRecordType.APPROVED_TRADE_INTENT.value: "APPROVED INTENT",
    JournalRecordType.EXECUTION_REQUEST.value: "EXECUTION REQUEST",
    JournalRecordType.EXECUTION_PREFLIGHT.value: "PREFLIGHT",
    JournalRecordType.OPERATOR_CONFIRMATION.value: "OPERATOR CONFIRMATION",
    JournalRecordType.BROKER_SUBMISSION.value: "SUBMISSION",
    JournalRecordType.BROKER_CONFIRMATION.value: "BROKER CONFIRMATION",
    JournalRecordType.EXECUTION_RECONCILIATION.value: "RECONCILIATION",
    JournalRecordType.EXECUTION_FAILURE.value: "FAILURE",
}


def build_execution_lifecycles(
    records: tuple[RecordProjection, ...],
) -> tuple[ExecutionLifecycleProjection, ...]:
    seeds = tuple(
        item for item in records if item.record_type == JournalRecordType.EXECUTION_REQUEST.value
    )
    if not seeds:
        seeds = tuple(
            item
            for item in records
            if item.record_type
            in {
                JournalRecordType.EXECUTION_PREFLIGHT.value,
                JournalRecordType.BROKER_SUBMISSION.value,
                JournalRecordType.BROKER_CONFIRMATION.value,
                JournalRecordType.EXECUTION_RECONCILIATION.value,
                JournalRecordType.EXECUTION_FAILURE.value,
            }
        )
    results: dict[str, ExecutionLifecycleProjection] = {}
    for seed in seeds:
        linked = connected_records(seed, records)
        request_id = _first_text(linked, "execution_request_id") or seed.source_record_id
        if request_id in results:
            continue
        stages = tuple(_stage(item) for item in linked if item.record_type in _STAGES)
        request = _record(linked, JournalRecordType.EXECUTION_REQUEST)
        confirmation = _record(linked, JournalRecordType.BROKER_CONFIRMATION)
        reconciliation = _record(linked, JournalRecordType.EXECUTION_RECONCILIATION)
        failure = _record(linked, JournalRecordType.EXECUTION_FAILURE)
        reference = _first_value(linked, "deal_reference")
        discrepancies = _strings(
            reconciliation.payload.get("discrepancies") if reconciliation else None
        )
        fields: dict[str, object] = {
            "execution_request_id": request_id,
            "instrument": (request.instrument if request else seed.instrument),
            "epic": (request.epic if request else seed.epic),
            "direction": _first_text(linked, "direction"),
            "approved_quantity": _first_decimal(linked, "approved_quantity"),
            "submitted_quantity": _first_decimal(
                linked, "submitted_quantity", "requested_quantity", "size"
            ),
            "stop_price": _first_decimal(linked, "stop_level", "stop_reference", "stop_price"),
            "target_price": _first_decimal(
                linked, "limit_level", "target_level", "target_reference", "target_price"
            ),
            "safely_truncated_deal_reference": safe_reference(reference),
            "confirmation_status": _status(confirmation, "NOT_REACHED"),
            "confirmed_entry": _decimal_from(
                confirmation, "executed_level", "entry_level", "confirmed_entry"
            ),
            "confirmed_size": _decimal_from(
                confirmation, "executed_size", "accepted_quantity", "confirmed_size"
            ),
            "reconciliation_status": _status(reconciliation, "NOT_REACHED"),
            "discrepancies": discrepancies,
            "halt_status": (
                "HALTED"
                if failure or discrepancies
                else _first_text(linked, "halt_status") or "CLEAR"
            ),
            "stages": stages,
            "source_record_ids": tuple(item.source_record_id for item in linked),
        }
        results[request_id] = ExecutionLifecycleProjection.model_validate(
            {**fields, "lifecycle_fingerprint": fingerprint(fields)}
        )
    return tuple(
        sorted(
            results.values(),
            key=lambda item: item.stages[-1].timestamp,
            reverse=True,
        )
    )


def _stage(record: RecordProjection) -> ExecutionStageProjection:
    allowed: dict[str, object] = {
        key: record.payload[key]
        for key in (
            "approved_quantity",
            "requested_quantity",
            "validated_quantity",
            "executed_level",
            "executed_size",
            "safe_request_id",
        )
        if key in record.payload
    }
    return ExecutionStageProjection(
        stage=_STAGES[record.record_type],
        status=_status(record, "RECORDED"),
        timestamp=record.effective_at,
        source_record_id=record.source_record_id,
        reason_codes=_strings(record.payload.get("reason_codes")),
        safe_details=allowed,
    )


def _record(
    records: tuple[RecordProjection, ...], record_type: JournalRecordType
) -> RecordProjection | None:
    return next((item for item in reversed(records) if item.record_type == record_type.value), None)


def _status(record: RecordProjection | None, default: str) -> str:
    if record is None:
        return default
    return (
        _text(record.payload.get("status"))
        or _text(record.payload.get("confirmation_status"))
        or _text(record.payload.get("reconciliation_status"))
        or default
    )


def _first_value(records: tuple[RecordProjection, ...], *keys: str) -> object | None:
    for record in reversed(records):
        for key in keys:
            if key in record.payload and record.payload[key] is not None:
                return record.payload[key]
    return None


def _first_text(records: tuple[RecordProjection, ...], *keys: str) -> str | None:
    return _text(_first_value(records, *keys))


def _first_decimal(records: tuple[RecordProjection, ...], *keys: str) -> Decimal | None:
    return _to_decimal(_first_value(records, *keys))


def _decimal_from(record: RecordProjection | None, *keys: str) -> Decimal | None:
    if record is None:
        return None
    return _to_decimal(next((record.payload[key] for key in keys if key in record.payload), None))


def _to_decimal(value: object | None) -> Decimal | None:
    try:
        return None if value is None else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _text(value: object | None) -> str | None:
    return None if value is None else str(value)


def _strings(value: object | None) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return ()
