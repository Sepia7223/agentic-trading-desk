from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading_desk.ai.config import AIAnalystConfiguration


def test_ai_is_disabled_and_network_is_denied_by_default() -> None:
    configuration = AIAnalystConfiguration()
    assert configuration.analysis_enabled is False
    assert configuration.allow_network_provider is False
    assert configuration.store_raw_provider_response is False
    assert configuration.temperature == Decimal("0")
    assert configuration.maximum_retries == 0
    assert configuration.redact_account_identifiers is True
    assert configuration.redact_broker_identifiers is True


def test_configuration_fingerprint_is_stable_and_models_are_immutable() -> None:
    first = AIAnalystConfiguration()
    second = AIAnalystConfiguration()
    assert first.fingerprint == second.fingerprint
    assert len(first.fingerprint) == 64
    with pytest.raises(ValidationError):
        first.analysis_enabled = True  # type: ignore[misc]


@pytest.mark.parametrize(
    "values",
    [
        {"temperature": Decimal("-0.1")},
        {"temperature": Decimal("1.1")},
        {"temperature": 0.1},
        {"maximum_input_characters": 99},
        {"maximum_records_per_request": 0},
        {"maximum_output_characters": 99},
        {"maximum_retries": 2},
        {"provider_name": ""},
        {"model_name": "bad\nname"},
        {"analysis_enabled": True},
        {"allow_network_provider": True},
        {"store_raw_provider_response": True},
    ],
)
def test_invalid_configuration_fails_closed(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        AIAnalystConfiguration.model_validate(values)
