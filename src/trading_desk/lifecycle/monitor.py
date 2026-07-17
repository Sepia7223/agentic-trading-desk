"""Bounded lifecycle monitor that manages positions independently of entry signals."""

from datetime import datetime
from typing import Protocol

from trading_desk.lifecycle.config import LifecycleConfiguration
from trading_desk.lifecycle.engine import DemoPositionLifecycleEngine
from trading_desk.lifecycle.errors import LifecycleStateError
from trading_desk.lifecycle.idempotency import LifecycleIdempotencyStore
from trading_desk.lifecycle.journal import InMemoryLifecycleJournal
from trading_desk.lifecycle.models import (
    DemoPositionSnapshot,
    LifecycleOutcome,
    LifecycleRiskState,
    StrategyExitState,
)
from trading_desk.lifecycle.state import LifecycleStateStore, update_state
from trading_desk.ports.position_exit import PositionExitPort


class LifecycleContextProvider(Protocol):
    async def snapshots(self, now: datetime) -> tuple[DemoPositionSnapshot, ...]: ...

    async def risk_state(
        self, snapshot: DemoPositionSnapshot, now: datetime
    ) -> LifecycleRiskState: ...

    async def strategy_exit(
        self, snapshot: DemoPositionSnapshot, now: datetime
    ) -> StrategyExitState: ...


class PositionLifecycleMonitor:
    def __init__(
        self,
        engine: DemoPositionLifecycleEngine,
        provider: LifecycleContextProvider,
    ) -> None:
        self.engine = engine
        self.provider = provider

    async def run_cycle(
        self, now: datetime, *, close_requests_today: int = 0
    ) -> tuple[LifecycleOutcome, ...]:
        snapshots = (await self.provider.snapshots(now))[
            : self.engine.configuration.maximum_positions_monitored
        ]
        outcomes: list[LifecycleOutcome] = []
        for snapshot in snapshots:
            risk = await self.provider.risk_state(snapshot, now)
            strategy = await self.provider.strategy_exit(snapshot, now)
            positions = await self.engine.broker.get_open_positions()
            outcome = await self.engine.evaluate_and_manage(
                snapshot=snapshot,
                risk=risk,
                strategy_exit=strategy,
                positions=positions,
                evaluation_timestamp=now,
                close_requests_today=close_requests_today,
            )
            outcomes.append(outcome)
            if outcome.result is not None and outcome.result.submitted_at is not None:
                break
            if outcome.automatic_lifecycle_halted:
                break
        return tuple(outcomes)


class PersistentPositionLifecycleMonitor:
    """Run one bounded cycle with restart-safe replay and halt protection."""

    def __init__(
        self,
        broker: PositionExitPort,
        provider: LifecycleContextProvider,
        state_store: LifecycleStateStore,
        configuration: LifecycleConfiguration,
    ) -> None:
        self.broker = broker
        self.provider = provider
        self.state_store = state_store
        self.configuration = configuration

    async def run_cycle(self, now: datetime) -> tuple[LifecycleOutcome, ...]:
        descriptor = self.state_store.acquire_lock()
        try:
            state = self.state_store.load()
            if state.automatic_lifecycle_halt:
                raise LifecycleStateError(
                    "persistent lifecycle halt requires explicit human review"
                )
            idempotency = LifecycleIdempotencyStore(state.idempotency)
            journal = InMemoryLifecycleJournal(state.journal_records)
            engine = DemoPositionLifecycleEngine(
                self.broker,
                configuration=self.configuration,
                idempotency=idempotency,
                journal=journal,
            )
            counts = dict(state.daily_close_counts)
            outcomes = await PositionLifecycleMonitor(engine, self.provider).run_cycle(
                now, close_requests_today=counts.get(now.date(), 0)
            )
            submitted = sum(
                1
                for outcome in outcomes
                if outcome.result is not None and outcome.result.submitted_at is not None
            )
            if submitted:
                counts[now.date()] = counts.get(now.date(), 0) + submitted
            unresolved = tuple(
                outcome.request.close_request_id
                for outcome in outcomes
                if outcome.automatic_lifecycle_halted and outcome.request is not None
            )
            mismatches = tuple(
                outcome.reconciliation.reconciliation_id
                for outcome in outcomes
                if outcome.reconciliation is not None and outcome.automatic_lifecycle_halted
            )
            halted = bool(unresolved or mismatches)
            self.state_store.save(
                update_state(
                    state,
                    idempotency=idempotency.snapshot(),
                    journal_records=journal.records(),
                    daily_close_counts=tuple(sorted(counts.items())),
                    last_close_timestamp=now if submitted else state.last_close_timestamp,
                    unresolved_close_states=tuple(
                        sorted(set(state.unresolved_close_states + unresolved))
                    ),
                    reconciliation_mismatches=tuple(
                        sorted(set(state.reconciliation_mismatches + mismatches))
                    ),
                    automatic_lifecycle_halt=halted,
                    halt_reason=("AMBIGUOUS_OR_MISMATCHED_CLOSE" if halted else None),
                )
            )
            return outcomes
        finally:
            self.state_store.release_lock(descriptor)
