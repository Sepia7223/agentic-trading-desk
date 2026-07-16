"""Immutable reconciliation of accepted Demo deals against open positions."""

from __future__ import annotations

from datetime import datetime

from trading_desk.execution.fingerprints import fingerprint
from trading_desk.execution.models import (
    DemoPositionRecord,
    ExecutionDirection,
    ExecutionRequest,
    ExecutionResult,
    ReconciliationResult,
    ReconciliationStatus,
)
from trading_desk.ig.models import Direction, OpenPosition


def reconcile_position(
    request: ExecutionRequest,
    result: ExecutionResult,
    positions: tuple[OpenPosition, ...],
    checked_at: datetime,
) -> tuple[ReconciliationResult, DemoPositionRecord | None]:
    position = next(
        (
            item
            for item in positions
            if item.deal_id == result.deal_id
            or (result.deal_reference is not None and item.deal_reference == result.deal_reference)
        ),
        None,
    )
    discrepancies: list[str] = []
    if position is None:
        status = ReconciliationStatus.POSITION_NOT_FOUND
    else:
        expected_direction = Direction.BUY if request.direction is ExecutionDirection.BUY else None
        if position.market.epic != request.epic:
            discrepancies.append("INSTRUMENT_MISMATCH")
        if position.direction != expected_direction:
            discrepancies.append("DIRECTION_MISMATCH")
        if result.accepted_quantity is None or position.size != result.accepted_quantity:
            discrepancies.append("QUANTITY_MISMATCH")
        if result.entry_level is None or position.opening_level != result.entry_level:
            discrepancies.append("ENTRY_LEVEL_MISMATCH")
        if position.stop_level != request.stop_reference:
            discrepancies.append("STOP_MISMATCH")
        if position.limit_level != request.target_reference:
            discrepancies.append("TARGET_MISMATCH")
        status = (
            ReconciliationStatus.RECONCILIATION_MISMATCH
            if discrepancies
            else ReconciliationStatus.RECONCILED
        )
    fields = {
        "execution_result_id": result.execution_result_id,
        "status": status,
        "checked_at": checked_at,
        "deal_reference": result.deal_reference or "unknown",
        "deal_id": result.deal_id,
        "discrepancies": tuple(discrepancies),
    }
    reconciliation_fingerprint = fingerprint(fields)
    reconciliation = ReconciliationResult.model_validate(
        {
            **fields,
            "reconciliation_id": reconciliation_fingerprint,
            "reconciliation_fingerprint": reconciliation_fingerprint,
        }
    )
    if status is not ReconciliationStatus.RECONCILED or position is None:
        return reconciliation, None
    position_fields = {
        "execution_result_id": result.execution_result_id,
        "reconciliation_id": reconciliation.reconciliation_id,
        "deal_reference": result.deal_reference,
        "deal_id": position.deal_id,
        "instrument": request.instrument,
        "epic": request.epic,
        "direction": request.direction,
        "quantity": position.size,
        "entry_level": position.opening_level,
        "stop_level": position.stop_level,
        "target_level": position.limit_level,
        "recorded_at": checked_at,
    }
    record_fingerprint = fingerprint(position_fields)
    demo_position = DemoPositionRecord.model_validate(
        {
            **position_fields,
            "record_id": record_fingerprint,
            "record_fingerprint": record_fingerprint,
        }
    )
    return reconciliation, demo_position


def pending_reconciliation(result: ExecutionResult, checked_at: datetime) -> ReconciliationResult:
    fields = {
        "execution_result_id": result.execution_result_id,
        "status": ReconciliationStatus.RECONCILIATION_PENDING,
        "checked_at": checked_at,
        "deal_reference": result.deal_reference or "unknown",
        "deal_id": result.deal_id,
        "discrepancies": ("POSITION_STATE_UNAVAILABLE",),
    }
    reconciliation_fingerprint = fingerprint(fields)
    return ReconciliationResult.model_validate(
        {
            **fields,
            "reconciliation_id": reconciliation_fingerprint,
            "reconciliation_fingerprint": reconciliation_fingerprint,
        }
    )
