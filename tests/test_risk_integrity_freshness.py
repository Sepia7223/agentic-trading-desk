from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from tests.risk_helpers import NOW, account, candidate, market

from trading_desk.risk.config import RiskConfiguration
from trading_desk.risk.engine import RiskEngine
from trading_desk.risk.models import (
    RiskDecisionStatus,
    RiskMarketStatus,
    RiskReasonCode,
)


@pytest.mark.parametrize(
    ("candidate_updates", "account_updates", "market_updates", "reason"),
    [
        ({"bid": None}, {}, {}, RiskReasonCode.INVALID_BID_ASK),
        ({"ask": None}, {}, {}, RiskReasonCode.INVALID_BID_ASK),
        ({"bid": Decimal("NaN")}, {}, {}, RiskReasonCode.INVALID_INPUT),
        ({"bid": Decimal("101")}, {}, {}, RiskReasonCode.INVALID_BID_ASK),
        ({}, {"account_equity": Decimal("NaN")}, {}, RiskReasonCode.INVALID_INPUT),
        ({}, {"account_equity": Decimal("0")}, {}, RiskReasonCode.INSUFFICIENT_EQUITY),
        (
            {},
            {"available_capital": Decimal("-1")},
            {},
            RiskReasonCode.INSUFFICIENT_AVAILABLE_CAPITAL,
        ),
        ({"stop_reference": Decimal("100")}, {}, {}, RiskReasonCode.INVALID_STOP_DIRECTION),
        ({"stop_reference": Decimal("99.5")}, {}, {}, RiskReasonCode.STOP_TOO_CLOSE),
        ({"stop_reference": Decimal("70")}, {}, {}, RiskReasonCode.STOP_TOO_FAR),
        ({}, {"state_complete": False}, {}, RiskReasonCode.ACCOUNT_STATE_UNKNOWN),
        ({}, {}, {"state_complete": False}, RiskReasonCode.MARKET_STATE_UNKNOWN),
        ({}, {}, {"value_per_price_unit": None}, RiskReasonCode.MARKET_STATE_UNKNOWN),
        ({}, {}, {"value_per_price_unit": Decimal("NaN")}, RiskReasonCode.INVALID_INPUT),
        ({}, {}, {"quantity_increment": Decimal("0")}, RiskReasonCode.MARKET_STATE_UNKNOWN),
    ],
)
def test_input_and_state_failures_return_stable_reason_codes(
    candidate_updates: dict[str, object],
    account_updates: dict[str, object],
    market_updates: dict[str, object],
    reason: RiskReasonCode,
) -> None:
    decision = RiskEngine().evaluate(
        candidate(**candidate_updates),
        account(**account_updates),
        market(**market_updates),
        NOW,
    )

    assert decision.status is not RiskDecisionStatus.APPROVED
    assert reason in decision.reason_codes
    assert decision.approved_quantity is None


@pytest.mark.parametrize(
    ("holding", "reason", "approved"),
    [
        (None, RiskReasonCode.UNKNOWN_HOLDING_STATE, False),
        (True, RiskReasonCode.POSITION_ALREADY_OPEN, False),
        (False, None, True),
    ],
)
def test_holding_state_semantics(
    holding: bool | None, reason: RiskReasonCode | None, approved: bool
) -> None:
    decision = RiskEngine().evaluate(candidate(holding_state=holding), account(), market(), NOW)

    assert (decision.status is RiskDecisionStatus.APPROVED) is approved
    if reason is not None:
        assert reason in decision.reason_codes


def test_expiry_is_exclusive_and_exact_expiry_rejects() -> None:
    before = RiskEngine().evaluate(
        candidate(candidate_expiry=NOW + timedelta(microseconds=1)), account(), market(), NOW
    )
    at_expiry = RiskEngine().evaluate(candidate(candidate_expiry=NOW), account(), market(), NOW)

    assert before.status is RiskDecisionStatus.APPROVED
    assert at_expiry.status is RiskDecisionStatus.EXPIRED
    assert RiskReasonCode.CANDIDATE_EXPIRED in at_expiry.reason_codes


def test_signal_future_data_cutoff_and_candidate_age_fail_closed() -> None:
    future = candidate(
        signal_timestamp=NOW + timedelta(seconds=1),
        data_cutoff_timestamp=NOW + timedelta(seconds=1),
    )
    old = candidate(
        signal_timestamp=NOW - timedelta(minutes=5, microseconds=1),
        data_cutoff_timestamp=NOW - timedelta(minutes=5, microseconds=1),
    )

    future_decision = RiskEngine().evaluate(future, account(), market(), NOW)
    old_decision = RiskEngine().evaluate(old, account(), market(), NOW)

    assert RiskReasonCode.SIGNAL_TIMESTAMP_IN_FUTURE in future_decision.reason_codes
    assert RiskReasonCode.CANDIDATE_EXPIRED in old_decision.reason_codes


def test_candidate_age_and_market_staleness_boundaries_are_inclusive() -> None:
    config = RiskConfiguration(maximum_market_signal_lag=timedelta(minutes=10))
    exact_age = candidate(
        signal_timestamp=NOW - config.maximum_candidate_age,
        data_cutoff_timestamp=NOW - config.maximum_candidate_age,
    )
    exact_market = market(timestamp=NOW - config.maximum_market_data_age)
    stale_market = market(
        timestamp=NOW - config.maximum_market_data_age - timedelta(microseconds=1)
    )

    assert (
        RiskEngine(config).evaluate(exact_age, account(), exact_market, NOW).status
        is RiskDecisionStatus.APPROVED
    )
    stale = RiskEngine(config).evaluate(candidate(), account(), stale_market, NOW)
    assert RiskReasonCode.MARKET_DATA_STALE in stale.reason_codes


def test_market_status_and_spread_gate() -> None:
    closed = RiskEngine().evaluate(
        candidate(market_status=RiskMarketStatus.CLOSED),
        account(),
        market(market_status=RiskMarketStatus.CLOSED),
        NOW,
    )
    wide = RiskEngine().evaluate(
        candidate(spread_bps=Decimal("10.01")),
        account(),
        market(spread_bps=Decimal("10.01")),
        NOW,
    )

    assert RiskReasonCode.MARKET_CLOSED in closed.reason_codes
    assert RiskReasonCode.SPREAD_TOO_WIDE in wide.reason_codes


def test_entry_and_candidate_snapshot_must_match_injected_market_state() -> None:
    bad_entry = RiskEngine().evaluate(
        candidate(entry_reference=Decimal("101"), stop_reference=Decimal("96")),
        account(),
        market(),
        NOW,
    )
    bad_spread = RiskEngine().evaluate(candidate(spread_bps=Decimal("9")), account(), market(), NOW)

    assert RiskReasonCode.INVALID_BID_ASK in bad_entry.reason_codes
    assert RiskReasonCode.MARKET_STATE_UNKNOWN in bad_spread.reason_codes


def test_configuration_fingerprint_mismatch_rejects() -> None:
    config = RiskConfiguration(required_strategy_configuration_fingerprint="b" * 64)
    decision = RiskEngine(config).evaluate(candidate(), account(), market(), NOW)

    assert decision.status is RiskDecisionStatus.INVALID_INPUT
    assert RiskReasonCode.CONFIGURATION_MISMATCH in decision.reason_codes
