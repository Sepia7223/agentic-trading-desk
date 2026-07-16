from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from tests.risk_helpers import candidate

from trading_desk.risk.config import RiskConfiguration
from trading_desk.risk.fingerprints import canonical_json, fingerprint
from trading_desk.risk.models import RiskDecisionStatus, TradeCandidate


def test_risk_configuration_defaults_are_safe_and_fingerprinted() -> None:
    config = RiskConfiguration()

    assert config.risk_per_trade_fraction == Decimal("0.01")
    assert config.kill_switch_enabled is True
    assert config.long_only is True
    assert config.include_unrealized_in_daily_loss is True
    assert len(config.fingerprint) == 64


def test_risk_configuration_is_immutable() -> None:
    config = RiskConfiguration()

    with pytest.raises(ValidationError):
        config.risk_per_trade_fraction = Decimal("0.02")  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("risk_per_trade_fraction", Decimal("0")),
        ("risk_per_trade_fraction", Decimal("1.01")),
        ("maximum_portfolio_drawdown_fraction", Decimal("-0.1")),
        ("maximum_gross_exposure_fraction", Decimal("1.1")),
        ("quantity_increment", Decimal("0")),
        ("maximum_candidate_age", timedelta(0)),
        ("risk_per_trade_fraction", Decimal("NaN")),
        ("risk_per_trade_fraction", 0.01),
        ("kill_switch_enabled", False),
        ("long_only", False),
    ],
)
def test_configuration_rejects_invalid_safety_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        RiskConfiguration.model_validate({field: value})


def test_configuration_rejects_reversed_ranges_and_bad_fingerprint() -> None:
    with pytest.raises(ValidationError, match="stop-distance bounds"):
        RiskConfiguration(minimum_stop_distance=Decimal("2"), maximum_stop_distance=Decimal("1"))
    with pytest.raises(ValidationError, match="quantity bounds"):
        RiskConfiguration(
            minimum_approved_quantity=Decimal("2"),
            maximum_approved_quantity=Decimal("1"),
        )
    with pytest.raises(ValidationError, match="lowercase SHA-256"):
        RiskConfiguration(required_strategy_configuration_fingerprint="invalid")


def test_configuration_fingerprint_is_stable_and_material_changes_differ() -> None:
    first = RiskConfiguration()
    second = RiskConfiguration.model_validate(first.model_dump())
    changed = RiskConfiguration(risk_per_trade_fraction=Decimal("0.02"))

    assert first.fingerprint == second.fingerprint
    assert first.fingerprint != changed.fingerprint


def test_canonical_fingerprint_ignores_mapping_field_order_and_normalizes_decimal() -> None:
    left = {"status": RiskDecisionStatus.REJECTED, "amount": Decimal("1.00")}
    right = {"amount": Decimal("1"), "status": RiskDecisionStatus.REJECTED}

    assert canonical_json(left) == canonical_json(right)
    assert fingerprint(left) == fingerprint(right)


def test_risk_models_require_utc_timestamps_and_reject_binary_float() -> None:
    values = candidate().model_dump()
    values["signal_timestamp"] = datetime(2026, 7, 15, 12, 0)
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        TradeCandidate.model_validate(values)

    values = candidate().model_dump()
    values["entry_reference"] = 100.0
    with pytest.raises(ValidationError, match="binary floating point"):
        TradeCandidate.model_validate(values)
