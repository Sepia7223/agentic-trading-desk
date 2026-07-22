"""Tests for the vendored SPA test and combinatorial purged CV splits."""

from __future__ import annotations

import numpy as np
import pytest

from trading_desk.trials import combinatorial_purged_splits, spa_test
from trading_desk.trials.spa import stationary_bootstrap_indices

RNG = np.random.default_rng(7)
N = 750  # ~3 years of daily observations


def noise(scale: float = 0.01) -> np.ndarray:
    return RNG.normal(0.0, scale, N)


# ------------------------------------------------------------------------ SPA


def test_spa_accepts_genuine_edge():
    bench = noise()
    good = bench + 0.004 + RNG.normal(0, 0.002, N)  # real, sizable edge
    result = spa_test(bench, {"good": good}, n_boot=600, seed=1)
    assert result["p_value"] < 0.05


def test_spa_rejects_pure_noise_candidate():
    bench = noise()
    lucky = bench + RNG.normal(0, 0.01, N)  # no true edge
    result = spa_test(bench, {"lucky": lucky}, n_boot=600, seed=2)
    assert result["p_value"] > 0.10


def test_spa_is_not_fooled_by_best_of_many_noise():
    """The core property: selecting the best of 20 noise candidates must NOT
    yield significance — SPA accounts for the search."""

    bench = noise()
    candidates = {f"n{i}": bench + RNG.normal(0, 0.01, N) for i in range(20)}
    result = spa_test(bench, candidates, n_boot=600, seed=3)
    assert result["p_value"] > 0.10


def test_spa_finds_real_edge_among_noise():
    bench = noise()
    candidates = {f"n{i}": bench + RNG.normal(0, 0.01, N) for i in range(10)}
    candidates["real"] = bench + 0.005 + RNG.normal(0, 0.002, N)
    result = spa_test(bench, candidates, n_boot=600, seed=4)
    assert result["p_value"] < 0.05


def test_spa_deterministic_and_validated():
    bench = noise()
    cand = {"a": bench + RNG.normal(0, 0.01, N)}
    r1 = spa_test(bench, cand, n_boot=200, seed=9)
    r2 = spa_test(bench, cand, n_boot=200, seed=9)
    assert r1 == r2
    with pytest.raises(ValueError, match="at least one candidate"):
        spa_test(bench, {})
    with pytest.raises(ValueError, match="align"):
        spa_test(bench, {"bad": bench[:-5] * 1.0})
    with pytest.raises(ValueError, match="at least 30"):
        spa_test(bench[:10], {"a": bench[:10] * 1.0})


def test_stationary_bootstrap_shape_and_range():
    idx = stationary_bootstrap_indices(100, 50, 10.0, np.random.default_rng(0))
    assert idx.shape == (50, 100)
    assert idx.min() >= 0 and idx.max() < 100


# ----------------------------------------------------------------------- CPCV


def test_cpcv_produces_all_combinations():
    splits = combinatorial_purged_splits(600, n_groups=6, test_groups=2)
    assert len(splits) == 15  # C(6,2)


def test_cpcv_no_overlap_and_purge_gap():
    label_span, embargo = 5, 3
    splits = combinatorial_purged_splits(
        600, n_groups=6, test_groups=2, label_span=label_span, embargo=embargo
    )
    for train, test in splits:
        train_set, test_set = set(train.tolist()), set(test.tolist())
        assert not train_set & test_set
        # purge: a training sample within label_span BEFORE any test index
        # would carry a label window reaching into the test set
        for t in test_set:
            for k in range(1, label_span + 1):
                assert (t - k) not in train_set
        # embargo: no training sample within embargo AFTER a test block end
        test_sorted = np.sort(test)
        block_ends = [
            int(test_sorted[i])
            for i in range(len(test_sorted))
            if i == len(test_sorted) - 1 or test_sorted[i + 1] != test_sorted[i] + 1
        ]
        for end in block_ends:
            for k in range(1, embargo + 1):
                assert end + k not in train_set


def test_cpcv_input_validation():
    with pytest.raises(ValueError):
        combinatorial_purged_splits(100, n_groups=1)
    with pytest.raises(ValueError):
        combinatorial_purged_splits(100, n_groups=4, test_groups=4)
    with pytest.raises(ValueError):
        combinatorial_purged_splits(3, n_groups=6)
    with pytest.raises(ValueError):
        combinatorial_purged_splits(100, n_groups=4, label_span=-1)
