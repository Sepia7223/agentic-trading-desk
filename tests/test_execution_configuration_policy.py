from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading_desk.config import IG_DEMO_BASE_URL, BrokerSettings
from trading_desk.execution.config import ExecutionConfiguration
from trading_desk.execution.errors import ExecutionPolicyViolation
from trading_desk.ig.execution_policy import (
    DEAL_CONFIRMATION_VERSION,
    OPEN_POSITION_VERSION,
    ExecutionOperation,
    enforce_execution_policy,
)


def test_execution_configuration_is_disabled_immutable_and_demo_only() -> None:
    configuration = ExecutionConfiguration()
    assert configuration.execution_enabled is False
    assert configuration.automatic_execution_enabled is False
    assert configuration.require_operator_confirmation is True
    assert configuration.demo_gateway == IG_DEMO_BASE_URL
    assert len(configuration.fingerprint) == 64
    with pytest.raises(ValidationError):
        configuration.execution_enabled = True  # type: ignore[misc]


@pytest.mark.parametrize(
    "update",
    [
        {"demo_gateway": "https://api.ig.com/gateway/deal"},
        {"demo_gateway": "http://demo-api.ig.com/gateway/deal"},
        {"demo_gateway": "https://demo-api.ig.com:444/gateway/deal"},
        {"demo_gateway": "https://user:pass@demo-api.ig.com/gateway/deal"},
        {"automatic_execution_enabled": True},
        {"require_operator_confirmation": False},
        {"allow_position_close": True},
        {"allow_position_amendment": True},
        {"allow_working_orders": True},
        {"allow_account_switch": True},
        {"allow_limit_orders": True},
        {"maximum_orders_per_run": 2},
        {"maximum_order_quantity": Decimal("0")},
        {"maximum_order_notional": 100.0},
    ],
)
def test_unsafe_configuration_is_rejected(update: dict[str, object]) -> None:
    with pytest.raises((ValidationError, ValueError)):
        ExecutionConfiguration.model_validate(update)


def test_configuration_fingerprint_is_stable_and_sensitive() -> None:
    first = ExecutionConfiguration()
    second = ExecutionConfiguration()
    changed = ExecutionConfiguration(maximum_orders_per_day=2)
    assert first.fingerprint == second.fingerprint
    assert first.fingerprint != changed.fingerprint


def test_exact_demo_url_validation_remains_canonical() -> None:
    assert BrokerSettings(base_url=IG_DEMO_BASE_URL).base_url == IG_DEMO_BASE_URL


@pytest.mark.parametrize(
    ("operation", "method", "path", "version"),
    [
        (ExecutionOperation.OPEN_POSITION, "GET", "/positions/otc", OPEN_POSITION_VERSION),
        (ExecutionOperation.OPEN_POSITION, "POST", "/positions/otc", 1),
        (ExecutionOperation.OPEN_POSITION, "POST", "/working-orders/otc", 2),
        (ExecutionOperation.OPEN_POSITION, "DELETE", "/positions/otc", 1),
        (ExecutionOperation.OPEN_POSITION, "PUT", "/positions/otc/deal", 2),
        (ExecutionOperation.OPEN_POSITION, "POST", "https://evil.example/positions/otc", 2),
        (ExecutionOperation.OPEN_POSITION, "POST", "//evil.example/positions/otc", 2),
        (ExecutionOperation.OPEN_POSITION, "POST", "/positions/../session", 2),
        (ExecutionOperation.OPEN_POSITION, "POST", "/positions/%2e%2e/session", 2),
        (ExecutionOperation.OPEN_POSITION, "POST", "/positions//otc", 2),
        (ExecutionOperation.DEAL_CONFIRMATION, "GET", "/confirms/", 1),
        (ExecutionOperation.DEAL_CONFIRMATION, "GET", "/confirms/ref?x=1", 1),
    ],
)
def test_non_allowlisted_execution_operations_are_rejected(
    operation: ExecutionOperation, method: str, path: str, version: int
) -> None:
    with pytest.raises(ExecutionPolicyViolation):
        enforce_execution_policy(operation, method, path, version)


def test_exact_execution_operations_are_allowed() -> None:
    enforce_execution_policy(
        ExecutionOperation.OPEN_POSITION, "POST", "/positions/otc", OPEN_POSITION_VERSION
    )
    enforce_execution_policy(
        ExecutionOperation.DEAL_CONFIRMATION,
        "GET",
        "/confirms/deal-ref-1",
        DEAL_CONFIRMATION_VERSION,
    )
