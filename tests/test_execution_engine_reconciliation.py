from __future__ import annotations

import asyncio
from decimal import Decimal

from tests.execution_helpers import (
    FakeExecutionBroker,
    enabled_configuration,
    open_position,
    request_and_confirmation,
)
from tests.risk_helpers import NOW, account, candidate, market

from trading_desk.execution.engine import ExecutionEngine
from trading_desk.execution.errors import ExecutionBrokerError
from trading_desk.execution.idempotency import ExecutionIdempotencyStore
from trading_desk.execution.journal import InMemoryExecutionJournal
from trading_desk.execution.models import (
    BrokerConfirmation,
    BrokerConfirmationStatus,
    ExecutionReasonCode,
    ExecutionStatus,
    ReconciliationStatus,
)


def _execute(broker: FakeExecutionBroker, **updates: object):  # type: ignore[no-untyped-def]
    configuration = updates.pop("configuration", enabled_configuration())
    request, confirmation, decision = request_and_confirmation(configuration=configuration)
    journal = updates.pop("journal", InMemoryExecutionJournal())
    engine = ExecutionEngine(
        broker,
        configuration=configuration,
        journal=journal,
        sleep=lambda _: _no_sleep(),
    )
    values = {
        "request": request,
        "decision": decision,
        "candidate": candidate(),
        "account": account(),
        "market": market(),
        "positions": (),
        "confirmation": confirmation,
        "evaluation_timestamp": NOW,
    }
    values.update(updates)
    return asyncio.run(engine.execute(**values)), engine, journal  # type: ignore[arg-type]


async def _no_sleep() -> None:
    return None


def test_complete_accepted_chain_reconciles_and_journals() -> None:
    outcome, engine, journal = _execute(FakeExecutionBroker())
    assert outcome.result.status is ExecutionStatus.ACCEPTED
    assert outcome.reconciliation is not None
    assert outcome.reconciliation.status is ReconciliationStatus.RECONCILED
    assert outcome.demo_position is not None
    assert outcome.demo_position.quantity == Decimal("1")
    assert engine.broker.submission_calls == 1  # type: ignore[attr-defined]
    events = journal.records()  # type: ignore[attr-defined]
    assert [item.sequence for item in events] == list(range(1, len(events) + 1))
    assert all(item.execution_request_id == outcome.result.execution_request_id for item in events)


def test_broker_rejection_is_not_accepted_or_reconciled() -> None:
    rejected = BrokerConfirmation(
        deal_reference="deal-ref-1",
        status=BrokerConfirmationStatus.REJECTED,
        broker_reason="INSUFFICIENT_FUNDS",
        confirmed_at=NOW,
    )
    outcome, _, _ = _execute(FakeExecutionBroker(confirmations=(rejected,)))
    assert outcome.result.status is ExecutionStatus.REJECTED
    assert outcome.reconciliation is None
    assert ExecutionReasonCode.BROKER_REJECTED in outcome.result.reason_codes


def test_confirmation_stop_mismatch_requires_reconciliation() -> None:
    mismatch = BrokerConfirmation(
        deal_reference="deal-ref-1",
        deal_id="deal-id-1",
        status=BrokerConfirmationStatus.ACCEPTED,
        epic="CS.D.TEST.CFD.IP",
        direction="BUY",
        executed_level=Decimal("100"),
        executed_size=Decimal("1"),
        stop_level=Decimal("94"),
        limit_level=Decimal("110"),
        confirmed_at=NOW,
    )
    broker = FakeExecutionBroker(confirmations=(mismatch,))
    outcome, _, _ = _execute(broker)
    assert outcome.result.status is ExecutionStatus.RECONCILIATION_REQUIRED
    assert broker.submission_calls == 1


def test_pending_confirmation_times_out_without_second_submission() -> None:
    pending = BrokerConfirmation(
        deal_reference="deal-ref-1",
        status=BrokerConfirmationStatus.PENDING,
        confirmed_at=NOW,
    )
    configuration = enabled_configuration(
        maximum_confirmation_wait_seconds=Decimal("1"),
        confirmation_poll_interval_seconds=Decimal("0.5"),
    )
    broker = FakeExecutionBroker(confirmations=(pending,))
    outcome, _, _ = _execute(broker, configuration=configuration)
    assert outcome.result.status is ExecutionStatus.RECONCILIATION_REQUIRED
    assert broker.submission_calls == 1
    assert broker.confirmation_calls == 2


def test_ambiguous_submission_is_consumed_and_never_retried() -> None:
    broker = FakeExecutionBroker(
        failure=ExecutionBrokerError("timeout", operation="open_position", ambiguous=True)
    )
    configuration = enabled_configuration()
    request, confirmation, decision = request_and_confirmation(configuration=configuration)
    store = ExecutionIdempotencyStore()
    engine = ExecutionEngine(broker, configuration=configuration, idempotency=store)
    values = {
        "request": request,
        "decision": decision,
        "candidate": candidate(),
        "account": account(),
        "market": market(),
        "positions": (),
        "confirmation": confirmation,
        "evaluation_timestamp": NOW,
    }
    first = asyncio.run(engine.execute(**values))
    second = asyncio.run(engine.execute(**values))
    assert first.result.status is ExecutionStatus.RECONCILIATION_REQUIRED
    assert second.result.status is ExecutionStatus.NOT_SUBMITTED
    assert broker.submission_calls == 1
    restored = ExecutionIdempotencyStore(store.snapshot())
    assert restored.intent_consumed(request.approved_intent_id)


def test_reconciliation_mismatches_are_recorded_not_corrected() -> None:
    broker = FakeExecutionBroker(positions=(open_position(size=Decimal("0.5")),))
    outcome, _, _ = _execute(broker)
    assert outcome.reconciliation is not None
    assert outcome.reconciliation.status is ReconciliationStatus.RECONCILIATION_MISMATCH
    assert "QUANTITY_MISMATCH" in outcome.reconciliation.discrepancies
    assert outcome.demo_position is None


def test_position_not_found_is_explicit() -> None:
    outcome, _, _ = _execute(FakeExecutionBroker(positions=()))
    assert outcome.reconciliation is not None
    assert outcome.reconciliation.status is ReconciliationStatus.POSITION_NOT_FOUND


def test_position_fetch_failure_becomes_pending_reconciliation() -> None:
    class UnavailablePositionsBroker(FakeExecutionBroker):
        async def get_open_positions(self):  # type: ignore[no-untyped-def]
            raise RuntimeError("unavailable")

    outcome, _, _ = _execute(UnavailablePositionsBroker())
    assert outcome.result.status is ExecutionStatus.ACCEPTED
    assert outcome.reconciliation is not None
    assert outcome.reconciliation.status is ReconciliationStatus.RECONCILIATION_PENDING
    assert outcome.demo_position is None


def test_disabled_execution_never_calls_broker() -> None:
    configuration = enabled_configuration().model_copy(update={"execution_enabled": False})
    broker = FakeExecutionBroker()
    outcome, _, _ = _execute(broker, configuration=configuration)
    assert outcome.result.status is ExecutionStatus.NOT_SUBMITTED
    assert broker.submission_calls == 0
