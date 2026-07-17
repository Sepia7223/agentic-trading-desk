"""Dedicated OAuth-authenticated adapter for one full IG Demo position close."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Self

from pydantic import ValidationError

from trading_desk.execution.errors import ExecutionBrokerError
from trading_desk.ig.execution import IGDemoExecutionAdapter
from trading_desk.ig.execution_policy import (
    CLOSE_POSITION_VERSION,
    DEAL_CONFIRMATION_VERSION,
    ExecutionOperation,
    validate_deal_reference,
)
from trading_desk.lifecycle.models import (
    BrokerCloseRequest,
    BrokerCloseSubmission,
    CloseBrokerConfirmation,
    CloseConfirmationStatus,
    CloseSide,
)


class IGDemoPositionExitAdapter(IGDemoExecutionAdapter):
    """Full-close-only Demo adapter with no amendment or working-order surface."""

    def __repr__(self) -> str:
        authenticated = str(self._has_session()).lower()
        return (
            "IGDemoPositionExitAdapter(environment=DEMO, mode=POSITION_LIFECYCLE, "
            f"authenticated={authenticated})"
        )

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        return self

    async def submit_position_close(self, request: BrokerCloseRequest) -> BrokerCloseSubmission:
        response, data = await self._execution_send(
            ExecutionOperation.CLOSE_POSITION,
            "DELETE",
            "/positions/otc",
            CLOSE_POSITION_VERSION,
            content=_serialize_close(request),
        )
        reference = data.get("dealReference")
        if not isinstance(reference, str) or not reference:
            raise ExecutionBrokerError(
                "IG close acknowledgement was malformed",
                operation=ExecutionOperation.CLOSE_POSITION.value,
                http_status=response.status_code,
                request_id=_request_id(response.headers),
                ambiguous=True,
            )
        try:
            return BrokerCloseSubmission(
                deal_reference=validate_deal_reference(reference),
                safe_request_id=_request_id(response.headers),
            )
        except (ValidationError, ValueError):
            raise ExecutionBrokerError(
                "IG close acknowledgement was malformed",
                operation=ExecutionOperation.CLOSE_POSITION.value,
                http_status=response.status_code,
                request_id=_request_id(response.headers),
                ambiguous=True,
            ) from None

    async def get_close_confirmation(self, deal_reference: str) -> CloseBrokerConfirmation:
        safe_reference = validate_deal_reference(deal_reference)
        response, data = await self._execution_send(
            ExecutionOperation.DEAL_CONFIRMATION,
            "GET",
            f"/confirms/{safe_reference}",
            DEAL_CONFIRMATION_VERSION,
            pending_not_found=True,
        )
        if data.get("pending") is True:
            return CloseBrokerConfirmation(
                deal_reference=safe_reference,
                status=CloseConfirmationStatus.PENDING,
                confirmed_at=datetime.now(UTC),
            )
        try:
            returned = _required_text(data, "dealReference")
            if returned != safe_reference:
                raise ValueError("confirmation reference mismatch")
            raw_status = _required_text(data, "dealStatus").upper()
            status = {
                "ACCEPTED": CloseConfirmationStatus.ACCEPTED,
                "REJECTED": CloseConfirmationStatus.REJECTED,
            }.get(raw_status, CloseConfirmationStatus.UNKNOWN)
            direction = data.get("direction")
            if direction != "SELL":
                raise ExecutionBrokerError(
                    "IG close confirmation violated the offsetting-side policy",
                    operation=ExecutionOperation.DEAL_CONFIRMATION.value,
                    http_status=response.status_code,
                    error_code="CLOSE_DIRECTION_MISMATCH",
                    request_id=_request_id(response.headers),
                )
            return CloseBrokerConfirmation(
                deal_reference=returned,
                deal_id=_optional_text(data.get("dealId")),
                status=status,
                broker_status=_optional_text(data.get("status")),
                broker_reason=_optional_text(data.get("reason")),
                epic=_optional_text(data.get("epic")),
                direction=CloseSide.SELL,
                executed_level=_optional_decimal(data.get("level")),
                executed_size=_optional_decimal(data.get("size")),
                confirmed_at=datetime.now(UTC),
            )
        except ExecutionBrokerError:
            raise
        except (ValidationError, TypeError, ValueError):
            raise ExecutionBrokerError(
                "IG close confirmation was malformed",
                operation=ExecutionOperation.DEAL_CONFIRMATION.value,
                http_status=response.status_code,
                request_id=_request_id(response.headers),
            ) from None


def _serialize_close(request: BrokerCloseRequest) -> str:
    values: tuple[tuple[str, object], ...] = (
        ("dealId", request.deal_id),
        ("direction", request.direction.value),
        ("size", request.size),
        ("orderType", request.order_type.value),
        ("timeInForce", request.time_in_force.value),
    )
    encoded: list[str] = []
    for key, value in values:
        serialized = format(value, "f") if isinstance(value, Decimal) else json.dumps(value)
        encoded.append(f"{json.dumps(key)}:{serialized}")
    return "{" + ",".join(encoded) + "}"


def _required_text(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError("required confirmation text is missing")
    return value


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    parsed = Decimal(str(value))
    if not parsed.is_finite():
        raise ValueError("confirmation decimal is non-finite")
    return parsed


def _request_id(headers: object) -> str | None:
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return None
    value = getter("X-REQUEST-ID") or getter("X-CORRELATION-ID")
    return str(value) if value is not None else None
