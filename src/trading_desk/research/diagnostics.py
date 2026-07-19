"""Overfitting and multiple-comparison diagnostics for research runs.

These diagnostics exist to make selection bias visible: searching N parameter
combinations guarantees that the best-looking result overstates true skill,
so every run reports how good the best trial would look under pure chance,
how much performance decays out of the selection window, and whether the
optimum is an isolated spike its neighbors do not support.
"""

from __future__ import annotations

import math
from decimal import Decimal

from trading_desk.research.grid import neighbor_indices
from trading_desk.research.models import (
    ExperimentDiagnostics,
    ExperimentSpecification,
    ObjectiveName,
    TrialResult,
)


def expected_best_under_null(
    trial_count: int, objective: ObjectiveName, per_trade_volatility: Decimal
) -> Decimal | None:
    """Expected best objective across N independent skill-free trials.

    Uses the standard extreme-value approximation E[max of N standard
    normals] ~= sqrt(2 ln N). For expectancy-like objectives the null scale
    is the per-trade volatility; for ratio objectives the scale is 1.
    """

    if trial_count < 1:
        return None
    scale = per_trade_volatility if objective is ObjectiveName.NET_EXPECTANCY else Decimal("1")
    if trial_count == 1:
        return Decimal("0")
    return (scale * Decimal(str(math.sqrt(2.0 * math.log(trial_count))))).quantize(
        Decimal("0.00000001")
    )


def degradation(inner: Decimal | None, outer: Decimal | None) -> Decimal | None:
    """Fractional performance decay from the selection stage to evaluation."""

    if inner is None or outer is None or inner == 0:
        return None
    return ((inner - outer) / abs(inner)).quantize(Decimal("0.00000001"))


def neighborhood_stability(
    specification: ExperimentSpecification,
    combinations: tuple[tuple[tuple[str, Decimal], ...], ...],
    trials: tuple[TrialResult, ...],
    best_index: int,
) -> tuple[Decimal | None, bool]:
    """Mean neighbor objective around the optimum, and spike rejection.

    An optimum whose one-step neighbors average below zero (or that has no
    neighbors at all in a multi-point space) is rejected as an isolated
    spike: real edges occupy regions, not single grid points.
    """

    objective = specification.objective
    by_index = {trial.trial_index: trial for trial in trials}
    neighbors = neighbor_indices(specification, combinations, best_index)
    values: list[Decimal] = []
    for index in neighbors:
        neighbor = by_index.get(index)
        if neighbor is None:
            continue
        value = neighbor.outer_evaluation.objective_value(objective)
        if value is not None:
            values.append(value)
    if not values:
        return None, len(combinations) > 1
    mean = sum(values, Decimal(0)) / Decimal(len(values))
    return mean.quantize(Decimal("0.00000001")), mean <= 0


def build_diagnostics(
    specification: ExperimentSpecification,
    combinations: tuple[tuple[tuple[str, Decimal], ...], ...],
    trials: tuple[TrialResult, ...],
    *,
    per_trade_volatility: Decimal,
    benchmark_objective: Decimal = Decimal("0"),
    economic_plausibility_notes: str,
) -> ExperimentDiagnostics:
    objective = specification.objective
    scored: list[tuple[Decimal, TrialResult]] = []
    for trial in trials:
        value = trial.outer_evaluation.objective_value(objective)
        if value is not None:
            scored.append((value, trial))
    best_value: Decimal | None = None
    best: TrialResult | None = None
    if scored:
        best_value, best = max(scored, key=lambda pair: pair[0])
    mean_value = (
        (sum((value for value, _ in scored), Decimal(0)) / Decimal(len(scored))).quantize(
            Decimal("0.00000001")
        )
        if scored
        else None
    )
    stability, spike_rejected = (
        neighborhood_stability(specification, combinations, trials, best.trial_index)
        if best is not None
        else (None, False)
    )
    return ExperimentDiagnostics(
        trial_count=len(combinations),
        completed_trial_count=len(trials),
        best_outer_objective=best_value,
        mean_outer_objective=mean_value,
        expected_best_under_null=expected_best_under_null(
            len(combinations), objective, per_trade_volatility
        ),
        development_to_validation_degradation=degradation(
            best.inner_selection.objective_value(objective) if best else None,
            best_value,
        ),
        neighborhood_stability=stability,
        isolated_optimum_rejected=spike_rejected,
        benchmark_objective=benchmark_objective,
        beats_benchmark=best_value is not None and best_value > benchmark_objective,
        economic_plausibility_notes=economic_plausibility_notes,
    )
