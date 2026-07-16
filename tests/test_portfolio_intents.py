from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from portfolio_helpers import approval, configured_portfolio
from risk_helpers import NOW
from trading_desk.portfolio.models import IntentRejectionCode
from trading_desk.risk.fingerprints import fingerprint
from trading_desk.risk.models import RiskDecisionStatus


def rejection_codes(**changes: object) -> tuple[IntentRejectionCode, ...]:
    portfolio = configured_portfolio()
    decision, candidate, quote = approval(portfolio)
    if "decision" in changes:
        decision = changes["decision"]  # type: ignore[assignment]
    if "candidate" in changes:
        candidate = changes["candidate"]  # type: ignore[assignment]
    if "quote" in changes:
        quote = changes["quote"]  # type: ignore[assignment]
    result = portfolio.open_position(
        decision,
        candidate,
        quote,
        changes.get("timestamp", NOW),  # type: ignore[arg-type]
        quantity=changes.get("quantity"),  # type: ignore[arg-type]
    )
    assert result.rejection is not None
    return result.rejection.reason_codes


def test_valid_approved_intent_opens_at_ask_without_exceeding_quantity() -> None:
    portfolio = configured_portfolio()
    decision, candidate, quote = approval(portfolio)
    result = portfolio.open_position(decision, candidate, quote, NOW)
    assert result.accepted
    assert result.position is not None and result.fill is not None
    assert result.position.quantity == decision.approved_quantity
    assert result.fill.reference_price == quote.ask
    assert result.fill.fill_price > result.fill.reference_price
    assert portfolio.state.open_position_count == 1


def test_expired_intent_is_rejected() -> None:
    portfolio = configured_portfolio()
    decision, candidate, quote = approval(portfolio)
    codes = rejection_codes(
        decision=decision,
        candidate=candidate,
        quote=quote.model_copy(update={"timestamp": decision.candidate_expiry}),
        timestamp=decision.candidate_expiry,
    )
    assert IntentRejectionCode.APPROVAL_EXPIRED in codes


def test_non_approved_decision_is_rejected() -> None:
    portfolio = configured_portfolio()
    decision, candidate, quote = approval(portfolio)
    rejected = decision.model_copy(
        update={
            "status": RiskDecisionStatus.REJECTED,
            "approved_intent": None,
        }
    )
    assert IntentRejectionCode.APPROVAL_NOT_APPROVED in rejection_codes(
        decision=rejected, candidate=candidate, quote=quote
    )


def test_tampered_decision_fingerprint_is_rejected() -> None:
    portfolio = configured_portfolio()
    decision, candidate, quote = approval(portfolio)
    tampered = decision.model_copy(update={"decision_fingerprint": "f" * 64})
    assert IntentRejectionCode.APPROVAL_FINGERPRINT_MISMATCH in rejection_codes(
        decision=tampered, candidate=candidate, quote=quote
    )


def refingerprint(decision):  # type: ignore[no-untyped-def]
    fields = decision.model_dump(mode="python", exclude={"decision_fingerprint"})
    return decision.model_copy(update={"decision_fingerprint": fingerprint(fields)})


def test_strategy_and_risk_fingerprint_mismatches_are_rejected() -> None:
    portfolio = configured_portfolio()
    decision, candidate, quote = approval(portfolio)
    changed_candidate = candidate.model_copy(
        update={"strategy_configuration_fingerprint": "b" * 64}
    )
    assert IntentRejectionCode.STRATEGY_FINGERPRINT_MISMATCH in rejection_codes(
        decision=decision, candidate=changed_candidate, quote=quote
    )

    assert decision.approved_intent is not None
    changed_intent = decision.approved_intent.model_copy(
        update={"risk_configuration_fingerprint": "b" * 64}
    )
    changed_decision = refingerprint(
        decision.model_copy(update={"approved_intent": changed_intent})
    )
    assert IntentRejectionCode.RISK_FINGERPRINT_MISMATCH in rejection_codes(
        decision=changed_decision, candidate=candidate, quote=quote
    )


def test_portfolio_snapshot_mismatch_is_rejected() -> None:
    source = configured_portfolio()
    decision, candidate, quote = approval(source)
    other = configured_portfolio(initial_cash=Decimal("90000"))
    result = other.open_position(decision, candidate, quote, NOW)
    assert result.rejection is not None
    assert IntentRejectionCode.PORTFOLIO_STATE_MISMATCH in result.rejection.reason_codes


