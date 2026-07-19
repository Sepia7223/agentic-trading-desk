"""Governed experiment execution over the Milestone 12 validation harness.

All trials of one experiment run in a single chronological pass per
instrument and timeframe: the causal market context is built once per bar
and shared by every parameterized evaluator, which is evidence-equivalent to
independent single-trial passes (the strategy state machines are identical
code either way) and removes the dominant repeated cost. Equivalence is
asserted by test, not assumed.

Chronological separation is structural: trial selection metrics come from
the development stage, evaluation metrics from the strictly later validation
stage, and the simulation cannot read a bar past the validation boundary —
final-test data is unavailable to optimization by construction.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import pstdev
from typing import Any

from trading_desk.context.fingerprints import fingerprint
from trading_desk.research.cache import TrialCache, trial_cache_key
from trading_desk.research.diagnostics import build_diagnostics
from trading_desk.research.grid import expand_grid
from trading_desk.research.models import (
    ExperimentRecord,
    ExperimentSpecification,
    ExperimentStatus,
    TrialMetrics,
    TrialResult,
    create_record,
    create_trial,
)
from trading_desk.research.registry import ExperimentRegistry
from trading_desk.strategy.configuration import StrategyConfiguration
from trading_desk.strategy.models import StrategyBarResolution
from trading_desk.strategy.portfolio_configuration import (
    GovernedStrategyConfiguration,
    RangeMeanReversionConfiguration,
    TrendPullbackConfiguration,
    VolatilityBreakoutConfiguration,
)
from trading_desk.strategy.range_mean_reversion import RangeMeanReversionEvaluator
from trading_desk.strategy.trend_pullback import TrendPullbackEvaluator
from trading_desk.strategy.validation import ValidationTrade, calculate_metrics
from trading_desk.strategy.validation_orchestration import trades_in_range
from trading_desk.strategy.validation_runner import (
    CausalContextBuilder,
    SimulatedStrategy,
    SimulationCosts,
    load_bars,
    simulate_strategies,
)
from trading_desk.strategy.volatility_breakout import VolatilityBreakoutEvaluator

RESEARCH_CODE_VERSION = "research-runner-v1"

PAIR_EPICS: dict[str, tuple[str, str]] = {
    "AUDUSD": ("CS.D.AUDUSD.CFD.IP", "AUD/USD"),
    "EURJPY": ("CS.D.EURJPY.CFD.IP", "EUR/JPY"),
    "EURUSD": ("CS.D.EURUSD.CFD.IP", "EUR/USD"),
    "GBPUSD": ("CS.D.GBPUSD.CFD.IP", "GBP/USD"),
    "USDCAD": ("CS.D.USDCAD.CFD.IP", "USD/CAD"),
    "USDJPY": ("CS.D.USDJPY.CFD.IP", "USD/JPY"),
}

TIMEFRAME_RESOLUTIONS: dict[str, StrategyBarResolution] = {
    "MINUTE_15": StrategyBarResolution.MINUTE_15,
    "HOUR": StrategyBarResolution.HOUR,
}

FAMILY_TOOLING: dict[str, tuple[type[GovernedStrategyConfiguration], Any]] = {
    "trend-pullback-v1": (TrendPullbackConfiguration, TrendPullbackEvaluator),
    "volatility-breakout": (VolatilityBreakoutConfiguration, VolatilityBreakoutEvaluator),
    "range-mean-reversion": (RangeMeanReversionConfiguration, RangeMeanReversionEvaluator),
}

INTRADAY_CONTEXT_CONFIGURATION = StrategyConfiguration(hmm_covariance_floor=1e-12)
INTRADAY_CONTEXT_WINDOW = 300


class ExperimentCancelled(RuntimeError):
    """Raised internally when a resource budget is exhausted."""


class ResearchAuthorityError(RuntimeError):
    """Raised when an experiment would touch data it must not see."""


@dataclass(frozen=True)
class ExperimentOutcome:
    record: ExperimentRecord
    cache_hits: int
    cache_misses: int


def _code_fingerprint() -> str:
    return fingerprint(
        {
            "research_code_version": RESEARCH_CODE_VERSION,
            "context_configuration": INTRADAY_CONTEXT_CONFIGURATION.fingerprint,
            "context_window": INTRADAY_CONTEXT_WINDOW,
        }
    )


def _trial_configuration(
    family: str, parameters: tuple[tuple[str, Decimal], ...]
) -> GovernedStrategyConfiguration:
    configuration_class, _ = FAMILY_TOOLING[family]
    fields = configuration_class.model_fields
    updates: dict[str, object] = {}
    for name, value in parameters:
        if name not in fields:
            raise ResearchAuthorityError(f"parameter {name!r} is not a governed field")
        annotation = fields[name].annotation
        updates[name] = int(value) if annotation is int else value
    return configuration_class.model_validate(
        {**configuration_class().model_dump(mode="python"), **updates}
    )


def _metrics(trades: tuple[ValidationTrade, ...]) -> TrialMetrics:
    metrics = calculate_metrics(trades)
    return TrialMetrics(
        trade_count=metrics.trade_count,
        net_expectancy=metrics.expectancy,
        profit_factor=metrics.profit_factor,
        sharpe_ratio=metrics.sharpe_ratio,
        maximum_drawdown=metrics.maximum_drawdown,
    )


def run_experiment(
    specification: ExperimentSpecification,
    *,
    bars_root: Path,
    registry: ExperimentRegistry,
    cache_root: Path | None = None,
    started_at: datetime | None = None,
) -> ExperimentOutcome:
    """Execute one frozen experiment and append its record to the registry.

    Failed and cancelled experiments are persisted with whatever trials
    completed; nothing about a run can change strategy lifecycle state.
    """

    started = started_at or datetime.now(tz=UTC)
    clock_start = time.monotonic()
    boundaries = specification.boundaries
    combinations = expand_grid(specification.parameter_space, specification.budget.maximum_trials)
    cache = TrialCache(cache_root or bars_root.parent / "research-cache")
    code_fingerprint = _code_fingerprint()
    boundaries_fingerprint = fingerprint(boundaries.model_dump(mode="python"))
    _, evaluator_class = FAMILY_TOOLING[specification.strategy_family]

    configurations = [
        _trial_configuration(specification.strategy_family, combination)
        for combination in combinations
    ]
    cache_keys = [
        trial_cache_key(
            dataset_fingerprint=specification.dataset_fingerprint,
            code_fingerprint=code_fingerprint,
            boundaries_fingerprint=boundaries_fingerprint,
            pairs=specification.pairs,
            timeframes=specification.timeframes,
            configuration_fingerprint=configuration.fingerprint,
        )
        for configuration in configurations
    ]
    cached: dict[int, TrialResult] = {}
    for index, key in enumerate(cache_keys):
        hit = cache.load(key)
        if hit is not None and hit.trial_index == index:
            cached[index] = hit

    pending = [index for index in range(len(combinations)) if index not in cached]
    trades_by_trial: dict[int, list[ValidationTrade]] = {index: [] for index in pending}
    status = ExperimentStatus.COMPLETED
    status_reason = ""

    try:
        for pair in specification.pairs:
            epic, instrument = PAIR_EPICS[pair]
            for timeframe in specification.timeframes:
                if time.monotonic() - clock_start > specification.budget.maximum_wall_clock_seconds:
                    raise ExperimentCancelled("wall-clock budget exhausted")
                if not pending:
                    continue
                bars = load_bars(bars_root / f"{pair}_{timeframe}.csv", epic=epic)
                if len(bars) > specification.budget.maximum_bars_per_series:
                    raise ExperimentCancelled("series exceeds the bar budget")
                builder = CausalContextBuilder(
                    epic=epic,
                    instrument=instrument,
                    resolution=TIMEFRAME_RESOLUTIONS[timeframe],
                    strategy_configuration=INTRADAY_CONTEXT_CONFIGURATION,
                    window_size=INTRADAY_CONTEXT_WINDOW,
                )
                strategies = tuple(
                    SimulatedStrategy(
                        evaluator=evaluator_class(configurations[index]),
                        maximum_holding_bars=getattr(
                            configurations[index], "maximum_holding_bars", 24
                        ),
                        configuration_fingerprint=configurations[index].fingerprint,
                    )
                    for index in pending
                )
                results = simulate_strategies(
                    strategies,
                    bars,
                    builder=builder,
                    costs=SimulationCosts(),
                    evaluation_start=boundaries.development_start,
                    evaluation_end=boundaries.validation_end,
                    trade_prefix=f"exp-{specification.experiment_id[:8]}-{pair}-{timeframe}",
                )
                for position, index in enumerate(pending):
                    trades_by_trial[index].extend(results[position].trades)
    except ExperimentCancelled as cancelled:
        status = ExperimentStatus.CANCELLED
        status_reason = str(cancelled)
    except (OSError, ValueError, RuntimeError) as error:
        status = ExperimentStatus.FAILED
        status_reason = f"{type(error).__name__}: {error}"

    trials: list[TrialResult] = []
    for index in range(len(combinations)):
        if index in cached:
            trials.append(cached[index])
            continue
        if status is not ExperimentStatus.COMPLETED:
            continue
        trades = tuple(
            sorted(trades_by_trial[index], key=lambda item: (item.entry_at, item.trade_id))
        )
        inner = trades_in_range(trades, boundaries.development_start, boundaries.development_end)
        outer = trades_in_range(trades, boundaries.validation_start, boundaries.validation_end)
        trial = create_trial(
            trial_index=index,
            parameters=tuple((name, str(value)) for name, value in combinations[index]),
            configuration_fingerprint=configurations[index].fingerprint,
            inner_selection=_metrics(inner),
            outer_evaluation=_metrics(outer),
        )
        cache.store(cache_keys[index], trial)
        trials.append(trial)

    ordered_trials = tuple(sorted(trials, key=lambda trial: trial.trial_index))
    diagnostics = None
    ranked: tuple[int, ...] = ()
    if status is ExperimentStatus.COMPLETED and ordered_trials:
        objective = specification.objective
        scored: list[tuple[Decimal, int]] = []
        for trial in ordered_trials:
            value = trial.outer_evaluation.objective_value(objective)
            if value is not None:
                scored.append((value, trial.trial_index))
        ranked = tuple(index for _, index in sorted(scored, key=lambda pair: pair[0], reverse=True))
        pooled = [
            float(trial.outer_evaluation.net_expectancy)
            for trial in ordered_trials
            if trial.outer_evaluation.net_expectancy is not None
        ]
        per_trade_volatility = (
            Decimal(str(pstdev(pooled))) if len(pooled) > 1 else Decimal("0.0001")
        )
        diagnostics = build_diagnostics(
            specification,
            combinations,
            ordered_trials,
            per_trade_volatility=per_trade_volatility,
            economic_plausibility_notes=(
                "Objective values are net of real spread, slippage, and funding on "
                "the approved dataset; review whether the best region's edge has a "
                "plausible market mechanism before any Milestone 12 handoff."
            ),
        )

    record = create_record(
        previous_record_id=registry.head(),
        specification=specification,
        status=status,
        status_reason=status_reason,
        code_fingerprint=code_fingerprint,
        trials=ordered_trials,
        diagnostics=diagnostics,
        ranked_trial_indices=ranked,
        started_at=started,
        finished_at=datetime.now(tz=UTC),
    )
    registry.append(record)
    return ExperimentOutcome(record=record, cache_hits=cache.hits, cache_misses=cache.misses)
