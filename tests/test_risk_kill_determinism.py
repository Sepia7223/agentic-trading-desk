from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from tests.risk_helpers import NOW, account, candidate, market

from trading_desk.risk.engine import RiskEngine
from trading_desk.risk.models import RiskDecisionStatus, RiskGate, RiskReasonCode


def test_kill_switch_overrides_otherwise_valid_approval() -> None:
    decision = RiskEngine().evaluate(candidate(), account(kill_switch_active=True), market(), NOW)

    assert decision.status is RiskDecisionStatus.KILL_SWITCHED
    assert decision.reason_codes == (RiskReasonCode.KILL_SWITCH_ACTIVE,)
    assert decision.failed_gates == (RiskGate.KILL_SWITCH,)
    assert decision.approved_quantity is None
    assert decision.approved_intent is None


def test_kill_switch_output_is_deterministic() -> None:
    engine = RiskEngine()
    values = [
        engine.evaluate(candidate(), account(kill_switch_active=True), market(), NOW)
        for _ in range(3)
    ]

    assert len({item.model_dump_json() for item in values}) == 1


def test_identical_inputs_produce_byte_equivalent_decisions() -> None:
    engine = RiskEngine()
    first = engine.evaluate(candidate(), account(), market(), NOW)
    second = engine.evaluate(candidate(), account(), market(), NOW)

    assert first.model_dump_json() == second.model_dump_json()
    assert first.decision_fingerprint == second.decision_fingerprint
    assert first.decision_id == second.decision_id


def test_material_input_change_changes_decision_fingerprint() -> None:
    engine = RiskEngine()
    first = engine.evaluate(candidate(), account(), market(), NOW)
    changed = engine.evaluate(candidate(stop_reference=Decimal("94")), account(), market(), NOW)

    assert first.decision_fingerprint != changed.decision_fingerprint
    assert first.decision_id != changed.decision_id


def test_approved_intent_is_immutable_and_expires_exclusively() -> None:
    decision = RiskEngine().evaluate(candidate(), account(), market(), NOW)
    intent = decision.approved_intent

    assert intent is not None
    assert intent.is_valid_at(NOW)
    assert intent.is_valid_at(intent.expiry_timestamp - timedelta(microseconds=1))
    assert not intent.is_valid_at(intent.expiry_timestamp)
    with pytest.raises(ValidationError):
        intent.approved_quantity = Decimal("1")  # type: ignore[misc]


def test_every_rejection_has_stable_reason_and_failed_gate() -> None:
    decisions = (
        RiskEngine().evaluate(candidate(holding_state=None), account(), market(), NOW),
        RiskEngine().evaluate(candidate(), account(state_complete=False), market(), NOW),
        RiskEngine().evaluate(candidate(), account(), market(state_complete=False), NOW),
    )

    assert all(item.status is not RiskDecisionStatus.APPROVED for item in decisions)
    assert all(item.reason_codes for item in decisions)
    assert all(item.failed_gates for item in decisions)


def test_decision_record_contains_journal_linkage_and_policy_fields() -> None:
    decision = RiskEngine().evaluate(candidate(), account(), market(), NOW)

    assert decision.candidate_id == "candidate-1"
    assert decision.signal_id == "signal-1"
    assert decision.account_snapshot_id == "account-snapshot-1"
    assert decision.market_snapshot_id == "market-snapshot-1"
    assert len(decision.strategy_configuration_fingerprint) == 64
    assert len(decision.risk_configuration_fingerprint) == 64
    assert len(decision.decision_fingerprint) == 64
