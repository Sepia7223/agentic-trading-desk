"""Combinatorial purged cross-validation splits (Lopez de Prado, AFML ch. 7/12).

Research-stage evaluation for signals whose labels span time: ordinary k-fold
leaks because training labels overlap test windows. This splitter:

- partitions the sample into ``n_groups`` contiguous time groups;
- forms every combination of ``test_groups`` groups as a test set
  (C(n_groups, test_groups) paths instead of one walk-forward path);
- PURGES training samples whose label window (``label_span`` observations
  after the sample) overlaps any test group;
- EMBARGOES a further ``embargo`` observations after each test group.

Vendored minimal implementation over indices; deterministic; no dependencies
beyond numpy. The locked walk-forward final test remains the last gate — CPCV
is for triage before spending it.
"""

from __future__ import annotations

from itertools import combinations

import numpy as np


def combinatorial_purged_splits(
    n_observations: int,
    *,
    n_groups: int = 6,
    test_groups: int = 2,
    label_span: int = 0,
    embargo: int = 0,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Return [(train_idx, test_idx), ...] over all group combinations."""

    if n_groups < 2:
        raise ValueError("n_groups must be >= 2")
    if not (1 <= test_groups < n_groups):
        raise ValueError("test_groups must be in [1, n_groups)")
    if n_observations < n_groups:
        raise ValueError("more groups than observations")
    if label_span < 0 or embargo < 0:
        raise ValueError("label_span and embargo must be >= 0")

    bounds = np.linspace(0, n_observations, n_groups + 1, dtype=int)
    groups = [np.arange(bounds[i], bounds[i + 1]) for i in range(n_groups)]

    splits: list[tuple[np.ndarray, np.ndarray]] = []
    all_idx = np.arange(n_observations)
    for combo in combinations(range(n_groups), test_groups):
        test_idx = np.concatenate([groups[g] for g in combo])
        blocked = np.zeros(n_observations, dtype=bool)
        blocked[test_idx] = True
        for g in combo:
            start, end = int(groups[g][0]), int(groups[g][-1])
            # purge: a training sample at t uses labels over [t, t+label_span];
            # any t whose label window reaches into the test group is dropped.
            purge_from = max(0, start - label_span)
            blocked[purge_from:start] = True
            # embargo: observations immediately after the test group are
            # serially correlated with it; drop them from training too.
            embargo_to = min(n_observations, end + 1 + embargo)
            blocked[end + 1 : embargo_to] = True
        train_idx = all_idx[~blocked]
        splits.append((train_idx, np.sort(test_idx)))
    return splits
