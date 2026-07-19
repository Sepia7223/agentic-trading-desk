from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from context_helpers import snapshot as base_snapshot
from trading_desk.context.fingerprints import fingerprint
from trading_desk.context.models import MarketContextSnapshot
from trading_desk.strategy.configuration import StrategyConfiguration
from trading_desk.strategy.contracts import (
    StrategyDecision,
    StrategyDirection,
    StrategyEvaluationContext,
    StrategyEvaluationResult,
    strategy_result,
)
from trading_desk.strategy.kalman import fit_local_linear_trend
from trading_desk.strategy.models import StrategyBarResolution
from trading_desk.strategy.validation_runner import (
    CausalContextBuilder,
    HistoricalBar,
    IncrementalKalman,
    SimulatedStrategy,
    SimulationCosts,
    ValidationRunnerError,
    load_bars,
    simulate_strategies,
)

EPIC = "CS.D.TEST.CFD.IP"
START = datetime(2025, 1, 6, tzinfo=UTC)


def bar(
    index: int, *, low_bid: float | None = None, high_bid: float | None = None
) -> HistoricalBar:
    mid = 100.0
    spread = 0.01
    return HistoricalBar(
        timestamp=START + timedelta(hours=index),
        open_bid=mid - spread / 2,
        open_ask=mid + spread / 2,
        high_bid=high_bid if high_bid is not None else mid + 0.05,
        high_ask=(high_bid if high_bid is not None else mid + 0.05) + spread,
        low_bid=low_bid if low_bid is not None else mid - 0.05,
        low_ask=(low_bid if low_bid is not None else mid - 0.05) + spread,
        close_bid=mid - spread / 2,
        close_ask=mid + spread / 2,
        volume=100.0,
    )


class StubContextBuilder(CausalContextBuilder):
    """Real builder mechanics with a deterministic synthetic context snapshot."""

    def snapshot(self, evaluation_timestamp: datetime) -> MarketContextSnapshot | None:
        if not self._bars:
            return None
        template = base_snapshot()
        fields = template.model_dump(mode="python", exclude={"context_id", "context_fingerprint"})
        fields["evaluation_timestamp"] = evaluation_timestamp
        fields["data_cutoff_timestamp"] = self._bars[-1].timestamp
        identity = fingerprint(fields)
        return MarketContextSnapshot.model_validate(
            {**fields, "context_id": identity, "context_fingerprint": identity}
        )


class StubEvaluator:
    strategy_id = "stub-strategy"
    strategy_version = "1.0.0"
    strategy_fingerprint = "f" * 64

    def __init__(self, candidate_cutoffs: set[datetime], stop: str, target: str) -> None:
        self.candidate_cutoffs = candidate_cutoffs
        self.stop = Decimal(stop)
        self.target = Decimal(target)
        self.seen_cutoffs: list[datetime] = []

    def evaluate(self, *, context: StrategyEvaluationContext) -> StrategyEvaluationResult:
        self.seen_cutoffs.append(context.completed_bar_timestamp)
        if context.completed_bar_timestamp not in self.candidate_cutoffs:
            return strategy_result(
                evaluation_id=context.evaluation_id,
                strategy_id=self.strategy_id,
                strategy_version=self.strategy_version,
                strategy_fingerprint=self.strategy_fingerprint,
                instrument_id=context.instrument_id,
                epic=context.epic,
                timeframe=context.timeframe,
                evaluation_timestamp=context.evaluation_timestamp,
                decision=StrategyDecision.REJECT,
                signal_strength=Decimal("0"),
                signal_confidence=Decimal("0"),
                rejection_reasons=("NOT_A_CANDIDATE",),
            )
        return strategy_result(
            evaluation_id=context.evaluation_id,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            strategy_fingerprint=self.strategy_fingerprint,
            instrument_id=context.instrument_id,
            epic=context.epic,
            timeframe=context.timeframe,
            evaluation_timestamp=context.evaluation_timestamp,
            decision=StrategyDecision.CANDIDATE,
            direction=StrategyDirection.LONG,
            signal_strength=Decimal("0.5"),
            signal_confidence=Decimal("0.5"),
            entry_reference=Decimal("100"),
            proposed_stop=self.stop,
            proposed_target=self.target,
            expected_holding_period=timedelta(hours=4),
            estimated_win_probability=Decimal("0.5"),
            estimated_average_gain=self.target - Decimal("100"),
            estimated_average_loss=Decimal("100") - self.stop,
            gross_expected_value=(self.target - Decimal("100")) * Decimal("0.5")
            - (Decimal("100") - self.stop) * Decimal("0.5"),
        )


def build(evaluator: StubEvaluator) -> tuple[SimulatedStrategy, StubContextBuilder]:
    strategy = SimulatedStrategy(
        evaluator=evaluator,
        maximum_holding_bars=4,
        configuration_fingerprint="c" * 64,
    )
    builder = StubContextBuilder(
        epic=EPIC,
        instrument="Test market",
        resolution=StrategyBarResolution.HOUR,
        strategy_configuration=StrategyConfiguration(),
        window_size=8,
        evaluator_window=4,
    )
    return strategy, builder


