from datetime import UTC, datetime, timedelta
from decimal import Decimal

from context_helpers import snapshot
from trading_desk.backtest.contextual import (
    ContextualTradeObservation,
    summarize_contextual_performance,
)
from trading_desk.context.models import ContextTimeframe
from trading_desk.scheduler.clock import completed_bar_boundary
from trading_desk.scheduler.engine import DeterministicScheduler, JsonSchedulerStateStore
from trading_desk.scheduler.models import ScheduledActionType, SchedulerState


def test_completed_bar_identity_does_not_depend_on_sleep_timing() -> None:
    first = datetime(2026, 7, 15, 14, 2, tzinfo=UTC)
    second = datetime(2026, 7, 15, 14, 4, 59, tzinfo=UTC)
    assert completed_bar_boundary(first, ContextTimeframe.MINUTE_5) == completed_bar_boundary(
        second, ContextTimeframe.MINUTE_5
    )


def test_scheduler_deduplicates_restart_and_halt(tmp_path) -> None:
    scheduler = DeterministicScheduler()
    now = datetime(2026, 7, 15, 14, 2, tzinfo=UTC)
    first = scheduler.plan_cycle(now, SchedulerState())
    state = scheduler.apply(SchedulerState(), first)
    assert any(item.action_type is ScheduledActionType.STRATEGY_BAR for item in first.actions)
    assert scheduler.plan_cycle(now, state).actions == ()
    store = JsonSchedulerStateStore(tmp_path / "scheduler.json")
    store.save(state)
    assert store.load() == state
    halted = scheduler.plan_cycle(now + timedelta(minutes=5), state, execution_halted=True)
    assert all(item.action_type is not ScheduledActionType.STRATEGY_BAR for item in halted.actions)


def test_scheduler_recovers_only_current_completed_boundaries() -> None:
    scheduler = DeterministicScheduler()
    now = datetime(2026, 7, 15, 15, 7, tzinfo=UTC)
    cycle = scheduler.plan_cycle(now, SchedulerState())
    bars = [item.completed_bar_timestamp for item in cycle.actions if item.completed_bar_timestamp]
    assert bars
    assert all(item <= now for item in bars)


def _observation(index: int, *, future: bool = False) -> ContextualTradeObservation:
    closed = datetime(2026, 7, 15, tzinfo=UTC) + timedelta(days=index + (100 if future else 0))
    return ContextualTradeObservation(
        strategy_id="trend-regime-v1",
        return_fraction=Decimal("0.01") if index % 2 == 0 else Decimal("-0.004"),
        cost=Decimal("0.001"),
        maximum_favorable_excursion=Decimal("0.02"),
        maximum_adverse_excursion=Decimal("-0.006"),
        exposure_fraction=Decimal("0.5"),
        turnover=Decimal("1"),
        closed_at=closed,
        context=snapshot(evaluation_timestamp=closed, data_cutoff_timestamp=closed),
    )


def test_contextual_expectancy_groups_metrics_and_excludes_future_records() -> None:
    observations = tuple(_observation(index) for index in range(4)) + (
        _observation(0, future=True),
    )
    cutoff = datetime(2026, 7, 20, tzinfo=UTC)
    result = summarize_contextual_performance(
        observations, cutoff_timestamp=cutoff, minimum_sample_size=5
    )
    assert len(result) == 1
    summary = result[0]
    assert summary.sample_size == 4
    assert not summary.sufficient_sample
    assert summary.costs == Decimal("0.004")
    assert dict(summary.group)["strategy"] == "trend-regime-v1"


def test_contextual_expectancy_fingerprint_is_stable() -> None:
    values = tuple(_observation(index) for index in range(3))
    cutoff = datetime(2026, 7, 20, tzinfo=UTC)
    assert summarize_contextual_performance(values, cutoff_timestamp=cutoff) == (
        summarize_contextual_performance(values, cutoff_timestamp=cutoff)
    )
