from __future__ import annotations

import asyncio
import importlib
import inspect
import os
import re
import subprocess
import sys
from collections.abc import Awaitable, Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from trading_desk.cli import main as cli_main
from trading_desk.config import AppSettings, BrokerSettings, SafetySettings
from trading_desk.ig.client import IGDemoClient, _validate_optional_environment_indicator
from trading_desk.ig.errors import (
    IGAuthenticationError,
    IGConfigurationError,
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
    }
    if environment is not _MISSING:
        payload["environment"] = environment
    return payload


def _login_response(environment: object = _MISSING) -> httpx.Response:
    return httpx.Response(
        200,
        json=_login_payload(environment),
        headers={"CST": "test-cst", "X-SECURITY-TOKEN": "test-security-token"},
    )


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


def test_login_uses_demo_gateway_version_and_safe_headers() -> None:
    calls: list[httpx.Request] = []

    async def scenario() -> None:
        client = IGDemoClient(
            _settings(),
            transport=httpx.MockTransport(_route_handler(lambda _: httpx.Response(500), calls)),
        )
        summary = await client.login()
        await client.aclose()
        assert summary.environment == "DEMO"

    _run(scenario())

    assert len(calls) == 1
    request = calls[0]
    assert request.method == "POST"
    assert str(request.url) == "https://demo-api.ig.com/gateway/deal/session"
    assert request.headers["Version"] == "2"
    assert request.headers["X-IG-API-KEY"] == "test-api-key"
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["Accept"] == "application/json; charset=UTF-8"


def test_session_v2_without_environment_field_authenticates() -> None:
    async def scenario() -> None:
        client = IGDemoClient(
            _settings(), transport=httpx.MockTransport(lambda _: _login_response())
        )
        summary = await client.login()

        assert summary.account_id == "DEMO_ACCOUNT"
        assert summary.client_id == "DEMO_CLIENT"
        assert summary.environment == "DEMO"
        assert "environment" not in _login_payload()
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


def test_login_captures_both_tokens_for_authenticated_requests() -> None:
    calls: list[httpx.Request] = []

    def operation(request: httpx.Request) -> httpx.Response:
        assert request.headers["CST"] == "test-cst"
        assert request.headers["X-SECURITY-TOKEN"] == "test-security-token"
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
    "headers",
    [
        {"CST": "test-cst"},
        {"X-SECURITY-TOKEN": "test-security-token"},
        {"CST": "   ", "X-SECURITY-TOKEN": "test-security-token"},
        {"CST": "test-cst", "X-SECURITY-TOKEN": "   "},
    ],
)
def test_missing_authentication_headers_fail_closed(headers: dict[str, str]) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_login_payload(), headers=headers)

    async def scenario() -> None:
        client = IGDemoClient(_settings(), transport=httpx.MockTransport(handler))
        with pytest.raises(IGAuthenticationError, match="omitted required session headers"):
            await client.login()
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
        with pytest.raises(IGSessionMissingError):
            await client.get_accounts()
        await client.aclose()

    _run(scenario())


def test_rerouting_environment_is_not_interpreted_as_an_environment_declaration() -> None:
    payload = _login_payload()
    payload["reroutingEnvironment"] = False

    async def scenario() -> None:
        client = IGDemoClient(
            _settings(),
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json=payload,
                    headers={"CST": "test-cst", "X-SECURITY-TOKEN": "test-security-token"},
                )
            ),
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


@pytest.mark.parametrize("missing_field", ["currentAccountId", "clientId"])
def test_missing_required_login_identity_fails_closed(missing_field: str) -> None:
    payload = _login_payload()
    del payload[missing_field]

    async def scenario() -> None:
        client = IGDemoClient(
            _settings(),
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json=payload,
                    headers={"CST": "test-cst", "X-SECURITY-TOKEN": "test-security-token"},
                )
            ),
        )
        with pytest.raises(IGResponseValidationError, match="login response was malformed"):
            await client.login()
        assert "authenticated=False" in repr(client)
        with pytest.raises(IGSessionMissingError):
            await client.get_accounts()
        await client.aclose()

    _run(scenario())


