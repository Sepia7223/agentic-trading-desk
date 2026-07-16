from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import os
import re
import subprocess
import sys
from collections.abc import Awaitable, Callable
from datetime import time as datetime_time
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from trading_desk.cli import _print_market_details, _redact_account_id
from trading_desk.cli import main as cli_main
from trading_desk.config import AppSettings, BrokerSettings, SafetySettings
from trading_desk.ig.client import IGDemoClient, _validate_optional_environment_indicator
from trading_desk.ig.errors import (
    IGAuthenticationError,
    IGConfigurationError,
    IGOAuthResponseValidationError,
    IGOAuthTokenExpiredError,
    IGRateLimitError,
    IGResponseValidationError,
    IGSessionMissingError,
    ReadOnlyPolicyViolation,
)
from trading_desk.ig.models import AccountType, MarketStatus, PriceResolution
from trading_desk.ig.policy import MARKET_DETAILS_VERSION, Operation

REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_BASE_PATH = "/gateway/deal"


def _run(awaitable: Awaitable[Any]) -> Any:
    return asyncio.run(awaitable)


def _settings(**overrides: object) -> AppSettings:
    broker_values: dict[str, object] = {
        "identifier": "test-identifier",
        "password": "test-password",
        "api_key": "test-api-key",
        "request_timeout_seconds": 5,
        "max_historical_price_points": 100,
    }
    broker_values.update(overrides)
    return AppSettings(broker=BrokerSettings.model_validate(broker_values))


_MISSING = object()
_ACCESS_TOKEN = "synthetic-oauth-access-token"
_REFRESH_TOKEN = "synthetic-oauth-refresh-token"


def _oauth_token(**overrides: object) -> dict[str, object]:
    token: dict[str, object] = {
        "access_token": _ACCESS_TOKEN,
        "refresh_token": _REFRESH_TOKEN,
        "token_type": "Bearer",
        "expires_in": "60",
        "scope": "profile",
    }
    token.update(overrides)
    return token


def _login_payload(environment: object = _MISSING) -> dict[str, object]:
    payload: dict[str, object] = {
        "currentAccountId": "DEMO_ACCOUNT",
        "clientId": "DEMO_CLIENT",
        "accountInfo": {
            "balance": 10000,
            "deposit": 0,
            "profitLoss": 0,
            "available": 10000,
        },
        "currencyIsoCode": "USD",
        "currencySymbol": "$",
        "timezoneOffset": 0,
        "lightstreamerEndpoint": "https://example.invalid",
        "oauthToken": _oauth_token(),
    }
    if environment is not _MISSING:
        payload["environment"] = environment
    return payload


def _login_response(environment: object = _MISSING) -> httpx.Response:
    return httpx.Response(200, json=_login_payload(environment))


