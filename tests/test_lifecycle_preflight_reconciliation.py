from datetime import timedelta
from decimal import Decimal

import pytest

from lifecycle_helpers import NOW, enabled_configuration, open_position, risk, snapshot
from trading_desk.lifecycle.engine import _result
from trading_desk.lifecycle.evaluator import evaluate_exit
from trading_desk.lifecycle.idempotency import LifecycleIdempotencyStore
from trading_desk.lifecycle.mapping import create_close_request, map_broker_close
from trading_desk.lifecycle.models import (
    CloseExecutionStatus,
    CloseReconciliationStatus,
    CloseSide,
    ExitPreflightStatus,
    StrategyExitState,
)
from trading_desk.lifecycle.preflight import run_exit_preflight
from trading_desk.lifecycle.reconciliation import reconcile_close


def preflight(**updates: object):  # type: ignore[no-untyped-def]
    config = updates.pop("configuration", enabled_configuration())
    snap = updates.pop("snapshot", snapshot(current_bid=Decimal("95"), current_mark=Decimal("95")))
    risk_state = updates.pop("risk", risk())
    decision = evaluate_exit(snap, risk_state, StrategyExitState.HOLD, NOW, config)
    request = create_close_request(decision, snap, config)
    values = {
        "decision": decision,
        "request": request,
        "snapshot": snap,
        "risk": risk_state,
        "positions": (open_position(),),
        "now": NOW,
        "configuration": config,
        "idempotency": LifecycleIdempotencyStore(),
        "broker_session_valid": True,
        "close_requests_this_cycle": 0,
        "close_requests_today": 0,
    }
    values.update(updates)
    return run_exit_preflight(**values), decision, request  # type: ignore[arg-type]


def test_valid_preflight_and_close_mapping_are_full_sell_market_only() -> None:
    result, _, request = preflight()
    assert result.status is ExitPreflightStatus.READY
    mapped = map_broker_close(request, result.validated_quantity)  # type: ignore[arg-type]
    assert mapped.deal_id == "deal-id-1"
    assert mapped.direction is CloseSide.SELL
    assert mapped.size == Decimal("1")
    assert set(mapped.model_dump()) == {
        "deal_id",
        "direction",
        "size",
        "order_type",
        "time_in_force",
    }


@pytest.mark.parametrize(
    ("updates", "gate"),
    [
        (
            {"configuration": enabled_configuration(automatic_exit_enabled=False)},
            "AUTOMATIC_EXIT_ENABLED",
        ),
        ({"positions": ()}, "EXACT_BROKER_POSITION"),
        ({"positions": (open_position(size=Decimal("0.5")),)}, "EXACT_BROKER_POSITION"),
        ({"broker_session_valid": False}, "BROKER_SESSION_VALID"),
        ({"close_requests_today": 2}, "DAILY_LIMIT_AVAILABLE"),
        ({"unresolved_previous_close": True}, "NO_UNRESOLVED_CLOSE"),
        ({"reconciliation_mismatch": True}, "NO_RECONCILIATION_MISMATCH"),
    ],
)
def test_preflight_blocks_every_unknown_or_unsafe_state(
    updates: dict[str, object], gate: str
) -> None:
    result, _, _ = preflight(**updates)
    assert result.status is not ExitPreflightStatus.READY
    assert gate in result.failed_gates


def test_preflight_blocks_stale_quote_and_account() -> None:
    result, _, _ = preflight(
        snapshot=snapshot(
            current_bid=Decimal("95"),
            current_mark=Decimal("95"),
            market_timestamp=NOW - timedelta(minutes=2),
        )
    )
    assert "MARKET_DATA_FRESH" in result.failed_gates


def test_idempotency_reserves_only_once() -> None:
    result, decision, request = preflight()
    assert result.status is ExitPreflightStatus.READY
    store = LifecycleIdempotencyStore()
    assert store.reserve(decision, request)
    assert not store.reserve(decision, request)
    assert store.snapshot() == LifecycleIdempotencyStore(store.snapshot()).snapshot()


@pytest.mark.parametrize(
    ("positions", "expected"),
    [
        ((), CloseReconciliationStatus.POSITION_CLOSED),
        ((open_position(),), CloseReconciliationStatus.POSITION_STILL_OPEN),
        ((open_position(size=Decimal("0.5")),), CloseReconciliationStatus.PARTIAL_POSITION_REMAINS),
        (
            (open_position(direction="SELL", deal_id="opposite"),),  # type: ignore[arg-type]
            CloseReconciliationStatus.UNEXPECTED_OPPOSITE_POSITION,
        ),
    ],
)
def test_reconciliation_never_invents_closure(
    positions: tuple[object, ...], expected: CloseReconciliationStatus
) -> None:
    _, _, request = preflight()
    result = _result(request, NOW, CloseExecutionStatus.ACCEPTED)
    reconciliation = reconcile_close(request, result, positions, NOW)  # type: ignore[arg-type]
    assert reconciliation.status is expected
    assert reconciliation == reconcile_close(request, result, positions, NOW)  # type: ignore[arg-type]
