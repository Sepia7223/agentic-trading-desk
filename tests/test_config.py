from __future__ import annotations

import pytest
from pydantic import ValidationError

from trading_desk.config import (
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


def test_settings_are_immutable() -> None:
    settings = AppSettings()

    with pytest.raises(ValidationError):
        settings.safety.live_trading_allowed = True


def test_live_trading_and_automatic_execution_are_rejected() -> None:
    with pytest.raises(ValidationError, match="live trading is disabled"):
        SafetySettings(live_trading_allowed=True)

    with pytest.raises(ValidationError, match="automatic execution is disabled"):
        SafetySettings(automatic_execution_enabled=True)


def test_production_ig_urls_are_rejected() -> None:
    with pytest.raises(ValidationError, match="production IG URLs"):
        BrokerSettings(base_url="https://api.ig.com/gateway/deal")

    with pytest.raises(ValidationError, match="demo environment"):
        BrokerSettings(base_url="https://example.com/gateway/deal")


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