def _route_handler(
    operation_response: Callable[[httpx.Request], httpx.Response],
    calls: list[httpx.Request] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        if request.method == "POST" and request.url.path == f"{DEMO_BASE_PATH}/session":
            return _login_response()
        if request.method == "DELETE" and request.url.path == f"{DEMO_BASE_PATH}/session":
            return httpx.Response(200)
        return operation_response(request)

    return handler


def test_package_import_does_not_require_credentials(tmp_path: Path) -> None:
    environment = os.environ.copy()
    for name in ("IG_IDENTIFIER", "IG_PASSWORD", "IG_API_KEY"):
        environment.pop(name, None)

    result = subprocess.run(
        [sys.executable, "-c", "import trading_desk; print('imported')"],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "imported"
    assert result.stderr == ""


def test_integration_command_rejects_missing_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ("IG_IDENTIFIER", "IG_PASSWORD", "IG_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    exit_code = cli_main(["ig", "accounts"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Environment: DEMO" in captured.out
    assert "Mode: READ_ONLY" in captured.out
    assert "missing required configuration: IG_IDENTIFIER" in captured.err


def test_login_uses_demo_gateway_version_three_and_documented_body() -> None:
    calls: list[httpx.Request] = []

    async def scenario() -> None:
        client = IGDemoClient(
            _settings(),
            transport=httpx.MockTransport(_route_handler(lambda _: httpx.Response(500), calls)),
        )
        summary = await client.login()
        assert summary.environment == "DEMO"
        assert summary.oauth.token_type == "Bearer"
        assert summary.oauth.expires_in == 60
        assert summary.oauth.scope == "profile"
        assert _ACCESS_TOKEN not in repr(summary)
        assert _REFRESH_TOKEN not in summary.model_dump_json()
        await client.aclose()

    _run(scenario())

    assert len(calls) == 1
    request = calls[0]
    assert request.method == "POST"
    assert str(request.url) == "https://demo-api.ig.com/gateway/deal/session"
    assert request.headers["Version"] == "3"
    assert request.headers["X-IG-API-KEY"] == "test-api-key"
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["Accept"] == "application/json; charset=UTF-8"
    assert json.loads(request.content) == {
        "identifier": "test-identifier",
        "password": "test-password",
    }


def test_oauth_login_without_environment_field_authenticates() -> None:
    async def scenario() -> None:
        client = IGDemoClient(
            _settings(), transport=httpx.MockTransport(lambda _: _login_response())
        )
        summary = await client.login()

        assert summary.account_id == "DEMO_ACCOUNT"
        assert summary.client_id == "DEMO_CLIENT"
        assert summary.environment == "DEMO"
        assert "environment" not in _login_payload()
        assert "authenticated=true" in repr(client)
        await client.aclose()

    _run(scenario())


def test_oauth_token_type_is_case_insensitive_and_scope_is_optional() -> None:
    payload = _login_payload()
    token = _oauth_token(token_type="bearer")
    del token["scope"]
    payload["oauthToken"] = token

    async def scenario() -> None:
        client = IGDemoClient(
            _settings(),
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
        )
        summary = await client.login()
        assert summary.oauth.token_type == "Bearer"
        assert summary.oauth.scope is None
        await client.aclose()

    _run(scenario())


def test_explicit_demo_environment_is_accepted_case_insensitively() -> None:
    async def scenario() -> None:
        for environment in ("DEMO", "demo", " Demo "):
            client = IGDemoClient(
                _settings(),
                transport=httpx.MockTransport(lambda _, value=environment: _login_response(value)),
            )
            assert (await client.login()).environment == "DEMO"
            await client.aclose()

    _run(scenario())


def test_authenticated_requests_use_only_oauth_headers() -> None:
    calls: list[httpx.Request] = []

    def operation(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {_ACCESS_TOKEN}"
        assert request.headers["IG-ACCOUNT-ID"] == "DEMO_ACCOUNT"
        assert request.headers["X-IG-API-KEY"] == "test-api-key"
        assert "CST" not in request.headers
        assert "X-SECURITY-TOKEN" not in request.headers
        return httpx.Response(200, json={"accounts": []})

    async def scenario() -> None:
        client = IGDemoClient(
            _settings(), transport=httpx.MockTransport(_route_handler(operation, calls))
        )
        await client.login()
        assert await client.get_accounts() == ()
        await client.aclose()

    _run(scenario())
    assert len(calls) == 2


@pytest.mark.parametrize(
    ("token_update", "missing_key"),
    [
        ({}, "oauthToken"),
        ({}, "access_token"),
        ({}, "refresh_token"),
        ({}, "token_type"),
        ({}, "expires_in"),
    ],
)
def test_missing_oauth_fields_fail_closed(
    token_update: dict[str, object], missing_key: str
) -> None:
    payload = _login_payload()
    if missing_key == "oauthToken":
        del payload[missing_key]
    else:
        token = _oauth_token(**token_update)
        del token[missing_key]
        payload["oauthToken"] = token

    _assert_oauth_login_fails_closed(payload)


@pytest.mark.parametrize(
    "token_update",
    [
        {"access_token": ""},
        {"access_token": "   "},
        {"refresh_token": ""},
        {"refresh_token": "   "},
        {"token_type": "Basic"},
        {"token_type": ""},
        {"expires_in": 0},
        {"expires_in": -1},
        {"expires_in": "nan"},
        {"expires_in": "inf"},
        {"expires_in": "invalid"},
        {"expires_in": True},
    ],
)
def test_invalid_oauth_token_values_fail_closed(token_update: dict[str, object]) -> None:
    payload = _login_payload()
    payload["oauthToken"] = _oauth_token(**token_update)
    _assert_oauth_login_fails_closed(payload)


@pytest.mark.parametrize("missing_field", ["currentAccountId", "clientId"])
def test_missing_required_login_identity_fails_closed(missing_field: str) -> None:
    payload = _login_payload()
    del payload[missing_field]
    _assert_oauth_login_fails_closed(payload)


def _assert_oauth_login_fails_closed(payload: dict[str, object]) -> None:
    async def scenario() -> None:
        client = IGDemoClient(
            _settings(),
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
        )
        with pytest.raises(IGOAuthResponseValidationError, match="OAuth login response"):
            await client.login()
        assert "authenticated=false" in repr(client)
        with pytest.raises(IGSessionMissingError):
            await client.get_accounts()
        await client.aclose()

    _run(scenario())


@pytest.mark.parametrize("environment", ["LIVE", "PROD", "PRODUCTION", "", "unknown", True])
def test_explicit_non_demo_login_responses_fail_closed(environment: object) -> None:
    async def scenario() -> None:
        client = IGDemoClient(
            _settings(), transport=httpx.MockTransport(lambda _: _login_response(environment))
        )
        with pytest.raises(IGAuthenticationError, match="unsafe environment"):
            await client.login()
        assert "authenticated=false" in repr(client)
        await client.aclose()

    _run(scenario())


def test_rerouting_environment_is_not_interpreted_as_environment() -> None:
    payload = _login_payload()
    payload["reroutingEnvironment"] = False

    async def scenario() -> None:
        client = IGDemoClient(
            _settings(),
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
        )
        assert (await client.login()).environment == "DEMO"
        await client.aclose()

    _run(scenario())


@pytest.mark.parametrize("environment", [_MISSING, "DEMO", "demo"])
def test_optional_environment_helper_accepts_missing_or_demo(environment: object) -> None:
    _validate_optional_environment_indicator(_login_payload(environment))


@pytest.mark.parametrize("environment", ["LIVE", "PROD", "PRODUCTION", "unknown", 1])
def test_optional_environment_helper_rejects_explicit_unsafe_values(environment: object) -> None:
    with pytest.raises(ValueError, match="not DEMO"):
        _validate_optional_environment_indicator(_login_payload(environment))


def test_malformed_login_json_fails_closed() -> None:
    async def scenario() -> None:
        client = IGDemoClient(
            _settings(), transport=httpx.MockTransport(lambda _: httpx.Response(200, text="bad"))
        )
        with pytest.raises(IGResponseValidationError):
            await client.login()
        assert "authenticated=false" in repr(client)
        await client.aclose()

    _run(scenario())


def test_login_redirect_is_not_treated_as_success() -> None:
    async def scenario() -> None:
        client = IGDemoClient(
            _settings(),
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    302,
                    json=_login_payload(),
                    headers={"Location": "https://example.invalid"},
                )
            ),
        )
        with pytest.raises(IGAuthenticationError, match="status=302"):
            await client.login()
        assert "authenticated=false" in repr(client)
        await client.aclose()

    _run(scenario())


def test_oauth_tokens_are_private_and_redacted_everywhere(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    async def scenario() -> None:
        client = IGDemoClient(
            _settings(), transport=httpx.MockTransport(lambda _: _login_response())
        )
        summary = await client.login()
        assert client._access_token is not None  # noqa: SLF001 - private-state safety check.
        assert client._refresh_token is not None  # noqa: SLF001 - private-state safety check.
        combined = f"{client!r} {client.__dict__!r} {summary!r} {summary.model_dump_json()}"
        assert _ACCESS_TOKEN not in combined
        assert _REFRESH_TOKEN not in combined
        assert "DEMO_ACCOUNT" not in repr(client)
        assert "authenticated=true" in repr(client)
        await client.aclose()

    _run(scenario())
    captured = capsys.readouterr()
    combined_output = captured.out + captured.err + caplog.text
    assert _ACCESS_TOKEN not in combined_output
    assert _REFRESH_TOKEN not in combined_output


@pytest.mark.parametrize(
    ("account_id", "redacted"),
    [("DEMO_ACCOUNT", "***OUNT"), ("12345", "***2345"), ("1234", "***")],
)
def test_cli_redacts_complete_account_ids(account_id: str, redacted: str) -> None:
    result = _redact_account_id(account_id)

    assert result == redacted
    assert result != account_id


def test_failed_login_redacts_oauth_values_and_clears_state(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = _login_payload("LIVE")

    async def scenario() -> None:
        client = IGDemoClient(
            _settings(),
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
        )
        with pytest.raises(IGAuthenticationError) as captured_error:
            await client.login()
        combined = f"{captured_error.value!s} {client!r} {client.__dict__!r}"
        assert _ACCESS_TOKEN not in combined
        assert _REFRESH_TOKEN not in combined
        assert "authenticated=false" in repr(client)
        await client.aclose()

    _run(scenario())
    captured = capsys.readouterr()
    output = captured.out + captured.err + caplog.text
    assert _ACCESS_TOKEN not in output
    assert _REFRESH_TOKEN not in output


def test_expired_oauth_token_blocks_transport_and_clears_session() -> None:
    calls: list[httpx.Request] = []
    now = [100.0]

    async def scenario() -> None:
        client = IGDemoClient(
            _settings(oauth_expiry_safety_margin_seconds=5),
            transport=httpx.MockTransport(
                _route_handler(lambda _: httpx.Response(200, json={"accounts": []}), calls)
            ),
            clock=lambda: now[0],
        )
        await client.login()
        now[0] = 155.0
        with pytest.raises(IGOAuthTokenExpiredError, match="access token expired"):
            await client.get_accounts()
        assert "authenticated=false" in repr(client)
        await client.aclose()

    _run(scenario())
    assert len(calls) == 1


def test_logout_always_clears_oauth_state_when_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return _login_response()
        return httpx.Response(500, json={"errorCode": "error.system.error"})

    async def scenario() -> None:
        client = IGDemoClient(_settings(), transport=httpx.MockTransport(handler))
        await client.login()
        with pytest.raises(Exception, match="operation=logout"):
            await client.logout()
        assert "authenticated=false" in repr(client)
        with pytest.raises(IGSessionMissingError):
            await client.get_accounts()
        await client.aclose()

    _run(scenario())


def test_oauth_logout_uses_delete_session_version_one() -> None:
    calls: list[httpx.Request] = []

    async def scenario() -> None:
        client = IGDemoClient(
            _settings(),
            transport=httpx.MockTransport(_route_handler(lambda _: httpx.Response(500), calls)),
        )
        await client.login()
        await client.logout()
        await client.aclose()

    _run(scenario())
    request = calls[-1]
    assert request.method == "DELETE"
    assert request.url.path == f"{DEMO_BASE_PATH}/session"
    assert request.headers["Version"] == "1"
    assert request.headers["Authorization"] == f"Bearer {_ACCESS_TOKEN}"
    assert request.headers["IG-ACCOUNT-ID"] == "DEMO_ACCOUNT"
    assert "CST" not in request.headers
    assert "X-SECURITY-TOKEN" not in request.headers


def test_authenticated_requests_fail_without_a_session_before_transport() -> None:
    transport_calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal transport_calls
        transport_calls += 1
        return httpx.Response(200, json={"accounts": []})

    async def scenario() -> None:
        client = IGDemoClient(_settings(), transport=httpx.MockTransport(handler))
        with pytest.raises(IGSessionMissingError):
            await client.get_accounts()
        await client.aclose()

    _run(scenario())
    assert transport_calls == 0


def test_accounts_parse_into_typed_models() -> None:
    payload = {
        "accounts": [
            {
                "accountId": "ABC123",
                "accountName": "Demo CFD",
                "accountType": "CFD",
                "preferred": True,
                "currency": "USD",
                "balance": {
                    "balance": 10000.25,
                    "deposit": 1000,
                    "profitLoss": -12.5,
                    "available": 8987.75,
                },
            }
        ]
    }

    def operation(request: httpx.Request) -> httpx.Response:
        assert request.headers["Version"] == "1"
        return httpx.Response(200, json=payload)

    async def scenario() -> None:
        client = IGDemoClient(
            _settings(),
            transport=httpx.MockTransport(_route_handler(operation)),
        )
        await client.login()
        accounts = await client.get_accounts()
        assert accounts[0].account_id == "ABC123"
        assert accounts[0].account_type.value == "CFD"
        assert accounts[0].balance.available_funds == Decimal("8987.75")
        await client.aclose()

    _run(scenario())


def test_unknown_future_enum_values_are_preserved() -> None:
    assert AccountType("FUTURE_ACCOUNT_TYPE").value == "FUTURE_ACCOUNT_TYPE"
    assert MarketStatus("FUTURE_MARKET_STATUS").value == "FUTURE_MARKET_STATUS"


def test_open_positions_use_version_two_and_parse_both_sections() -> None:
    calls: list[httpx.Request] = []
    payload = {
        "positions": [
            {
                "position": {
                    "dealId": "D1",
                    "dealReference": "REF1",
                    "direction": "BUY",
                    "size": 2,
                    "level": 1.085,
                    "stopLevel": 1.07,
                    "limitLevel": 1.1,
                    "controlledRisk": False,
                    "currency": "USD",
                    "createdDateUTC": "2026-07-13T12:00:00Z",
                },
                "market": {
                    "epic": "CS.D.EURUSD.CFD.IP",
                    "instrumentName": "EUR/USD",
                    "bid": 1.086,
                    "offer": 1.0862,
                    "marketStatus": "TRADEABLE",
                    "updateTimeUTC": "2026-07-13T12:01:00Z",
                },
            }
        ]
    }

    def operation(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/positions")
        assert request.headers["Version"] == "2"
        return httpx.Response(200, json=payload)

    async def scenario() -> None:
        client = IGDemoClient(
            _settings(), transport=httpx.MockTransport(_route_handler(operation, calls))
        )
        await client.login()
        positions = await client.get_open_positions()
        assert positions[0].deal_id == "D1"
        assert positions[0].market.epic == "CS.D.EURUSD.CFD.IP"
        assert positions[0].opening_level == Decimal("1.085")
        await client.aclose()

    _run(scenario())


def test_market_search_validates_and_parses_results() -> None:
    payload = {
        "markets": [
            {
                "epic": "CS.D.EURUSD.CFD.IP",
                "instrumentName": "EUR/USD",
                "instrumentType": "CURRENCIES",
                "marketStatus": "TRADEABLE",
                "bid": 1.08,
                "offer": 1.081,
                "expiry": "-",
            }
        ]
    }

    def operation(request: httpx.Request) -> httpx.Response:
        assert request.url.params["searchTerm"] == "EUR/USD"
        assert request.headers["Version"] == "1"
        return httpx.Response(200, json=payload)

    async def scenario() -> None:
        client = IGDemoClient(_settings(), transport=httpx.MockTransport(_route_handler(operation)))
        await client.login()
        markets = await client.search_markets(" EUR/USD ")
        assert markets[0].epic == "CS.D.EURUSD.CFD.IP"
        assert markets[0].instrument_name == "EUR/USD"
        with pytest.raises(ReadOnlyPolicyViolation):
            await client.search_markets("\n")
        await client.aclose()

    _run(scenario())


def _market_details_payload(update_time: object = "12:34:56") -> dict[str, object]:
    snapshot: dict[str, object] = {
        "marketStatus": "TRADEABLE",
        "bid": 1.10001,
        "offer": 1.10009,
    }
    if update_time is not _MISSING:
        snapshot["updateTime"] = update_time
    return {
        "instrument": {
            "epic": "CS.D.EURUSD.CFD.IP",
            "name": "EUR/USD",
            "type": "CURRENCIES",
            "expiry": "-",
            "controlledRiskAllowed": True,
            "lotSize": 1,
            "contractSize": "100000",
            "valueOfOnePip": "10",
            "currencies": [{"code": "USD", "isDefault": True}],
        },
        "snapshot": snapshot,
        "dealingRules": {
            "minDealSize": {"unit": "POINTS", "value": 0.5},
            "minNormalStopOrLimitDistance": {"unit": "POINTS", "value": 5},
            "maxStopOrLimitDistance": {"unit": "PERCENTAGE", "value": 90},
        },
    }


def test_market_details_v3_parses_time_of_day_and_rules(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = _market_details_payload()

    def operation(request: httpx.Request) -> httpx.Response:
        assert request.headers["Version"] == str(MARKET_DETAILS_VERSION)
        return httpx.Response(200, json=payload)

    async def scenario() -> None:
        client = IGDemoClient(_settings(), transport=httpx.MockTransport(_route_handler(operation)))
        await client.login()
        market = await client.get_market_details("CS.D.EURUSD.CFD.IP")
        assert market.epic == "CS.D.EURUSD.CFD.IP"
        assert market.instrument_type.value == "CURRENCIES"
        assert market.market_status.value == "TRADEABLE"
        assert market.offer == Decimal("1.10009")
        assert market.currency_code == "USD"
        assert market.contract_size == Decimal("100000")
        assert market.value_of_one_pip == Decimal("10")
        assert isinstance(market.update_time, datetime_time)
        assert market.update_time == datetime_time(12, 34, 56)
        assert market.update_time.tzinfo is None
        assert "update_time_utc" not in type(market).model_fields
        assert market.min_deal_size is not None
        assert market.min_deal_size.value == Decimal("0.5")
        _print_market_details(market)
        await client.aclose()

    _run(scenario())
    assert "Updated: 12:34:56" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("raw_time", "expected"),
    [
        ("12:34:56.789", datetime_time(12, 34, 56, 789000)),
        ("00:00:00.000001", datetime_time(0, 0, 0, 1)),
    ],
)
def test_market_details_fractional_update_time_parses(
    raw_time: str, expected: datetime_time
) -> None:
    async def scenario() -> None:
        client = IGDemoClient(
            _settings(),
            transport=httpx.MockTransport(
                _route_handler(
                    lambda _: httpx.Response(200, json=_market_details_payload(raw_time))
                )
            ),
        )
        await client.login()
        market = await client.get_market_details("CS.D.EURUSD.CFD.IP")
        assert market.update_time == expected
        await client.aclose()

    _run(scenario())


def test_missing_market_details_update_time_is_none() -> None:
    async def scenario() -> None:
        client = IGDemoClient(
            _settings(),
            transport=httpx.MockTransport(
                _route_handler(
                    lambda _: httpx.Response(200, json=_market_details_payload(_MISSING))
                )
            ),
        )
        await client.login()
        market = await client.get_market_details("CS.D.EURUSD.CFD.IP")
        assert market.update_time is None
        await client.aclose()

    _run(scenario())


@pytest.mark.parametrize(
    "raw_time",
    [
        "",
        "24:00:00",
        "12:60:00",
        "12:34:60",
        "2026-07-13T12:34:56Z",
        "12:34",
        "1:02:03",
        123456,
    ],
)
def test_invalid_market_details_time_has_safe_diagnostic(raw_time: object) -> None:
    payload = _market_details_payload(raw_time)
    payload["unrelatedSensitiveValue"] = "must-not-appear"

    async def scenario() -> None:
        client = IGDemoClient(
            _settings(),
            transport=httpx.MockTransport(
                _route_handler(lambda _: httpx.Response(200, json=payload))
            ),
        )
        await client.login()
        with pytest.raises(IGResponseValidationError) as captured:
            await client.get_market_details("CS.D.EURUSD.CFD.IP")
        diagnostic = str(captured.value)
        assert "operation=market_details" in diagnostic
        assert "field=snapshot.updateTime" in diagnostic
        assert "reason=invalid time-of-day" in diagnostic
        assert "must-not-appear" not in diagnostic
        if str(raw_time):
            assert str(raw_time) not in diagnostic
        await client.aclose()

    _run(scenario())


@pytest.mark.parametrize("missing_structure", ["instrument", "snapshot", "dealingRules"])
def test_missing_market_details_structures_fail_closed(missing_structure: str) -> None:
    payload = _market_details_payload()
    del payload[missing_structure]

    async def scenario() -> None:
        client = IGDemoClient(
            _settings(),
            transport=httpx.MockTransport(
                _route_handler(lambda _: httpx.Response(200, json=payload))
            ),
        )
        await client.login()
        with pytest.raises(IGResponseValidationError) as captured:
            await client.get_market_details("CS.D.EURUSD.CFD.IP")
        assert f"field={missing_structure}" in str(captured.value)
        assert "reason=missing or invalid object" in str(captured.value)
        await client.aclose()

    _run(scenario())


def test_malformed_market_details_dealing_rule_fails_closed() -> None:
    payload = _market_details_payload()
    payload["dealingRules"] = {"minDealSize": {"unit": "POINTS", "value": "bad"}}

    async def scenario() -> None:
        client = IGDemoClient(
            _settings(),
            transport=httpx.MockTransport(
                _route_handler(lambda _: httpx.Response(200, json=payload))
            ),
        )
        await client.login()
        with pytest.raises(IGResponseValidationError):
            await client.get_market_details("CS.D.EURUSD.CFD.IP")
        await client.aclose()

    _run(scenario())


@pytest.mark.parametrize("status", ["TRADEABLE", "CLOSED", "OFFLINE", "FUTURE_STATUS"])
def test_market_details_enums_are_forward_compatible(status: str) -> None:
    payload = _market_details_payload()
    snapshot = payload["snapshot"]
    instrument = payload["instrument"]
    assert isinstance(snapshot, dict)
    assert isinstance(instrument, dict)
    snapshot["marketStatus"] = status
    instrument["type"] = "FUTURE_INSTRUMENT" if status == "FUTURE_STATUS" else "CURRENCIES"

    async def scenario() -> None:
        client = IGDemoClient(
            _settings(),
            transport=httpx.MockTransport(
                _route_handler(lambda _: httpx.Response(200, json=payload))
            ),
        )
        await client.login()
        market = await client.get_market_details("CS.D.EURUSD.CFD.IP")
        assert market.market_status.value == status
        if status == "FUTURE_STATUS":
            assert market.instrument_type.value == "FUTURE_INSTRUMENT"
        await client.aclose()

    _run(scenario())


def _prices_payload(*, missing_close_ask: bool = False) -> dict[str, object]:
    close: dict[str, object] = {"bid": 104, "ask": 106, "lastTraded": 105}
    if missing_close_ask:
        close.pop("ask")
    return {
        "prices": [
            {
                "snapshotTimeUTC": "2026-07-13T12:00:00Z",
                "openPrice": {"bid": 100, "ask": 102},
                "highPrice": {"bid": 108, "ask": 110},
                "lowPrice": {"bid": 98, "ask": 100},
                "closePrice": close,
                "lastTradedVolume": 1234,
            }
        ],
        "metadata": {
            "pageData": {"pageNumber": 2, "pageSize": 1, "totalPages": 4},
            "allowance": {
                "allowanceExpiry": 60,
                "remainingAllowance": 99,
                "totalAllowance": 100,
            },
        },
    }


@pytest.mark.parametrize("resolution", list(PriceResolution))
def test_supported_price_requests_are_constructed_correctly(resolution: PriceResolution) -> None:
    def operation(request: httpx.Request) -> httpx.Response:
        assert request.url.params["resolution"] == resolution.value
        assert request.url.params["max"] == "20"
        assert request.url.params["pageNumber"] == "2"
        assert request.headers["Version"] == "3"
        return httpx.Response(200, json=_prices_payload())

    async def scenario() -> None:
        client = IGDemoClient(_settings(), transport=httpx.MockTransport(_route_handler(operation)))
        await client.login()
        await client.get_historical_prices(
            "CS.D.EURUSD.CFD.IP", resolution=resolution, max_points=20, page_number=2
        )
        await client.aclose()

    _run(scenario())


def test_historical_prices_normalize_midpoints_paging_and_allowance() -> None:
    async def scenario() -> None:
        client = IGDemoClient(
            _settings(),
            transport=httpx.MockTransport(
                _route_handler(lambda _: httpx.Response(200, json=_prices_payload()))
            ),
        )
        await client.login()
        page = await client.get_historical_prices("CS.D.EURUSD.CFD.IP", max_points=20)
        bar = page.bars[0]
        assert bar.open.bid == Decimal("100")
        assert bar.open.ask == Decimal("102")
        assert bar.midpoint_open == Decimal("101")
        assert bar.midpoint_high == Decimal("109")
        assert bar.midpoint_low == Decimal("99")
        assert bar.midpoint_close == Decimal("105")
        assert bar.last_traded == Decimal("105")
        assert bar.last_traded_volume == Decimal("1234")
        assert page.strategy_ready_closes == (Decimal("105"),)
        assert page.pagination.model_dump() == {
            "page_number": 2,
            "page_size": 1,
            "total_pages": 4,
        }
        assert page.allowance.model_dump() == {
            "allowance_expiry_seconds": 60,
            "remaining_allowance": 99,
            "total_allowance": 100,
        }
        await client.aclose()

    _run(scenario())


def test_incomplete_close_is_preserved_but_excluded_from_strategy_series() -> None:
    async def scenario() -> None:
        client = IGDemoClient(
            _settings(),
            transport=httpx.MockTransport(
                _route_handler(
                    lambda _: httpx.Response(200, json=_prices_payload(missing_close_ask=True))
                )
            ),
        )
        await client.login()
        page = await client.get_historical_prices("CS.D.EURUSD.CFD.IP", max_points=20)
        assert len(page.bars) == 1
        assert page.bars[0].close.bid == Decimal("104")
        assert page.bars[0].close.ask is None
        assert page.bars[0].valid_for_strategy is False
        assert page.bars[0].validation_reason == "close ask missing"
        assert page.strategy_ready_closes == ()
        await client.aclose()

    _run(scenario())


def test_401_errors_map_safely() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"errorCode": "error.security.client-token-invalid"},
            headers={"X-REQUEST-ID": "request-401"},
        )

    async def scenario() -> None:
        client = IGDemoClient(_settings(), transport=httpx.MockTransport(handler))
        with pytest.raises(IGAuthenticationError) as error:
            await client.login()
        diagnostic = str(error.value)
        assert "status=401" in diagnostic
        assert "error.security.client-token-invalid" in diagnostic
        assert "request-401" in diagnostic
        assert "test-password" not in diagnostic
        await client.aclose()

    _run(scenario())


def test_allowance_403_errors_map_to_rate_limit() -> None:
    def operation(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"errorCode": "error.public-api.exceeded-account-allowance"},
        )

    async def scenario() -> None:
        client = IGDemoClient(_settings(), transport=httpx.MockTransport(_route_handler(operation)))
        await client.login()
        with pytest.raises(IGRateLimitError, match="allowance exhausted"):
            await client.get_accounts()
        await client.aclose()

    _run(scenario())


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not-json"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={"accounts": "not-a-list"}),
    ],
)
def test_malformed_responses_fail_closed(response: httpx.Response) -> None:
    async def scenario() -> None:
        client = IGDemoClient(
            _settings(), transport=httpx.MockTransport(_route_handler(lambda _: response))
        )
        await client.login()
        with pytest.raises(IGResponseValidationError):
            await client.get_accounts()
        await client.aclose()

    _run(scenario())