def test_incremental_kalman_matches_reference() -> None:
    config = StrategyConfiguration()
    random.seed(7)
    prices = [1.10]
    for _ in range(499):
        prices.append(prices[-1] * (1 + random.gauss(0.00005, 0.001)))
    reference = fit_local_linear_trend(prices, config)
    incremental = IncrementalKalman(config)
    for value in prices:
        incremental.update(value)
    mine = incremental.result()
    assert reference.ready and mine.ready
    for name in (
        "current_filtered_level",
        "current_slope",
        "current_slope_uncertainty",
        "current_normalized_slope",
        "current_normalized_slope_uncertainty",
        "normalized_price_deviation",
    ):
        assert math.isclose(
            getattr(reference, name), getattr(mine, name), rel_tol=1e-9, abs_tol=1e-12
        )


def test_load_bars_rejects_epic_mismatch_and_disorder(tmp_path: Path) -> None:
    header = (
        "epic,timestamp,open_bid,open_ask,high_bid,high_ask,"
        "low_bid,low_ask,close_bid,close_ask,last_traded_volume"
    )
    row = "{epic},{ts},1,1.1,1.2,1.3,0.9,1.0,1.05,1.15,10"
    wrong = tmp_path / "wrong.csv"
    wrong.write_text(
        header + "\n" + row.format(epic="CS.D.OTHER.CFD.IP", ts="2025-01-06T00:00:00+00:00"),
        encoding="utf-8",
    )
    with pytest.raises(ValidationRunnerError, match="does not match"):
        load_bars(wrong, epic=EPIC)
    disordered = tmp_path / "disordered.csv"
    disordered.write_text(
        header
        + "\n"
        + row.format(epic=EPIC, ts="2025-01-06T01:00:00+00:00")
        + "\n"
        + row.format(epic=EPIC, ts="2025-01-06T00:00:00+00:00"),
        encoding="utf-8",
    )
    with pytest.raises(ValidationRunnerError, match="strictly increasing"):
        load_bars(disordered, epic=EPIC)


def test_entry_fills_on_next_bar_and_end_boundary_is_never_read() -> None:
    signal_at = START + timedelta(hours=3)
    evaluator = StubEvaluator({signal_at}, stop="99.50", target="105")
    strategy, builder = build(evaluator)
    bars = tuple(bar(index) for index in range(10))
    results = simulate_strategies(
        (strategy,),
        bars,
        builder=builder,
        costs=SimulationCosts(),
        evaluation_start=START,
        evaluation_end=START + timedelta(hours=6),
        trade_prefix="test",
    )
    assert evaluator.seen_cutoffs
    assert max(evaluator.seen_cutoffs) <= START + timedelta(hours=6)
    trade = results[0].trades[0]
    assert trade.entry_at == signal_at + timedelta(hours=1)
    assert trade.exit_at > trade.entry_at


def test_adverse_first_stop_beats_target_in_same_bar() -> None:
    signal_at = START + timedelta(hours=2)
    evaluator = StubEvaluator({signal_at}, stop="99.90", target="100.04")
    strategy, builder = build(evaluator)
    bars = list(bar(index) for index in range(8))
    bars[3] = bar(3, low_bid=99.85, high_bid=100.20)
    results = simulate_strategies(
        (strategy,),
        tuple(bars),
        builder=builder,
        costs=SimulationCosts(),
        evaluation_start=START,
        evaluation_end=START + timedelta(hours=7),
        trade_prefix="test",
    )
    trade = results[0].trades[0]
    assert trade.net_pnl < 0
    assert results[0].forced_exit_count == 0


def test_costs_reconcile_with_fill_prices() -> None:
    signal_at = START + timedelta(hours=2)
    evaluator = StubEvaluator({signal_at}, stop="99.50", target="105")
    strategy, builder = build(evaluator)
    bars = tuple(bar(index) for index in range(8))
    costs = SimulationCosts(slippage_bps=Decimal("1"))
    results = simulate_strategies(
        (strategy,),
        bars,
        builder=builder,
        costs=costs,
        evaluation_start=START,
        evaluation_end=START + timedelta(hours=7),
        trade_prefix="test",
    )
    trade = results[0].trades[0]
    entry_mid = Decimal("100")
    entry_fill = Decimal("100.005") + entry_mid * Decimal("1") / Decimal("10000")
    exit_fill = Decimal("99.995") - entry_mid * Decimal("1") / Decimal("10000")
    expected_net = (exit_fill - entry_fill) / entry_mid - trade.funding_cost
    assert abs(trade.net_pnl - expected_net) < Decimal("0.0000001")


def test_maximum_holding_produces_exit_and_conversion_counts() -> None:
    signal_at = START + timedelta(hours=1)
    evaluator = StubEvaluator({signal_at}, stop="99.00", target="105")
    strategy, builder = build(evaluator)
    bars = tuple(bar(index) for index in range(12))
    results = simulate_strategies(
        (strategy,),
        bars,
        builder=builder,
        costs=SimulationCosts(),
        evaluation_start=START,
        evaluation_end=START + timedelta(hours=11),
        trade_prefix="test",
    )
    outcome = results[0]
    assert outcome.candidate_count == 1
    assert outcome.evaluation_count >= 5
    assert len(outcome.trades) == 1
    held = (outcome.trades[0].exit_at - outcome.trades[0].entry_at) // timedelta(hours=1)
    assert held <= 6
