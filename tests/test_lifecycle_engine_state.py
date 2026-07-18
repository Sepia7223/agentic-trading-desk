from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path

import pytest

from lifecycle_helpers import (
    NOW,
    FakeCloseBroker,
    enabled_configuration,
    open_position,
    risk,
    snapshot,
)
from trading_desk.execution.errors import ExecutionBrokerError
from trading_desk.lifecycle.engine import DemoPositionLifecycleEngine
from trading_desk.lifecycle.idempotency import LifecycleIdempotencyStore
from trading_desk.lifecycle.journal import InMemoryLifecycleJournal
from trading_desk.lifecycle.models import (
    CloseBrokerConfirmation,
    CloseConfirmationStatus,
    CloseExecutionStatus,
    CloseReconciliationStatus,
    LifecycleEventType,
    StrategyExitState,
)
from trading_desk.lifecycle.state import LifecycleStateStore, initial_state, update_state


async def no_sleep(_: float) -> None:
    return None


def run(broker: FakeCloseBroker, **updates: object):  # type: ignore[no-untyped-def]
    journal = updates.pop("journal", InMemoryLifecycleJournal())
    engine = DemoPositionLifecycleEngine(
        broker,
        configuration=updates.pop("configuration", enabled_configuration()),
        idempotency=updates.pop("idempotency", LifecycleIdempotencyStore()),
        journal=journal,
        sleep=no_sleep,
    )
    snap = updates.pop("snapshot", snapshot(current_bid=Decimal("95"), current_mark=Decimal("95")))
    values = {
        "snapshot": snap,
        "risk": risk(),
        "strategy_exit": StrategyExitState.HOLD,
        "positions": (open_position(),),
        "evaluation_timestamp": NOW,
    }
    values.update(updates)
    return asyncio.run(engine.evaluate_and_manage(**values)), engine, journal  # type: ignore[arg-type]


def test_complete_stop_close_is_submitted_once_confirmed_and_reconciled() -> None:
    broker = FakeCloseBroker(positions_after=())
    outcome, _, journal = run(broker)
    assert broker.submission_calls == 1
    assert outcome.result is not None
    assert outcome.result.status is CloseExecutionStatus.RECONCILED
    assert outcome.reconciliation is not None
    assert outcome.reconciliation.status is CloseReconciliationStatus.POSITION_CLOSED
    assert not outcome.automatic_lifecycle_halted
    events = tuple(item.event_type for item in journal.records())  # type: ignore[attr-defined]
    assert LifecycleEventType.POSITION_CLOSED in events


def test_hold_does_not_submit() -> None:
    broker = FakeCloseBroker()
    outcome, _, _ = run(broker, snapshot=snapshot())
    assert outcome.result is None
    assert broker.submission_calls == 0


def test_ambiguous_transport_halts_without_retry() -> None:
    broker = FakeCloseBroker(
        failure=ExecutionBrokerError(
            "safe close failure", operation="close_position", ambiguous=True
        )
    )
    outcome, _, _ = run(broker)
    assert broker.submission_calls == 1
    assert outcome.result is not None
    assert outcome.result.status is CloseExecutionStatus.RECONCILIATION_REQUIRED
    assert outcome.automatic_lifecycle_halted


def test_pending_confirmation_times_out_without_second_close() -> None:
    pending = CloseBrokerConfirmation(
        deal_reference="close-ref-1",
        status=CloseConfirmationStatus.PENDING,
        confirmed_at=NOW,
    )
    broker = FakeCloseBroker(confirmations=(pending,))
    outcome, _, _ = run(
        broker,
        configuration=enabled_configuration(
            maximum_confirmation_wait_seconds=Decimal("1"),
            confirmation_poll_interval_seconds=Decimal("0.5"),
        ),
    )
    assert broker.submission_calls == 1
    assert broker.confirmation_calls == 2
    assert outcome.result is not None
    assert outcome.result.status is CloseExecutionStatus.RECONCILIATION_REQUIRED


def test_residual_position_halts_and_never_submits_second_close() -> None:
    broker = FakeCloseBroker(positions_after=(open_position(size=Decimal("0.5")),))
    outcome, _, _ = run(broker)
    assert broker.submission_calls == 1
    assert outcome.automatic_lifecycle_halted
    assert outcome.reconciliation is not None
    assert outcome.reconciliation.status is CloseReconciliationStatus.PARTIAL_POSITION_REMAINS


def test_persistent_state_round_trip_halt_and_lock(tmp_path: Path) -> None:
    path = tmp_path / "lifecycle.json"
    store = LifecycleStateStore(path)
    descriptor = store.acquire_lock()
    with pytest.raises(Exception, match="locked"):
        store.acquire_lock()
    state = update_state(
        initial_state(),
        automatic_lifecycle_halt=True,
        halt_reason="AMBIGUOUS_CLOSE",
        last_close_timestamp=NOW,
        daily_close_counts=((NOW.date(), 1),),
    )
    store.save(state)
    assert store.load() == state
    store.release_lock(descriptor)


def test_corrupted_persistent_state_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "lifecycle.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(Exception, match="could not be validated"):
        LifecycleStateStore(path).load()