@pytest.mark.parametrize(
    ("operation", "method", "path", "version"),
    [
        (Operation.ACCOUNTS, "POST", "/accounts", 1),
        (Operation.ACCOUNTS, "GET", "/positions", 1),
        (Operation.ACCOUNTS, "GET", "/accounts", 2),
        (Operation.ACCOUNTS, "GET", "https://evil.example/accounts", 1),
        (Operation.ACCOUNTS, "GET", "//evil.example/accounts", 1),
        (Operation.ACCOUNTS, "GET", "/accounts/../positions", 1),
        (Operation.ACCOUNTS, "GET", "/accounts/%2e%2e/positions", 1),
        (Operation.ACCOUNTS, "GET", "/accounts//extra", 1),
        (Operation.ACCOUNTS, "GET", "/accounts/", 1),
        (Operation.ACCOUNTS, "GET", "/accounts?switch=true", 1),
        (Operation.ACCOUNTS, "GET", "/accounts#fragment", 1),
        (Operation.MARKET_DETAILS, "GET", "/markets/", MARKET_DETAILS_VERSION),
        (Operation.MARKET_DETAILS, "GET", "/markets/BAD%2FEPIC", MARKET_DETAILS_VERSION),
        (Operation.MARKET_DETAILS, "GET", "/markets/../session", MARKET_DETAILS_VERSION),
    ],
)
def test_non_allowlisted_requests_are_blocked_before_transport(
    operation: Operation, method: str, path: str, version: int
) -> None:
    transport_calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal transport_calls
        transport_calls += 1
        return httpx.Response(500)

    async def scenario() -> None:
        client = IGDemoClient(_settings(), transport=httpx.MockTransport(handler))
        with pytest.raises(ReadOnlyPolicyViolation):
            await client._send(  # noqa: SLF001 - verifies the internal policy boundary directly.
                operation, method, path, version, expect_json=True
            )
        await client.aclose()

    _run(scenario())
    assert transport_calls == 0


