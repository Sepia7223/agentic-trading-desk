"""Fail-closed eligibility checks for deterministic trade analysis."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class SafetyAction(StrEnum):
    """Actions available before concrete providers or execution exist."""

    NO_TRADE = "NO TRADE"
    ANALYSIS_ONLY = "ANALYSIS ONLY"


class TradeSafetyState(BaseModel):
    """Whether every state required for trade analysis is known."""

    model_config = ConfigDict(frozen=True)

    broker_state_known: bool | None = None
    position_state_known: bool | None = None
    market_state_known: bool | None = None
    risk_state_known: bool | None = None


def evaluate_trade_safety(state: TradeSafetyState) -> SafetyAction:
    """Return no-trade unless every required state is explicitly known."""

    known_states = (
        state.broker_state_known,
        state.position_state_known,
        state.market_state_known,
        state.risk_state_known,
    )
    if not all(value is True for value in known_states):
        return SafetyAction.NO_TRADE
    return SafetyAction.ANALYSIS_ONLY
