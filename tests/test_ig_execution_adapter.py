from __future__ import annotations

import asyncio
import json
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr
from tests.execution_helpers import request_and_confirmation

from trading_desk.config import (
    AISettings,
    AppSettings,
    BrokerSettings,
    OperatingMode,
    SafetySettings,
)
from trading_desk.execution.errors import ExecutionBrokerError, ExecutionPolicyViolation
from trading_desk.execution.mapping import map_market_order
from trading_desk.execution.models import BrokerConfirmationStatus
from trading_desk.ig.execution import IGDemoExecutionAdapter
from trading_desk.ig.execution_policy import ExecutionOperation


def _settings() -> AppSettings:
    return AppSettings(
        broker=BrokerSettings(
            identifier=SecretStr("test-user"),
            password=SecretStr("test-password"),
            api_key=SecretStr("test-api-key"),
        ),
        safety=SafetySettings(operating_mode=OperatingMode.CONTROLLED_EXECUTION),
        ai=AISettings(),
    )


def _login_response() -> httpx.Response:
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


def test_adapter_submits_exact_market_order_and_parses_confirmation() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/session"):
            return _login_response()
        if request.url.path.endswith("/positions/otc"):
            assert request.method == "POST"
            assert request.headers["Version"] == "2"
            body = json.loads(request.content)
            assert body == {
                "currencyCode": "USD",
                "dealReference": body["dealReference"],
                "direction": "BUY",
                "epic": "CS.D.TEST.CFD.IP",
                "expiry": "-",
                "forceOpen": True,
                "guaranteedStop": False,
                "limitLevel": 110,
                "orderType": "MARKET",
                "size": 1,
                "stopLevel": 95,
            }
            return httpx.Response(
                200,
                json={"dealReference": "deal-ref-1"},
                headers={"X-REQUEST-ID": "safe-1"},
            )
        if "/confirms/" in request.url.path:
            assert request.method == "GET"
            assert request.headers["Version"] == "1"
            return httpx.Response(
                200,
                json={
                    "dealReference": "deal-ref-1",
                    "dealId": "deal-id-1",
                    "dealStatus": "ACCEPTED",
                    "status": "OPEN",
                    "reason": "SUCCESS",
                    "epic": "CS.D.TEST.CFD.IP",
                    "direction": "BUY",
                    "level": 100,
                    "size": 1,
                    "stopLevel": 95,
                    "limitLevel": 110,
                },
            )
        raise AssertionError("unexpected request")

    async def scenario() -> None:
        adapter = IGDemoExecutionAdapter(_settings(), transport=httpx.MockTransport(handler))
        await adapter.login()
        request, _, _ = request_and_confirmation()
        order = map_market_order(request, Decimal("1"))
        submission = await adapter.submit_market_position(order)
        confirmation = await adapter.get_deal_confirmation(submission.deal_reference)
        assert submission.safe_request_id == "safe-1"
        assert confirmation.status is BrokerConfirmationStatus.ACCEPTED
        assert confirmation.deal_id == "deal-id-1"
        assert "test-access-token" not in repr(adapter)
        await adapter.aclose()

    asyncio.run(scenario())
    assert len(requests) == 3


def test_submission_transport_failure_is_ambiguous_and_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path.endswith("/session"):
            return _login_response()
        calls += 1
        raise httpx.ReadTimeout("redacted")

    async def scenario() -> None:
        adapter = IGDemoExecutionAdapter(_settings(), transport=httpx.MockTransport(handler))
        await adapter.login()
        request, _, _ = request_and_confirmation()
        with pytest.raises(ExecutionBrokerError) as captured:
            await adapter.submit_market_position(map_market_order(request, Decimal("1")))
        assert captured.value.ambiguous is True
        assert "test-api-key" not in str(captured.value)
        assert "test-access-token" not in str(captured.value)
        await adapter.aclose()

    asyncio.run(scenario())
    assert calls == 1


def test_missing_deal_reference_is_ambiguous() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/session"):
            return _login_response()
        return httpx.Response(200, json={})

    async def scenario() -> None:
        adapter = IGDemoExecutionAdapter(_settings(), transport=httpx.MockTransport(handler))
        await adapter.login()
        request, _, _ = request_and_confirmation()
        with pytest.raises(ExecutionBrokerError) as captured:
            await adapter.submit_market_position(map_market_order(request, Decimal("1")))
        assert captured.value.ambiguous is True
        await adapter.aclose()

    asyncio.run(scenario())


def test_confirmation_not_found_maps_to_pending() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/session"):
            return _login_response()
        return httpx.Response(404, json={"errorCode": "error.confirms.deal-not-found"})

    async def scenario() -> None:
        adapter = IGDemoExecutionAdapter(_settings(), transport=httpx.MockTransport(handler))
        await adapter.login()
        confirmation = await adapter.get_deal_confirmation("deal-ref-1")
        assert confirmation.status is BrokerConfirmationStatus.PENDING
        await adapter.aclose()

    asyncio.run(scenario())


def test_non_buy_confirmation_has_explicit_policy_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/session"):
            return _login_response()
        return httpx.Response(
            200,
            json={
                "dealReference": "deal-ref-1",
                "dealStatus": "ACCEPTED",
                "direction": "SELL",
            },
        )

    async def scenario() -> None:
        adapter = IGDemoExecutionAdapter(_settings(), transport=httpx.MockTransport(handler))
        await adapter.login()
        with pytest.raises(ExecutionBrokerError) as captured:
            await adapter.get_deal_confirmation("deal-ref-1")
        assert captured.value.error_code == "DIRECTION_MISMATCH"
        await adapter.aclose()

    asyncio.run(scenario())


def test_invalid_path_is_blocked_before_transport() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    async def scenario() -> None:
        adapter = IGDemoExecutionAdapter(_settings(), transport=httpx.MockTransport(handler))
        with pytest.raises(ExecutionPolicyViolation):
            await adapter._execution_send(  # noqa: SLF001
                ExecutionOperation.OPEN_POSITION,
                "POST",
                "https://evil.example/positions/otc",
                2,
            )
        await adapter.aclose()

    asyncio.run(scenario())
    assert calls == 0


def test_redirect_is_not_followed() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path.endswith("/session"):
            return _login_response()
        calls += 1
        return httpx.Response(302, headers={"Location": "https://api.ig.com/gateway/deal"}, json={})

    async def scenario() -> None:
        adapter = IGDemoExecutionAdapter(_settings(), transport=httpx.MockTransport(handler))
        await adapter.login()
        request, _, _ = request_and_confirmation()
        with pytest.raises(ExecutionBrokerError):
            await adapter.submit_market_position(map_market_order(request, Decimal("1")))
        await adapter.aclose()

    asyncio.run(scenario())
    assert calls == 1