@pytest.mark.parametrize("epic", ["", "../session", "ABC/DEF", "ABC%2FDEF", "A" * 81])
def test_malformed_epics_are_rejected_before_transport(epic: str) -> None:
    transport_calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal transport_calls
        transport_calls += 1
        return httpx.Response(500)

    async def scenario() -> None:
        client = IGDemoClient(_settings(), transport=httpx.MockTransport(handler))
        with pytest.raises(ReadOnlyPolicyViolation):
            await client.get_market_details(epic)
        await client.aclose()

    _run(scenario())
    assert transport_calls == 0


def test_client_exposes_no_unrestricted_public_request_method() -> None:
    public_methods = {
        name
        for name, member in inspect.getmembers(IGDemoClient, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    assert "request" not in public_methods
    assert "send" not in public_methods
    assert public_methods == {
        "aclose",
        "get_accounts",
        "get_historical_prices",
        "get_market_details",
        "get_open_positions",
        "login",
        "logout",
        "search_markets",
    }


@pytest.mark.parametrize(
    ("broker_update", "safety_update"),
    [
        ({"broker_environment": "LIVE"}, {}),
        ({"base_url": "https://api.ig.com/gateway/deal"}, {}),
        ({}, {"operating_mode": "WRITE"}),
        ({}, {"live_trading_allowed": True}),
        ({}, {"automatic_execution_enabled": True}),
    ],
)
def test_client_refuses_unsafe_runtime_boundaries(
    broker_update: dict[str, object], safety_update: dict[str, object]
) -> None:
    safe_settings = _settings()
    broker_data = safe_settings.broker.model_dump()
    broker_data.update(broker_update)
    safety_data = safe_settings.safety.model_dump()
    safety_data.update(safety_update)
    unsafe = AppSettings.model_construct(
        broker=BrokerSettings.model_construct(**broker_data),
        safety=SafetySettings.model_construct(**safety_data),
        ai=safe_settings.ai,
        database_url=safe_settings.database_url,
    )

    with pytest.raises(IGConfigurationError):
        IGDemoClient(unsafe, transport=httpx.MockTransport(lambda _: httpx.Response(500)))


def test_source_contains_no_execution_endpoints_or_order_operation_methods() -> None:
    source_root = REPO_ROOT / "src"
    read_only_files = (
        source_root / "trading_desk" / "ig" / "client.py",
        source_root / "trading_desk" / "ig" / "policy.py",
        source_root / "trading_desk" / "ports" / "broker.py",
    )
    source = "\n".join(path.read_text(encoding="utf-8") for path in read_only_files).lower()
    forbidden_endpoints = (
        "/positions/otc",
        "/working-orders/otc",
        "/workingorders/otc",
        "/confirms/",
    )
    assert all(endpoint not in source for endpoint in forbidden_endpoints)

    prohibited_method = re.compile(
        r"(?:async\s+)?def\s+(?:place|create|update|close|execute|submit|preview)_.*order"
    )
    assert prohibited_method.search(source) is None
    assert "switch_account" not in source

    client_text = (source_root / "trading_desk" / "ig" / "client.py").read_text(encoding="utf-8")
    assert '"PUT"' not in client_text

    client_source = importlib.import_module("trading_desk.ig.client")
    assert client_source is not None


def test_price_limit_and_resolution_fail_before_transport() -> None:
    transport_calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal transport_calls
        transport_calls += 1
        return httpx.Response(500)

    async def scenario() -> None:
        client = IGDemoClient(_settings(), transport=httpx.MockTransport(handler))
        with pytest.raises(IGConfigurationError):
            await client.get_historical_prices("VALID.EPIC", max_points=101)
        with pytest.raises(IGConfigurationError):
            await client.get_historical_prices("VALID.EPIC", resolution="MINUTE")
        await client.aclose()

    _run(scenario())
    assert transport_calls == 0
