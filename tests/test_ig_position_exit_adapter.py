from __future__ import annotations

import asyncio
import json
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr

from trading_desk.config import (
    AISettings,
    AppSettings,
    BrokerSettings,
    OperatingMode,
    SafetySettings,
)
from trading_desk.execution.errors import ExecutionBrokerError, ExecutionPolicyViolation
from trading_desk.ig.execution_policy import (
    CLOSE_POSITION_VERSION,
    ExecutionOperation,
    enforce_execution_policy,
)
from trading_desk.ig.position_exit import IGDemoPositionExitAdapter
from trading_desk.lifecycle.models import (
    BrokerCloseRequest,
    CloseConfirmationStatus,
    CloseOrderType,
    CloseSide,
    CloseTimeInForce,
)


def settings() -> AppSettings:
    return AppSettings(
        broker=BrokerSettings(
            identifier=SecretStr("test-user"),
            password=SecretStr("test-password"),
            api_key=SecretStr("test-api-key"),
        ),
        safety=SafetySettings(operating_mode=OperatingMode.CONTROLLED_EXECUTION),
        ai=AISettings(),
    )


def login_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "currentAccountId": "account-1",
            "clientId": "client-1",
            "environment": "DEMO",
            "oauthToken": {
                "access_token": "test-access-token",
                "refresh_token": "test-refresh-token",
                "token_type": "Bearer",
                "expires_in": "60",
            },
        },
    )


def close_request() -> BrokerCloseRequest:
    return BrokerCloseRequest(
        deal_id="deal-id-1",
        direction=CloseSide.SELL,
        size=Decimal("1.2500"),
        order_type=CloseOrderType.MARKET,
        time_in_force=CloseTimeInForce.FILL_OR_KILL,
    )


def test_exact_delete_v1_mapping_and_sell_confirmation() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/session"):
            return login_response()
        if request.url.path.endswith("/positions/otc"):
            assert request.method == "DELETE"
            assert request.headers["Version"] == "1"
            assert json.loads(request.content) == {
                "dealId": "deal-id-1",
                "direction": "SELL",
                "size": 1.25,
                "orderType": "MARKET",
                "timeInForce": "FILL_OR_KILL",
            }
            return httpx.Response(200, json={"dealReference": "close-ref-1"})
        if "/confirms/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "dealReference": "close-ref-1",
                    "dealId": "close-deal-1",
                    "dealStatus": "ACCEPTED",
                    "status": "CLOSED",
                    "reason": "SUCCESS",
                    "epic": "CS.D.EURUSD.CFD.IP",
                    "direction": "SELL",
                    "level": 99,
                    "size": 1.25,
                },
            )
        raise AssertionError("unexpected endpoint")

    async def scenario() -> None:
        adapter = IGDemoPositionExitAdapter(settings(), transport=httpx.MockTransport(handler))
        await adapter.login()
        submission = await adapter.submit_position_close(close_request())
        confirmation = await adapter.get_close_confirmation(submission.deal_reference)
        assert confirmation.status is CloseConfirmationStatus.ACCEPTED
        assert confirmation.direction is CloseSide.SELL
        assert "test-access-token" not in repr(adapter)
        await adapter.aclose()

    asyncio.run(scenario())
    assert len(requests) == 3


@pytest.mark.parametrize(
    ("method", "path", "version"),
    [
        ("POST", "/positions/otc", 1),
        ("DELETE", "/positions/otc", 2),
        ("DELETE", "https://api.ig.com/gateway/deal/positions/otc", 1),
        ("DELETE", "/positions/otc/", 1),
        ("PUT", "/positions/otc/deal-id-1", 2),
    ],
)
def test_close_policy_rejects_every_non_allowlisted_contract(
    method: str, path: str, version: int
) -> None:
    with pytest.raises(ExecutionPolicyViolation):
        enforce_execution_policy(ExecutionOperation.CLOSE_POSITION, method, path, version)


def test_close_transport_failure_is_ambiguous_and_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path.endswith("/session"):
            return login_response()
        calls += 1
        raise httpx.ReadTimeout("redacted")

    async def scenario() -> None:
        adapter = IGDemoPositionExitAdapter(settings(), transport=httpx.MockTransport(handler))
        await adapter.login()
        with pytest.raises(ExecutionBrokerError) as captured:
            await adapter.submit_position_close(close_request())
        assert captured.value.ambiguous
        assert "test-api-key" not in str(captured.value)
        await adapter.aclose()

    asyncio.run(scenario())
    assert calls == 1


def test_close_allowlist_constant_is_documented_version() -> None:
    assert CLOSE_POSITION_VERSION == 1
