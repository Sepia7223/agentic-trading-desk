from __future__ import annotations

import pytest

from trading_desk.safety import SafetyAction, TradeSafetyState, evaluate_trade_safety


def test_missing_state_fails_closed_to_no_trade() -> None:
    assert evaluate_trade_safety(TradeSafetyState()) is SafetyAction.NO_TRADE


@pytest.mark.parametrize(
    "unknown_field",
    [
        "broker_state_known",
        "position_state_known",
        "market_state_known",
        "risk_state_known",
    ],
)
@pytest.mark.parametrize("unknown_value", [False, None])
def test_each_unknown_state_fails_closed_to_no_trade(
    unknown_field: str, unknown_value: bool | None
) -> None:
    values: dict[str, bool | None] = {
        "broker_state_known": True,
        "position_state_known": True,
        "market_state_known": True,
        "risk_state_known": True,
    }
    values[unknown_field] = unknown_value

    state = TradeSafetyState(**values)

    assert evaluate_trade_safety(state) is SafetyAction.NO_TRADE


def test_known_state_remains_analysis_only() -> None:
    state = TradeSafetyState(
        broker_state_known=True,
        position_state_known=True,
        market_state_known=True,
        risk_state_known=True,
    )

    assert evaluate_trade_safety(state) is SafetyAction.ANALYSIS_ONLY
