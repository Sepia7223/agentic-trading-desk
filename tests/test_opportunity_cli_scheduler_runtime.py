from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from trading_desk import cli
from trading_desk.context.models import ContextTimeframe
from trading_desk.opportunity.config import (
    DemoExplorationConfiguration,
    MarketUniverse,
)
from trading_desk.opportunity.runtime import AutonomousOpportunityRunner
from trading_desk.opportunity.scheduler import plan_completed_bars
from trading_desk.opportunity.state import OpportunityStateStore

NOW = datetime(2026, 7, 17, 12, 2, tzinfo=UTC)


@pytest.mark.parametrize("command", ("scan-once", "rank-once"))
def test_opportunity_cli_dispatches_to_operational_cycle(
    monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    calls: list[str] = []

    async def run(args):  # type: ignore[no-untyped-def]
        calls.append(args.opportunity_command)
        return 0

    monkeypatch.setattr(cli, "_run_read_only_opportunity_cycle", run)
    result = cli.main(
        [
            "opportunity",
            command,
            "--enable-opportunity-engine",
            "--economic-calendar",
            "events.json",
            "--holiday-calendar",
            "holidays.json",
        ]
    )
    assert result == 0
    assert calls == [command]


def test_demo_exploration_fails_before_configuration_or_authentication() -> None:
    result = cli.main(
        [
            "demo-exploration",
            "run-cycle",
            "--economic-calendar",
            "events.json",
            "--holiday-calendar",
            "holidays.json",
        ]
    )
    assert result == 2


def test_scheduler_never_returns_current_unfinished_bar() -> None:
    market = (
        MarketUniverse()
        .require_enabled("EUR/USD")
        .model_copy(update={"supported_timeframes": (ContextTimeframe.HOUR,)})
    )
    planned = plan_completed_bars(MarketUniverse(markets=(market,)), NOW)
    assert planned[0].completed_bar_timestamp == datetime(2026, 7, 17, 11, tzinfo=UTC)


def test_scheduler_holiday_and_bounded_catchup_are_deterministic() -> None:
    market = (
        MarketUniverse()
        .require_enabled("EUR/USD")
        .model_copy(update={"supported_timeframes": (ContextTimeframe.MINUTE_5,)})
    )
    universe = MarketUniverse(markets=(market,))
    previous = (("EUR/USD", ContextTimeframe.MINUTE_5, NOW - timedelta(hours=1)),)
    planned = plan_completed_bars(
        universe,
        NOW,
        last_completed=previous,
        maximum_catch_up_bars=3,
    )
    assert len(planned) == 3
    assert all(item.completed_bar_timestamp < NOW for item in planned)
    assert (
        plan_completed_bars(
            universe,
            NOW,
            last_completed=previous,
            maximum_catch_up_bars=3,
            closed_dates=(NOW.date().isoformat(),),
        )
        == ()
    )


def test_stale_process_lock_is_reclaimed_by_explicit_policy(tmp_path: Path) -> None:
    store = OpportunityStateStore(tmp_path / "state.json")
    lock = store.path.with_suffix(".json.lock")
    lock.write_text(
        json.dumps({"pid": 999999, "created_at": time.time() - 7200}),
        encoding="utf-8",
    )
    descriptor = store.acquire_lock()
    try:
        assert descriptor >= 0
    finally:
        store.release_lock(descriptor)
    assert not lock.exists()


class FakeScheduler:
    def __init__(self, state_store: OpportunityStateStore) -> None:
        self.state_store = state_store
        self.calls = 0

    def due(self, observed_at):  # type: ignore[no-untyped-def]
        del observed_at
        self.calls += 1
        return (SimpleNamespace(evaluation_id=f"evaluation-{self.calls}"),)


class FakeOrchestrator:
    calls = 0

    async def run(self, observed_at, **kwargs):  # type: ignore[no-untyped-def]
        del observed_at, kwargs
        self.calls += 1
        return SimpleNamespace(
            cycle=SimpleNamespace(
                cycle_id=f"cycle-{self.calls}",
                skipped_evaluation_ids=(),
            )
        )


class FakeLifecycle:
    calls = 0

    async def monitor(self, observed_at):  # type: ignore[no-untyped-def]
        del observed_at
        self.calls += 1
        return ()


def test_continuous_runner_runs_multiple_cycles_and_releases_lock(tmp_path: Path) -> None:
    state = OpportunityStateStore(tmp_path / "state.json")
    scheduler = FakeScheduler(state)
    orchestrator = FakeOrchestrator()
    lifecycle = FakeLifecycle()
    runner = AutonomousOpportunityRunner(
        orchestrator,  # type: ignore[arg-type]
        scheduler,  # type: ignore[arg-type]
        lifecycle,
        DemoExplorationConfiguration(
            enabled=True,
            scheduler_poll_interval_seconds=1,
        ),
        tmp_path / "runner.json",
        sleep=lambda _: asyncio.sleep(0),
    )
    health = asyncio.run(
        runner.run(
            asyncio.Event(),
            explicit_demo_enable=True,
            maximum_iterations=3,
        )
    )
    assert health.cycles_completed == 3
    assert orchestrator.calls == 3
    assert lifecycle.calls == 0
    assert not (tmp_path / "runner.json.lock").exists()
    assert health.running is False
