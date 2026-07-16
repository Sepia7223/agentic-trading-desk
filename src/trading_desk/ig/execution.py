"""OAuth-authenticated IG Demo adapter for one controlled mutation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, NoReturn

import httpx
from pydantic import ValidationError

from trading_desk.config import (
    IG_DEMO_BASE_URL,
    AppSettings,
    BrokerEnvironment,
    OperatingMode,
)
from trading_desk.execution.errors import ExecutionBrokerError
from trading_desk.execution.models import (
    BrokerConfirmation,
    BrokerConfirmationStatus,
    BrokerOrderRequest,
    BrokerSubmission,
    ExecutionDirection,
)
from trading_desk.ig.client import IGDemoClient
from trading_desk.ig.execution_policy import (
    DEAL_CONFIRMATION_VERSION,
    OPEN_POSITION_VERSION,
    ExecutionOperation,
    enforce_execution_policy,
    validate_deal_reference,
)


class IGDemoExecutionAdapter(IGDemoClient):
    """Dedicated Demo-only adapter; no close, amend, working-order, or switch surface."""

    def __repr__(self) -> str:
        authenticated = str(self._has_session()).lower()
        return (
            "IGDemoExecutionAdapter(environment=DEMO, mode=CONTROLLED_EXECUTION, "
            f"authenticated={authenticated})"
        )

    async def __aenter__(self) -> IGDemoExecutionAdapter:
        try:
            await self.login()
            return self
        except Exception:
            await self.aclose()
            raise

    async def submit_market_position(self, request: BrokerOrderRequest) -> BrokerSubmission:
        response, data = await self._execution_send(
            ExecutionOperation.OPEN_POSITION,
            "POST",
            "/positions/otc",
            OPEN_POSITION_VERSION,
            content=_serialize_order(request),
        )
        deal_reference = data.get("dealReference")
        if not isinstance(deal_reference, str) or not deal_reference:
            raise ExecutionBrokerError(
                "IG submission response was malformed",
                operation=ExecutionOperation.OPEN_POSITION.value,
                http_status=response.status_code,
                request_id=_request_id(response),
                ambiguous=True,
            )
        try:
            return BrokerSubmission(
                deal_reference=validate_deal_reference(deal_reference),
                safe_request_id=_request_id(response),
            )
        except (ValidationError, ValueError):
            raise ExecutionBrokerError(
                "IG submission response was malformed",
                operation=ExecutionOperation.OPEN_POSITION.value,
                http_status=response.status_code,
                request_id=_request_id(response),
                ambiguous=True,
            ) from None

    async def get_deal_confirmation(self, deal_reference: str) -> BrokerConfirmation:
        safe_reference = validate_deal_reference(deal_reference)
        response, data = await self._execution_send(
            ExecutionOperation.DEAL_CONFIRMATION,
            "GET",
            f"/confirms/{safe_reference}",
            DEAL_CONFIRMATION_VERSION,
            pending_not_found=True,
        )
        if data.get("pending") is True:
            return BrokerConfirmation(
                deal_reference=safe_reference,
                status=BrokerConfirmationStatus.PENDING,
                confirmed_at=datetime.now(UTC),
            )
        try:
            returned_reference = _required_text(data, "dealReference")
            if returned_reference != safe_reference:
                raise ValueError("confirmation reference mismatch")
            raw_status = _required_text(data, "dealStatus").upper()
            status = {
                "ACCEPTED": BrokerConfirmationStatus.ACCEPTED,
                "REJECTED": BrokerConfirmationStatus.REJECTED,
            }.get(raw_status, BrokerConfirmationStatus.UNKNOWN)
            direction = data.get("direction")
            return BrokerConfirmation(
                deal_reference=returned_reference,
                deal_id=_optional_text(data.get("dealId")),
                status=status,
                broker_status=_optional_text(data.get("status")),
                broker_reason=_optional_text(data.get("reason")),
                epic=_optional_text(data.get("epic")),
                direction=(ExecutionDirection.BUY if direction == "BUY" else None),
                executed_level=_optional_decimal(data.get("level")),
                executed_size=_optional_decimal(data.get("size")),
                stop_level=_optional_decimal(data.get("stopLevel")),
                limit_level=_optional_decimal(data.get("limitLevel")),
                confirmed_at=datetime.now(UTC),
            )
        except (ValidationError, TypeError, ValueError):
            raise ExecutionBrokerError(
                "IG confirmation response was malformed",
                operation=ExecutionOperation.DEAL_CONFIRMATION.value,
                http_status=response.status_code,
                request_id=_request_id(response),
            ) from None

    async def _execution_send(
        self,
        operation: ExecutionOperation,
        method: str,
        path: str,
        version: int,
        *,
        content: str | None = None,
        pending_not_found: bool = False,
    ) -> tuple[httpx.Response, dict[str, Any]]:
        enforce_execution_policy(operation, method, path, version)
        self._require_active_oauth_session_for_execution(operation)
        api_key = self._required_secret(self._broker_settings.api_key, "IG_API_KEY")
        assert self._access_token is not None
        assert self._account_id is not None
        headers = {
            "X-IG-API-KEY": api_key,
            "Authorization": f"Bearer {self._access_token.get_secret_value()}",
            "IG-ACCOUNT-ID": self._account_id,
            "Content-Type": "application/json",
            "Accept": "application/json; charset=UTF-8",
            "Version": str(version),
        }
        try:
            response = await self._client.request(
                method, path.lstrip("/"), headers=headers, content=content
            )
        except httpx.HTTPError:
            raise ExecutionBrokerError(
                "IG execution transport failed",
                operation=operation.value,
                ambiguous=operation is ExecutionOperation.OPEN_POSITION,
            ) from None
        data = _decode_json(response, operation)
        error_code = data.get("errorCode") if isinstance(data.get("errorCode"), str) else None
        if (
            pending_not_found
            and response.status_code == 404
            and error_code == "error.confirms.deal-not-found"
        ):
            return response, {"pending": True}
        if not response.is_success or error_code is not None:
            raise ExecutionBrokerError(
                "IG execution request was rejected",
                operation=operation.value,
                http_status=response.status_code,
                error_code=error_code,
                request_id=_request_id(response),
                ambiguous=(
                    operation is ExecutionOperation.OPEN_POSITION and response.status_code >= 500
                ),
            )
        return response, data

    def _require_active_oauth_session_for_execution(self, operation: ExecutionOperation) -> None:
        try:
            from trading_desk.ig.policy import Operation

            self._require_active_oauth_session(Operation.POSITIONS)
        except Exception as error:
            if isinstance(error, ExecutionBrokerError):
                raise
            raise ExecutionBrokerError(
                "IG execution requires an active OAuth session",
                operation=operation.value,
            ) from None

    @staticmethod
    def _validate_runtime_boundary(settings: AppSettings) -> None:
        if settings.broker.broker_environment is not BrokerEnvironment.DEMO:
            raise ValueError("broker environment must be DEMO")
        if settings.safety.operating_mode is not OperatingMode.CONTROLLED_EXECUTION:
            raise ValueError("operating mode must be CONTROLLED_EXECUTION")
        if settings.safety.live_trading_allowed:
            raise ValueError("live trading must remain disabled")
        if settings.safety.automatic_execution_enabled:
            raise ValueError("automatic execution must remain disabled")
        if settings.broker.base_url != IG_DEMO_BASE_URL:
            raise ValueError("IG base URL must be the canonical demo endpoint")


def _serialize_order(request: BrokerOrderRequest) -> str:
    values: list[tuple[str, object]] = [
        ("currencyCode", request.currency_code),
        ("dealReference", request.deal_reference),
        ("direction", request.direction.value),
        ("epic", request.epic),
        ("expiry", request.expiry),
        ("forceOpen", request.force_open),
        ("guaranteedStop", request.guaranteed_stop),
        ("orderType", request.order_type.value),
        ("size", request.size),
        ("stopLevel", request.stop_level),
    ]
    if request.limit_level is not None:
        values.append(("limitLevel", request.limit_level))
    encoded = []
    for key, value in values:
        serialized = format(value, "f") if isinstance(value, Decimal) else json.dumps(value)
        encoded.append(f"{json.dumps(key)}:{serialized}")
    return "{" + ",".join(encoded) + "}"


def _decode_json(response: httpx.Response, operation: ExecutionOperation) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        _raise_invalid_response(operation, response)
    if not isinstance(data, dict):
        _raise_invalid_response(operation, response)
    return data


def _raise_invalid_response(operation: ExecutionOperation, response: httpx.Response) -> NoReturn:
    raise ExecutionBrokerError(
        "IG execution response was not a JSON object",
        operation=operation.value,
        http_status=response.status_code,
        request_id=_request_id(response),
        ambiguous=operation is ExecutionOperation.OPEN_POSITION,
    ) from None


def _request_id(response: httpx.Response) -> str | None:
    value = response.headers.get("X-REQUEST-ID") or response.headers.get("X-CORRELATION-ID")
    return str(value) if value is not None else None


def _required_text(data: dict[str, Any], key: str) -> str:
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
