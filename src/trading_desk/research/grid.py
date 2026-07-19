"""Frozen bounded parameter-grid expansion for research experiments."""

from __future__ import annotations

from decimal import Decimal
from itertools import product

from trading_desk.research.models import ExperimentSpecification, ParameterRange


class SearchSpaceError(ValueError):
    """Raised when a search space violates its frozen bounds."""


def expand_grid(
    parameter_space: tuple[ParameterRange, ...], maximum_trials: int
) -> tuple[tuple[tuple[str, Decimal], ...], ...]:
    """Deterministic cartesian expansion of the frozen search space.

    The expansion order is fixed (axis declaration order, ascending values),
    so the same specification always produces the same trial sequence. The
    trial budget is enforced before execution, never by silent truncation.
    """

    axes = [[(axis.name, value) for value in axis.values()] for axis in parameter_space]
    combinations = tuple(tuple(combo) for combo in product(*axes))
    if len(combinations) > maximum_trials:
        raise SearchSpaceError(
            f"search space of {len(combinations)} trials exceeds the frozen budget "
            f"of {maximum_trials}; shrink the space or raise the budget explicitly"
        )
    return combinations


def neighbor_indices(
    specification: ExperimentSpecification,
    combinations: tuple[tuple[tuple[str, Decimal], ...], ...],
    index: int,
) -> tuple[int, ...]:
    """Indices of grid points differing by exactly one step on one axis."""

    steps = {axis.name: axis.step for axis in specification.parameter_space}
    center = dict(combinations[index])
    neighbors: list[int] = []
    for other_index, combination in enumerate(combinations):
        if other_index == index:
            continue
        other = dict(combination)
        differing = [name for name in center if other[name] != center[name]]
        if len(differing) == 1:
            name = differing[0]
            if abs(other[name] - center[name]) == steps[name]:
                neighbors.append(other_index)
    return tuple(neighbors)
