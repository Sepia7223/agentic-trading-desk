"""Deterministic operator-confirmation creation and validation."""

from datetime import datetime, timedelta

from trading_desk.execution.config import ExecutionConfiguration
from trading_desk.execution.fingerprints import fingerprint
from trading_desk.execution.models import ExecutionRequest, OperatorConfirmation


def create_operator_confirmation(
    request: ExecutionRequest,
    *,
    confirmed_at: datetime,
    configuration: ExecutionConfiguration,
    validity: timedelta = timedelta(minutes=1),
) -> OperatorConfirmation:
    fields = {
        "execution_request_id": request.execution_request_id,
        "request_fingerprint": request.request_fingerprint,
        "exact_quantity": request.requested_quantity,
        "instrument": request.instrument,
        "direction": request.direction,
        "maximum_price_drift_bps": configuration.reject_on_price_drift_bps,
        "confirmed_at": confirmed_at,
        "expires_at": confirmed_at + validity,
    }
    confirmation_id = fingerprint(fields)
    return OperatorConfirmation.model_validate(
        {
            **fields,
            "confirmation_id": confirmation_id,
            "confirmation_fingerprint": confirmation_id,
        }
    )


def confirmation_matches(
    request: ExecutionRequest,
    confirmation: OperatorConfirmation | None,
    evaluation_timestamp: datetime,
    configuration: ExecutionConfiguration,
) -> bool:
    return bool(
        confirmation is not None
        and request.operator_confirmation_id == confirmation.confirmation_id
        and confirmation.execution_request_id == request.execution_request_id
        and confirmation.request_fingerprint == request.request_fingerprint
        and confirmation.exact_quantity == request.requested_quantity
        and confirmation.instrument == request.instrument
        and confirmation.direction is request.direction
        and confirmation.maximum_price_drift_bps == configuration.reject_on_price_drift_bps
        and confirmation.confirmed_at <= evaluation_timestamp < confirmation.expires_at
    )
