from __future__ import annotations

import pytest
from pydantic import ValidationError

from trading_desk.config import (
    IG_DEMO_BASE_URL,
    AppSettings,
    BrokerEnvironment,
    BrokerSettings,
    OperatingMode,
    SafetySettings,
)


def test_safety_defaults_are_demo_read_only_and_execution_disabled() -> None:
    settings = AppSettings()

    assert settings.broker.broker_environment is BrokerEnvironment.DEMO
    assert settings.safety.operating_mode is OperatingMode.READ_ONLY
    assert settings.safety.live_trading_allowed is False
    assert settings.safety.automatic_execution_enabled is False
    assert settings.broker.oauth_expiry_safety_margin_seconds == 5


def test_settings_are_immutable() -> None:
    settings = AppSettings()

    with pytest.raises(ValidationError):
        settings.safety.live_trading_allowed = True


def test_live_trading_and_automatic_execution_are_rejected() -> None:
    with pytest.raises(ValidationError, match="live trading is disabled"):
        SafetySettings(live_trading_allowed=True)

    with pytest.raises(ValidationError, match="requires CONTROLLED_EXECUTION"):
        SafetySettings(automatic_execution_enabled=True)

    enabled = SafetySettings(
        operating_mode=OperatingMode.CONTROLLED_EXECUTION,
        automatic_execution_enabled=True,
    )
    assert enabled.live_trading_allowed is False


@pytest.mark.parametrize(
    "base_url",
    [
        IG_DEMO_BASE_URL,
        "https://demo-api.ig.com:443/gateway/deal",
    ],
)
def test_exact_ig_demo_url_is_accepted_and_normalized(base_url: str) -> None:
    assert BrokerSettings(base_url=base_url).base_url == IG_DEMO_BASE_URL


@pytest.mark.parametrize(
    "base_url",
    [
        "http://demo-api.ig.com/gateway/deal",
        "https://api.ig.com/gateway/deal",
        "https://demo-api.ig.com.evil.example/gateway/deal",
        "https://evil-demo.example/gateway/deal",
        "https://demo-api.ig.com/wrong/path",
        "https://demo-api.ig.com/gateway/deal?test=true",
        "https://demo-api.ig.com/gateway/deal#fragment",
        "https://user:password@demo-api.ig.com/gateway/deal",
        "https://demo-api.ig.com:444/gateway/deal",
        "https://demo-api.ig.com/gateway/%2e%2e/deal",
        "https://demo-api.ig.com/gateway%2Fdeal",
        "https://demo-api.ig.com//gateway/deal",
        "https://demo-api.ig.com/gateway/deal/",
        "https://demo-api.ig.com/gateway/deal/../deal",
        "https://demo-api.ig.com/gateway/deal%2Fextra",
        "https://demo-api.ig.com:invalid/gateway/deal",
    ],
)
def test_incorrect_or_malicious_ig_urls_are_rejected(base_url: str) -> None:
    with pytest.raises(ValidationError, match="exact IG demo endpoint"):
        BrokerSettings(base_url=base_url)


def test_ai_settings_do_not_contain_broker_credentials() -> None:
    ai_fields = set(type(AppSettings().ai).model_fields)

    assert {"api_key", "model", "provider"} == ai_fields
    assert "password" not in ai_fields
    assert "identifier" not in ai_fields


def test_secret_values_are_redacted_from_repr_json_and_validation_errors() -> None:
    sentinel = "synthetic-secret-for-redaction-test"
    settings = AppSettings(
        broker=BrokerSettings(api_key=sentinel, identifier=sentinel, password=sentinel),
        ai={"api_key": sentinel},
    )

    assert sentinel not in repr(settings)
    assert sentinel not in settings.model_dump_json()

    with pytest.raises(ValidationError) as error:
        BrokerSettings(base_url="https://api.ig.com/gateway/deal", api_key=sentinel)

    assert sentinel not in str(error.value)


def test_ig_environment_configuration_is_typed_and_secret() -> None:
    settings = AppSettings.from_environment(
        {
            "IG_BASE_URL": IG_DEMO_BASE_URL,
            "IG_IDENTIFIER": "test-identifier",
            "IG_PASSWORD": "test-password",
            "IG_API_KEY": "test-api-key",
            "IG_REQUEST_TIMEOUT_SECONDS": "12.5",
            "IG_MAX_HISTORICAL_PRICE_POINTS": "250",
            "IG_OAUTH_EXPIRY_SAFETY_MARGIN_SECONDS": "7.5",
        },
        env_file=None,
    )

    assert settings.broker.identifier is not None
    assert settings.broker.password is not None
    assert settings.broker.api_key is not None
    assert settings.broker.identifier.get_secret_value() == "test-identifier"
    assert settings.broker.password.get_secret_value() == "test-password"
    assert settings.broker.api_key.get_secret_value() == "test-api-key"
    assert settings.broker.request_timeout_seconds == 12.5
    assert settings.broker.max_historical_price_points == 250
    assert settings.broker.oauth_expiry_safety_margin_seconds == 7.5


@pytest.mark.parametrize("margin", [-1, 61, float("nan"), float("inf")])
def test_invalid_oauth_expiry_margin_is_rejected(margin: float) -> None:
    with pytest.raises(ValidationError):
        BrokerSettings(oauth_expiry_safety_margin_seconds=margin)


def test_ig_credentials_remain_optional_until_an_integration_is_used() -> None:
    settings = AppSettings.from_environment({}, env_file=None)

    assert settings.broker.identifier is None
    assert settings.broker.password is None
    assert settings.broker.api_key is None
