from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from trading_desk import cli
from trading_desk.config import AppSettings
from trading_desk.context.models import ContextTimeframe
from trading_desk.context.operational import HolidayEntry, HolidayImpact
from trading_desk.opportunity.config import (
    DemoExplorationConfiguration,
    MarketUniverse,
)
from trading_desk.opportunity.errors import OpportunityStateError
from trading_desk.opportunity.runtime import AutonomousOpportunityRunner
from trading_desk.opportunity.scheduler import plan_completed_bars
from trading_desk.opportunity.state import OpportunityStateStore

NOW = datetime(2026, 7, 17, 12, 2, tzinfo=UTC)


def test_opportunity_history_request_uses_exact_strategy_minimum() -> None:
    settings = AppSettings()
    assert cli._opportunity_history_points(settings) == 220  # noqa: SLF001
    undersized = settings.model_copy(
        update={"broker": settings.broker.model_copy(update={"max_historical_price_points": 219})}
    )
    with pytest.raises(ValueError, match="below the strategy minimum"):
        cli._opportunity_history_points(undersized)  # noqa: SLF001


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


def test_certification_cli_dispatches_to_read_only_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def scan(args):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        assert args.enable_opportunity_engine
        return 0

    monkeypatch.setattr(cli, "_run_read_only_certification_scan", scan)
    result = cli.main(
        [
            "opportunity",
            "certify-readonly",
            "--enable-opportunity-engine",
            "--economic-calendar",
            "events.json",
            "--holiday-calendar",
            "holidays.json",
        ]
    )
    assert result == 0
    assert calls == 1


def test_certification_holds_lock_through_broker_scan_and_releases_on_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state_path = tmp_path / "certification-state.json"

    class Broker:
        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return self

        async def __aexit__(self, *args):  # type: ignore[no-untyped-def]
            return None

        async def get_accounts(self):  # type: ignore[no-untyped-def]
            balance = SimpleNamespace(
                balance=0,
                profit_loss=0,
            )
            return (
                SimpleNamespace(
                    account_id="masked-test-account",
                    preferred=True,
                    currency="USD",
                    balance=balance,
                ),
            )

    class Exposure:
        async def snapshot(self, observed_at):  # type: ignore[no-untyped-def]
            del observed_at
            return SimpleNamespace(existing_epics=())

    class Provider:
        diagnostics = ()

        async def evaluate(self, *args):  # type: ignore[no-untyped-def]
            del args
            with pytest.raises(OpportunityStateError, match="lock is active"):
                OpportunityStateStore(state_path).acquire_lock()
            raise RuntimeError("stop after proving lock ownership")

    monkeypatch.setattr(cli.AppSettings, "from_environment", lambda: AppSettings())
    monkeypatch.setattr(cli, "LocalJSONEconomicCalendar", lambda path: object())
    monkeypatch.setattr(cli, "LocalJSONHolidayCalendar", lambda path: object())
    monkeypatch.setattr(cli, "OperationalCandidateContextProvider", lambda *args: object())
    monkeypatch.setattr(
        cli, "_opportunity_repository", lambda path: SimpleNamespace(close=lambda: None)
    )
    monkeypatch.setattr(cli, "IGDemoClient", lambda settings: Broker())
    monkeypatch.setattr(cli, "OperationalExposureProvider", lambda *args: Exposure())
    monkeypatch.setattr(
        cli, "OperationalOpportunityEvidenceProvider", lambda *args, **kwargs: Provider()
    )
    args = SimpleNamespace(
        enable_opportunity_engine=True,
        economic_calendar=str(tmp_path / "events.json"),
        holiday_calendar=str(tmp_path / "holidays.json"),
        state_file=str(state_path),
        journal=str(tmp_path / "journal.db"),
    )
    with pytest.raises(RuntimeError, match="proving lock ownership"):
        asyncio.run(cli._run_read_only_certification_scan(args))  # noqa: SLF001
    assert not state_path.with_suffix(".json.lock").exists()


def test_read_only_observer_runs_bounded_cycles_and_releases_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = 0

    async def run(args):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        OpportunityStateStore(Path(args.state_file)).save(
            OpportunityStateStore(Path(args.state_file)).load()
        )
        return 0

    async def no_wait(awaitable, timeout):  # type: ignore[no-untyped-def]
        del timeout
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr(cli, "_run_read_only_opportunity_cycle", run)
    monkeypatch.setattr(cli.asyncio, "wait_for", no_wait)
    state_path = tmp_path / "opportunity.json"
    result = cli.main(
        [
            "opportunity",
            "observe",
            "--enable-opportunity-engine",
            "--economic-calendar",
            "events.json",
            "--holiday-calendar",
            "holidays.json",
            "--state-file",
            str(state_path),
            "--cycles",
            "3",
            "--interval-seconds",
            "15",
        ]
    )
    assert result == 0
    assert calls == 3
    assert not Path(f"{state_path}.observer.lock").exists()


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