@pytest.mark.parametrize(
    ("intent_update", "code"),
    [
        ({"stop_reference": Decimal("101")}, IntentRejectionCode.INVALID_STOP),
        ({"target_reference": Decimal("99")}, IntentRejectionCode.INVALID_TARGET),
    ],
)
def test_invalid_protective_levels_are_rejected(
    intent_update: dict[str, object], code: IntentRejectionCode
) -> None:
    portfolio = configured_portfolio()
    decision, candidate, quote = approval(portfolio)
    assert decision.approved_intent is not None
    changed_intent = decision.approved_intent.model_copy(update=intent_update)
    changed_decision = refingerprint(
        decision.model_copy(update={"approved_intent": changed_intent})
    )
    assert code in rejection_codes(decision=changed_decision, candidate=candidate, quote=quote)


@pytest.mark.parametrize(
    ("quantity", "code"),
    [
        (Decimal("0"), IntentRejectionCode.INVALID_QUANTITY),
        (Decimal("1000000"), IntentRejectionCode.INVALID_QUANTITY),
    ],
)
def test_invalid_or_excess_quantity_rejected(quantity: Decimal, code: IntentRejectionCode) -> None:
    portfolio = configured_portfolio()
    decision, candidate, quote = approval(portfolio)
    assert code in rejection_codes(
        decision=decision, candidate=candidate, quote=quote, quantity=quantity
    )


def test_partial_fill_is_rejected_by_default_and_allowed_only_when_explicit() -> None:
    portfolio = configured_portfolio()
    decision, candidate, quote = approval(portfolio)
    requested = decision.approved_quantity / Decimal("2")  # type: ignore[operator]
    result = portfolio.open_position(decision, candidate, quote, NOW, quantity=requested)
    assert result.rejection is not None
    assert IntentRejectionCode.INVALID_QUANTITY in result.rejection.reason_codes

    enabled = configured_portfolio(allow_partial_fills=True)
    decision, candidate, quote = approval(enabled)
    requested = decision.approved_quantity / Decimal("2")  # type: ignore[operator]
    accepted = enabled.open_position(decision, candidate, quote, NOW, quantity=requested)
    assert accepted.accepted and accepted.position is not None
    assert accepted.position.quantity == requested


def test_duplicate_decision_and_candidate_are_consumed_once() -> None:
    portfolio = configured_portfolio()
    decision, candidate, quote = approval(portfolio)
    assert portfolio.open_position(decision, candidate, quote, NOW).accepted
    fresh_quote = quote.model_copy(update={"timestamp": NOW + timedelta(seconds=1)})
    result = portfolio.open_position(decision, candidate, fresh_quote, NOW + timedelta(seconds=1))
    assert result.rejection is not None
    assert IntentRejectionCode.DUPLICATE_INTENT in result.rejection.reason_codes
    assert IntentRejectionCode.POSITION_ALREADY_EXISTS in result.rejection.reason_codes


def test_maximum_position_limit_rejects_additional_intent() -> None:
    portfolio = configured_portfolio(maximum_open_positions=1)
    decision, candidate, quote = approval(portfolio)
    assert portfolio.open_position(decision, candidate, quote, NOW).accepted
    result = portfolio.open_position(
        decision,
        candidate,
        quote.model_copy(update={"timestamp": NOW + timedelta(seconds=1)}),
        NOW + timedelta(seconds=1),
    )
    assert result.rejection is not None
    assert IntentRejectionCode.PORTFOLIO_LIMIT_REACHED in result.rejection.reason_codes


@pytest.mark.parametrize(
    ("quote_update", "expected"),
    [
        ({"market_status": "CLOSED"}, IntentRejectionCode.MARKET_NOT_TRADEABLE),
        ({"bid": Decimal("101")}, IntentRejectionCode.INVALID_BID_ASK),
        ({"ask": Decimal("100.1")}, IntentRejectionCode.MARKET_STATE_MISMATCH),
        ({"snapshot_id": "other"}, IntentRejectionCode.MARKET_STATE_MISMATCH),
    ],
)
def test_invalid_market_state_rejected(
    quote_update: dict[str, object], expected: IntentRejectionCode
) -> None:
    portfolio = configured_portfolio()
    decision, candidate, quote = approval(portfolio)
    assert expected in rejection_codes(
        decision=decision, candidate=candidate, quote=quote.model_copy(update=quote_update)
    )


def test_insufficient_cash_rejected_atomically() -> None:
    portfolio = configured_portfolio(initial_cash=Decimal("100"))
    decision, candidate, quote = approval(portfolio)
    before = portfolio.state
    result = portfolio.open_position(decision, candidate, quote, NOW)
    assert result.rejection is not None
    assert IntentRejectionCode.INSUFFICIENT_CASH in result.rejection.reason_codes
    assert portfolio.state.cash == before.cash
    assert portfolio.state.open_position_count == 0