def test_malformed_login_json_fails_closed() -> None:
    async def scenario() -> None:
        client = IGDemoClient(
            _settings(),
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    text="not-json",
                    headers={"CST": "test-cst", "X-SECURITY-TOKEN": "test-security-token"},
                )
            ),
        )
        with pytest.raises(IGResponseValidationError):
            await client.login()
        assert "authenticated=False" in repr(client)
        with pytest.raises(IGSessionMissingError):
            await client.get_accounts()
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
                    headers={
                        "Location": "https://example.invalid",
                        "CST": "test-cst",
                        "X-SECURITY-TOKEN": "test-security-token",
                    },
                )
            ),
        )
        with pytest.raises(IGAuthenticationError, match="status=302"):
            await client.login()
        assert "authenticated=False" in repr(client)
        await client.aclose()

    _run(scenario())


def test_failed_login_redacts_authentication_headers_everywhere(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    cst = "synthetic-cst-for-redaction"
    security_token = "synthetic-security-token-for-redaction"

    async def scenario() -> None:
        client = IGDemoClient(
            _settings(),
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json=_login_payload("LIVE"),
                    headers={"CST": cst, "X-SECURITY-TOKEN": security_token},
                )
            ),
        )
        with pytest.raises(IGAuthenticationError) as captured_error:
            await client.login()
        safe_text = f"{captured_error.value!s} {client!r} {client.__dict__!r}"
        assert cst not in safe_text
        assert security_token not in safe_text
        assert "authenticated=False" in repr(client)
        await client.aclose()

    _run(scenario())
    captured = capsys.readouterr()
    output = captured.out + captured.err + caplog.text
    assert cst not in output
    assert security_token not in output


def test_tokens_are_absent_from_logs_exceptions_representations_and_output(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    async def scenario() -> None:
        client = IGDemoClient(
            _settings(), transport=httpx.MockTransport(lambda _: _login_response())
        )
        await client.login()
        combined_repr = f"{client!r} {client.__dict__!r}"
        assert "test-cst" not in combined_repr
        assert "test-security-token" not in combined_repr
        await client.aclose()

    _run(scenario())
    captured = capsys.readouterr()
    combined_output = captured.out + captured.err + caplog.text
    assert "test-cst" not in combined_output
    assert "test-security-token" not in combined_output


def test_logout_always_clears_tokens_when_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return _login_response()
        return httpx.Response(500, json={"errorCode": "error.system.error"})

    async def scenario() -> None:
        client = IGDemoClient(_settings(), transport=httpx.MockTransport(handler))
        await client.login()
        with pytest.raises(Exception, match="operation=logout"):
            await client.logout()
        with pytest.raises(IGSessionMissingError):
            await client.get_accounts()
        assert "authenticated=False" in repr(client)
        await client.aclose()

    _run(scenario())


def test_logout_uses_delete_session_version_one() -> None:
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
    assert calls[-1].method == "DELETE"
    assert calls[-1].url.path == f"{DEMO_BASE_PATH}/session"
    assert calls[-1].headers["Version"] == "1"


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


def test_market_details_use_isolated_version_and_parse_rules() -> None:
    payload = {
        "instrument": {
            "epic": "CS.D.EURUSD.CFD.IP",
            "name": "EUR/USD",
            "type": "CURRENCIES",
            "expiry": "-",
            "controlledRiskAllowed": True,
        },
        "snapshot": {
            "marketStatus": "TRADEABLE",
            "bid": 1.08,
            "offer": 1.081,
            "updateTimeUTC": "2026-07-13T12:00:00Z",
        },
        "dealingRules": {
            "minDealSize": {"value": 0.5, "unit": "POINTS"},
            "minNormalStopOrLimitDistance": {"value": 5, "unit": "POINTS"},
            "maxStopOrLimitDistance": {"value": 100, "unit": "POINTS"},
        },
    }

    def operation(request: httpx.Request) -> httpx.Response:
        assert request.headers["Version"] == str(MARKET_DETAILS_VERSION)
        return httpx.Response(200, json=payload)

    async def scenario() -> None:
        client = IGDemoClient(_settings(), transport=httpx.MockTransport(_route_handler(operation)))
        await client.login()
        market = await client.get_market_details("CS.D.EURUSD.CFD.IP")
        assert market.epic == "CS.D.EURUSD.CFD.IP"
        assert market.min_deal_size is not None
        assert market.min_deal_size.value == Decimal("0.5")
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
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(source_root.rglob("*.py"))
    ).lower()
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