def test_lifecycle_certification_requires_extra_enable_switch() -> None:
    result = cli.main(
        [
            "demo-exploration",
            "certify-lifecycle",
            "--enable-opportunity-engine",
            "--enable-demo-exploration",
            "--enable-execution",
            "--economic-calendar",
            "events.json",
            "--holiday-calendar",
            "holidays.json",
        ]
    )
    assert result == 2


def test_lifecycle_certification_rejects_temporary_or_empty_calendars() -> None:
    valid_holidays = SimpleNamespace(source_identifier="operator-holidays-v1")
    with pytest.raises(ValueError, match="temporary weekend"):
        cli._validate_certification_calendar_sources(  # noqa: SLF001
            SimpleNamespace(
                source_identifier="certification-weekend-events-v1", events=(object(),)
            ),
            valid_holidays,
        )
    with pytest.raises(ValueError, match="populated economic calendar"):
        cli._validate_certification_calendar_sources(  # noqa: SLF001
            SimpleNamespace(source_identifier="operator-events-v1", events=()),
            valid_holidays,
        )


def test_scheduler_never_returns_current_unfinished_bar() -> None:
    market = (
        MarketUniverse()
        .require_enabled("EUR/USD")
        .model_copy(update={"supported_timeframes": (ContextTimeframe.HOUR,)})
    )
    planned = plan_completed_bars(MarketUniverse(markets=(market,)), NOW)
    assert planned[0].completed_bar_timestamp == datetime(2026, 7, 17, 11, tzinfo=UTC)


@pytest.mark.parametrize(
    "observed_at",
    (
        datetime(2026, 7, 17, 21, 5, tzinfo=UTC),
        datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
        datetime(2026, 7, 19, 20, 59, tzinfo=UTC),
    ),
)
def test_scheduler_suppresses_closed_forex_weekend(observed_at: datetime) -> None:
    market = (
        MarketUniverse()
        .require_enabled("EUR/USD")
        .model_copy(update={"supported_timeframes": (ContextTimeframe.MINUTE_5,)})
    )
    assert plan_completed_bars(MarketUniverse(markets=(market,)), observed_at) == ()


def test_scheduler_resumes_after_sunday_forex_open() -> None:
    market = (
        MarketUniverse()
        .require_enabled("EUR/USD")
        .model_copy(update={"supported_timeframes": (ContextTimeframe.MINUTE_5,)})
    )
    planned = plan_completed_bars(
        MarketUniverse(markets=(market,)),
        datetime(2026, 7, 19, 21, 10, tzinfo=UTC),
    )
    assert planned[0].completed_bar_timestamp == datetime(2026, 7, 19, 21, 5, tzinfo=UTC)


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


def test_currency_holiday_closes_only_affected_markets() -> None:
    universe = MarketUniverse()
    holiday = HolidayEntry(
        date=NOW.date(),
        name="JPY bank holiday",
        currencies=("JPY",),
        impact=HolidayImpact.HOLIDAY,
    )
    global_dates, market_dates = cli._holiday_scheduler_closures(  # noqa: SLF001
        universe, (holiday,)
    )
    assert global_dates == ()
    assert market_dates == (
        ("EUR/JPY", NOW.date().isoformat()),
        ("USD/JPY", NOW.date().isoformat()),
    )
    planned = plan_completed_bars(
        universe,
        NOW,
        closed_market_dates=market_dates,
    )
    instruments = {item.instrument_id for item in planned}
    assert "EUR/JPY" not in instruments
    assert "USD/JPY" not in instruments
    assert {"EUR/USD", "GBP/USD", "AUD/USD", "USD/CAD"} <= instruments


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


def test_certification_runner_stops_gracefully_after_position_observation(tmp_path: Path) -> None:
    state = OpportunityStateStore(tmp_path / "state.json")
    scheduler = FakeScheduler(state)
    orchestrator = FakeOrchestrator()
    lifecycle = FakeLifecycle()
    observations = 0

    def position_observed() -> bool:
        nonlocal observations
        observations += 1
        return observations == 2

    runner = AutonomousOpportunityRunner(
        orchestrator,  # type: ignore[arg-type]
        scheduler,  # type: ignore[arg-type]
        lifecycle,
        DemoExplorationConfiguration(
            enabled=True,
            scheduler_poll_interval_seconds=1,
        ),
        tmp_path / "restart-runner.json",
        sleep=lambda _: asyncio.sleep(0),
    )

    health = asyncio.run(
        runner.run(
            asyncio.Event(),
            explicit_demo_enable=True,
            maximum_iterations=10,
            stop_when=position_observed,
        )
    )

    assert health.cycles_completed == 2
    assert health.reason_codes == ("POSITION_OBSERVED_RESTART_REQUIRED",)
    assert not (tmp_path / "restart-runner.json.lock").exists()
