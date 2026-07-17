from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal

from journal_helpers import configuration as journal_configuration
from lifecycle_helpers import (
    NOW,
    FakeCloseBroker,
    enabled_configuration,
    open_position,
    risk,
    snapshot,
)
from trading_desk.journal.models import JournalQuery, JournalRecordType
from trading_desk.journal.sqlite import SQLiteJournalRepository
from trading_desk.journal.writer import DurableJournalWriter
from trading_desk.lifecycle.engine import DemoPositionLifecycleEngine
from trading_desk.lifecycle.journal import DurableLifecycleJournal
from trading_desk.lifecycle.models import ExitReason, LifecycleEventType, StrategyExitState
from trading_desk.lifecycle.monitor import (
    LifecycleContextProvider,
    PersistentPositionLifecycleMonitor,
)
from trading_desk.lifecycle.review import compare_paper_demo_exit
from trading_desk.lifecycle.state import LifecycleStateStore


class StaticProvider(LifecycleContextProvider):
    async def snapshots(self, now):  # type: ignore[no-untyped-def]
        del now
        return (snapshot(current_bid=Decimal("95"), current_mark=Decimal("95")),)

    async def risk_state(self, position, now):  # type: ignore[no-untyped-def]
        del position, now
        return risk()

    async def strategy_exit(self, position, now):  # type: ignore[no-untyped-def]
        del position, now
        return StrategyExitState.HOLD


class SequencedCloseBroker(FakeCloseBroker):
    def __init__(self) -> None:
        super().__init__(positions_after=())
        self.position_reads = 0

    async def get_open_positions(self):  # type: ignore[no-untyped-def]
        self.position_reads += 1
        return (open_position(),) if self.position_reads == 1 else ()


def test_reconciled_close_creates_durable_lineage_and_review(tmp_path) -> None:  # type: ignore[no-untyped-def]
    with SQLiteJournalRepository(journal_configuration(tmp_path / "journal.db")) as repository:
        writer = DurableJournalWriter(repository)
        writer.append_source(
            record_type=JournalRecordType.STRATEGY_SIGNAL,
            source_record_id="execution-1",
            source={"action": "LONG_CANDIDATE"},
            created_at=NOW,
            environment="DEMO",
        )
        journal = DurableLifecycleJournal(writer)
        outcome = asyncio.run(
            DemoPositionLifecycleEngine(
                FakeCloseBroker(positions_after=()),
                configuration=enabled_configuration(),
                journal=journal,
            ).evaluate_and_manage(
                snapshot=snapshot(current_bid=Decimal("95"), current_mark=Decimal("95")),
                risk=risk(),
                strategy_exit=StrategyExitState.HOLD,
                positions=(open_position(),),
                evaluation_timestamp=NOW,
            )
        )
        assert outcome.reconciliation is not None
        records = repository.query(JournalQuery(limit=100)).records
        types = tuple(record.record_type for record in records)
        assert JournalRecordType.POSITION_CLOSED in types
        assert JournalRecordType.POST_TRADE_REVIEW in types
        assert all(record.environment == "DEMO" for record in records)
        lifecycle_records = records[1:]
        assert all(record.source_parent_ids for record in lifecycle_records)
        assert lifecycle_records[0].source_parent_ids == ("execution-1",)
        assert LifecycleEventType.POST_TRADE_REVIEW_CREATED in {
            record.event_type for record in journal.records()
        }


def test_paper_demo_comparison_is_deterministic_and_analytical() -> None:
    values = {
        "position_id": "position-1",
        "paper_exit_timestamp": NOW,
        "demo_exit_timestamp": NOW + timedelta(seconds=5),
        "paper_exit_price": Decimal("101"),
        "demo_exit_price": Decimal("100.8"),
        "paper_costs": Decimal("0.1"),
        "demo_costs": Decimal("0.2"),
        "paper_pnl": Decimal("1"),
        "demo_pnl": Decimal("0.8"),
        "paper_holding_duration": timedelta(hours=1),
        "demo_holding_duration": timedelta(hours=1, seconds=5),
        "paper_exit_reason": ExitReason.PROFIT_TARGET,
        "demo_exit_reason": ExitReason.PROTECTIVE_STOP,
    }
    first = compare_paper_demo_exit(**values)
    assert first == compare_paper_demo_exit(**values)
    assert first.exit_slippage_difference == Decimal("-0.2")
    assert first.exit_reason_difference
    assert "close" not in type(first).model_fields


def test_persistent_monitor_prevents_replay_after_restart(tmp_path) -> None:  # type: ignore[no-untyped-def]
    broker = SequencedCloseBroker()
    store = LifecycleStateStore(tmp_path / "state.json")
    monitor = PersistentPositionLifecycleMonitor(
        broker,
        StaticProvider(),
        store,
        enabled_configuration(),
    )
    outcomes = asyncio.run(monitor.run_cycle(NOW))
    assert outcomes[0].result is not None
    assert broker.submission_calls == 1
    state = store.load()
    assert dict(state.daily_close_counts)[NOW.date()] == 1
    assert state.idempotency.consumed_close_requests
    replay = asyncio.run(monitor.run_cycle(NOW + timedelta(seconds=1)))
    assert replay[0].result is None
    assert broker.submission_calls == 1
