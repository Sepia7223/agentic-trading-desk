"""Restart-safe completed-bar scheduling and autonomous Demo runtime control."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from trading_desk.opportunity.config import DemoExplorationConfiguration, MarketUniverse
from trading_desk.opportunity.orchestrator import (
    OpportunityOrchestrator,
    PositionLifecyclePort,
)
from trading_desk.opportunity.scheduler import (
    ScheduledOpportunityEvaluation,
    plan_completed_bars,
)
from trading_desk.opportunity.state import OpportunityStateStore


class OpportunityRuntimeHealth(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    observed_at: datetime
    running: bool
    cycles_completed: int = Field(ge=0)
    lifecycle_cycles_completed: int = Field(ge=0)
    missed_evaluations: int = Field(ge=0)
    last_cycle_id: str | None = None
    entry_halted: bool
    reason_codes: tuple[str, ...] = ()


class CompletedBarSchedulerService:
    def __init__(
        self,
        universe: MarketUniverse,
        state_store: OpportunityStateStore,
        *,
        maximum_catch_up_bars: int,
        closed_dates: tuple[str, ...] = (),
        closed_market_dates: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.universe = universe
        self.state_store = state_store
        self.maximum_catch_up_bars = maximum_catch_up_bars
        self.closed_dates = closed_dates
        self.closed_market_dates = closed_market_dates

    def due(self, observed_at: datetime) -> tuple[ScheduledOpportunityEvaluation, ...]:
        state = self.state_store.load()
        completed = tuple(
            (instrument, _timeframe(timeframe), timestamp)
            for instrument, timeframe, timestamp in state.last_completed_bars
        )
        return plan_completed_bars(
            self.universe,
            observed_at,
            last_completed=completed,
            maximum_catch_up_bars=self.maximum_catch_up_bars,
            closed_dates=self.closed_dates,
            closed_market_dates=self.closed_market_dates,
        )


class AutonomousOpportunityRunner:
    def __init__(
        self,
        orchestrator: OpportunityOrchestrator,
        scheduler: CompletedBarSchedulerService,
        lifecycle: PositionLifecyclePort,
        configuration: DemoExplorationConfiguration,
        process_lock_path: Path,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.orchestrator = orchestrator
        self.scheduler = scheduler
        self.lifecycle = lifecycle
        self.configuration = configuration
        self.process_lock = OpportunityStateStore(process_lock_path)
        self.clock = clock
        self.sleep = sleep
        self.health = OpportunityRuntimeHealth(
            observed_at=clock(),
            running=False,
            cycles_completed=0,
            lifecycle_cycles_completed=0,
            missed_evaluations=0,
            entry_halted=False,
        )

    async def run(
        self,
        stop: asyncio.Event,
        *,
        explicit_demo_enable: bool,
        maximum_iterations: int | None = None,
        stop_when: Callable[[], bool] | None = None,
    ) -> OpportunityRuntimeHealth:
        descriptor = self.process_lock.acquire_lock()
        cycles = 0
        lifecycle_cycles = 0
        missed = 0
        last_cycle_id: str | None = None
        last_lifecycle_at: datetime | None = None
        self.health = self.health.model_copy(update={"running": True})
        try:
            iterations = 0
            while not stop.is_set():
                now = self.clock().astimezone(UTC)
                due = self.scheduler.due(now)
                if due:
                    persisted = self.scheduler.state_store.load()
                    result = await self.orchestrator.run(
                        now,
                        explicit_demo_enable=explicit_demo_enable,
                        entry_halted=persisted.entries_halted,
                        unresolved_execution_ambiguity=(
                            "UNRESOLVED_EXECUTION_AMBIGUITY" in persisted.halt_reasons
                        ),
                        reconciliation_mismatch=(
                            "RECONCILIATION_MISMATCH" in persisted.halt_reasons
                        ),
                        scheduled_evaluations=due,
                    )
                    cycles += 1
                    lifecycle_cycles += 1
                    last_lifecycle_at = now
                    last_cycle_id = result.cycle.cycle_id
                    missed += len(result.cycle.skipped_evaluation_ids)
                elif last_lifecycle_at is None or now - last_lifecycle_at >= timedelta(
                    seconds=self.configuration.lifecycle_interval_seconds
                ):
                    await self.lifecycle.monitor(now)
                    lifecycle_cycles += 1
                    last_lifecycle_at = now
                self.health = OpportunityRuntimeHealth(
                    observed_at=now,
                    running=True,
                    cycles_completed=cycles,
                    lifecycle_cycles_completed=lifecycle_cycles,
                    missed_evaluations=missed,
                    last_cycle_id=last_cycle_id,
                    entry_halted=self.scheduler.state_store.load().entries_halted,
                )
                iterations += 1
                if stop_when is not None and stop_when():
                    self.health = self.health.model_copy(
                        update={"reason_codes": ("POSITION_OBSERVED_RESTART_REQUIRED",)}
                    )
                    break
                if maximum_iterations is not None and iterations >= maximum_iterations:
                    break
                with suppress(TimeoutError):
                    await asyncio.wait_for(
                        stop.wait(),
                        timeout=self.configuration.scheduler_poll_interval_seconds,
                    )
            return self.health.model_copy(update={"observed_at": self.clock(), "running": False})
        finally:
            self.process_lock.release_lock(descriptor)


def _timeframe(value: str):  # type: ignore[no-untyped-def]
    from trading_desk.context.models import ContextTimeframe

    return ContextTimeframe(value)
