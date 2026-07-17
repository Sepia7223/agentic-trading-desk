"""Deterministic full-close reconciliation against current Demo positions."""

from datetime import datetime

from trading_desk.ig.models import Direction, OpenPosition
from trading_desk.lifecycle.fingerprints import fingerprint
from trading_desk.lifecycle.models import (
    CloseExecutionResult,
    CloseReconciliationResult,
    CloseReconciliationStatus,
    CloseRequest,
)


def reconcile_close(
    request: CloseRequest,
    result: CloseExecutionResult,
    positions: tuple[OpenPosition, ...],
    checked_at: datetime,
) -> CloseReconciliationResult:
    exact = next((item for item in positions if item.deal_id == request.deal_id), None)
    opposite = next(
        (
            item
            for item in positions
            if item.market.epic == request.epic and item.direction is Direction.SELL
        ),
        None,
    )
    discrepancies: list[str] = []
    remaining = None
    if opposite is not None:
        status = CloseReconciliationStatus.UNEXPECTED_OPPOSITE_POSITION
        discrepancies.append("OPPOSITE_POSITION_CREATED")
        remaining = opposite.size
    elif exact is None:
        status = CloseReconciliationStatus.POSITION_CLOSED
        remaining = request.requested_quantity * 0
    else:
        remaining = exact.size
        if exact.market.epic != request.epic or exact.direction is not Direction.BUY:
            status = CloseReconciliationStatus.RECONCILIATION_MISMATCH
            discrepancies.append("POSITION_IDENTITY_MISMATCH")
        elif exact.size == request.requested_quantity:
            status = CloseReconciliationStatus.POSITION_STILL_OPEN
            discrepancies.append("FULL_POSITION_REMAINS")
        elif exact.size > 0:
            status = CloseReconciliationStatus.PARTIAL_POSITION_REMAINS
            discrepancies.append("NON_ZERO_RESIDUAL_QUANTITY")
        else:
            status = CloseReconciliationStatus.POSITION_NOT_FOUND_AS_EXPECTED
            discrepancies.append("ZERO_SIZE_POSITION_RETURNED")
    fields = {
        "close_result_id": result.close_result_id,
        "position_id": request.position_id,
        "status": status,
        "checked_at": checked_at,
        "remaining_quantity": remaining,
        "discrepancies": tuple(discrepancies),
    }
    identity = fingerprint(fields)
    return CloseReconciliationResult.model_validate(
        {**fields, "reconciliation_id": identity, "reconciliation_fingerprint": identity}
    )


def pending_close_reconciliation(
    request: CloseRequest,
    result: CloseExecutionResult,
    checked_at: datetime,
) -> CloseReconciliationResult:
    fields = {
        "close_result_id": result.close_result_id,
        "position_id": request.position_id,
        "status": CloseReconciliationStatus.RECONCILIATION_PENDING,
        "checked_at": checked_at,
        "remaining_quantity": None,
        "discrepancies": ("POSITION_STATE_UNAVAILABLE",),
    }
    identity = fingerprint(fields)
    return CloseReconciliationResult.model_validate(
        {**fields, "reconciliation_id": identity, "reconciliation_fingerprint": identity}
    )
