from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from tests.execution_helpers import enabled_configuration, request_and_confirmation
from tests.risk_helpers import NOW, account, candidate, market

from trading_desk.execution.config import ExecutionConfiguration
from trading_desk.execution.idempotency import ExecutionIdempotencyStore
from trading_desk.execution.models import ExecutionReasonCode, PreflightStatus
from trading_desk.execution.preflight import run_preflight
from trading_desk.risk.engine import RiskEngine
from trading_desk.risk.models import RiskMarketStatus


def _preflight(**updates: object):  # type: ignore[no-untyped-def]
    configuration = updates.pop("configuration", enabled_configuration())
    request, confirmation, decision = request_and_confirmation(configuration=configuration)
    values = {
        "request": request,
        "decision": decision,
        "candidate": candidate(),
        "account": account(),
        "market": market(),
        "positions": (),
        "confirmation": confirmation,
        "evaluation_timestamp": NOW,
        "configuration": configuration,
        "risk_engine": RiskEngine(),
        "idempotency": ExecutionIdempotencyStore(),
    }
    values.update(updates)
    return run_preflight(**values)  # type: ignore[arg-type]


def test_valid_current_state_is_ready_and_quantity_never_increases() -> None:
    result = _preflight()
    assert result.status is PreflightStatus.READY
    assert result.validated_quantity == Decimal("1")


def test_current_risk_revalidation_can_only_reduce_quantity() -> None:
    reduced = _preflight(
        account=account(
            account_equity=Decimal("100"),
            available_capital=Decimal("100"),
        )
    )
    assert reduced.status is PreflightStatus.READY
    assert reduced.validated_quantity == Decimal("0.20")


def test_confirmation_is_bound_to_exact_request_and_expiry() -> None:
    configuration = enabled_configuration()
    request, confirmation, _ = request_and_confirmation(configuration=configuration)
    wrong_request = request.model_copy(update={"operator_confirmation_id": "f" * 64})
    mismatch = _preflight(
        configuration=configuration,
        request=wrong_request,
        confirmation=confirmation,
    )
    assert ExecutionReasonCode.OPERATOR_CONFIRMATION_REQUIRED in mismatch.reason_codes
    expired = _preflight(
        configuration=configuration,
        request=request,
        confirmation=confirmation,
        evaluation_timestamp=NOW + timedelta(minutes=2),
    )
    assert ExecutionReasonCode.OPERATOR_CONFIRMATION_REQUIRED in expired.reason_codes


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"configuration": ExecutionConfiguration()}, ExecutionReasonCode.EXECUTION_DISABLED),
        ({"confirmation": None}, ExecutionReasonCode.OPERATOR_CONFIRMATION_REQUIRED),
        (
            {"evaluation_timestamp": NOW + timedelta(minutes=5)},
            ExecutionReasonCode.APPROVAL_EXPIRED,
        ),
        (
            {"account": account(kill_switch_active=True)},
            ExecutionReasonCode.KILL_SWITCH_ACTIVE,
        ),
        (
            {"account": account(timestamp=NOW - timedelta(minutes=2))},
            ExecutionReasonCode.ACCOUNT_DATA_STALE,
        ),
        (
            {"market": market(timestamp=NOW - timedelta(minutes=2))},
            ExecutionReasonCode.MARKET_DATA_STALE,
        ),
        (
            {"market": market(market_status=RiskMarketStatus.CLOSED)},
            ExecutionReasonCode.MARKET_CLOSED,
        ),
        ({"market": market(bid=Decimal("101"))}, ExecutionReasonCode.INVALID_BID_ASK),
        (
            {"market": market(ask=Decimal("100.2"))},
            ExecutionReasonCode.PRICE_DRIFT_EXCEEDED,
        ),
        (
            {"market": market(spread_bps=Decimal("20"))},
            ExecutionReasonCode.SPREAD_CHANGED,
        ),
        ({"orders_this_run": 1}, ExecutionReasonCode.MAX_ORDERS_PER_RUN_REACHED),
        ({"orders_today": 1}, ExecutionReasonCode.MAX_ORDERS_PER_DAY_REACHED),
        ({"automatic": True}, ExecutionReasonCode.AUTOMATIC_EXECUTION_DISABLED),
    ],
)
def test_mandatory_gate_failure_rejects(
    updates: dict[str, object], reason: ExecutionReasonCode
) -> None:
    result = _preflight(**updates)
    assert result.status is not PreflightStatus.READY
    assert reason in result.reason_codes
    assert result.validated_quantity is None


def test_tampered_quantity_and_fingerprints_reject() -> None:
    configuration = enabled_configuration(maximum_order_quantity=Decimal("500"))
    request, confirmation, _ = request_and_confirmation(configuration=configuration)
    tampered = request.model_copy(update={"requested_quantity": Decimal("201")})
    result = _preflight(
        configuration=configuration,
        request=tampered,
        confirmation=confirmation,
    )
    assert ExecutionReasonCode.QUANTITY_EXCEEDS_APPROVAL in result.reason_codes

    tampered_currency = request.model_copy(update={"currency": "EUR"})
    fingerprint_result = _preflight(
        configuration=configuration,
        request=tampered_currency,
        confirmation=confirmation,
    )
    assert ExecutionReasonCode.EXECUTION_FINGERPRINT_MISMATCH in (fingerprint_result.reason_codes)


def test_consumed_intent_and_duplicate_request_reject() -> None:
    configuration = enabled_configuration()
    request, confirmation, _ = request_and_confirmation(configuration=configuration)
    store = ExecutionIdempotencyStore()
    assert store.reserve_submission(request)
    result = _preflight(
        configuration=configuration,
        request=request,
        confirmation=confirmation,
        idempotency=store,
    )
    assert ExecutionReasonCode.DUPLICATE_EXECUTION_REQUEST in result.reason_codes
    assert ExecutionReasonCode.INTENT_ALREADY_CONSUMED in result.reason_codes
