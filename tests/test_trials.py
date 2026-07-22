"""Tests for the trial registry and Probabilistic/Deflated Sharpe ratios."""

from __future__ import annotations

from pathlib import Path

import pytest

from trading_desk.trials import (
    TrialRegistry,
    deflated_sharpe_ratio,
    expected_max_sharpe,
    probabilistic_sharpe_ratio,
)

# ------------------------------------------------------------------------ PSR


def test_psr_confident_when_sharpe_clears_benchmark_with_long_sample():
    psr = probabilistic_sharpe_ratio(0.1, 0.0, n_observations=2000)
    assert psr > 0.99


def test_psr_uncertain_with_short_sample():
    long = probabilistic_sharpe_ratio(0.1, 0.0, n_observations=2000)
    short = probabilistic_sharpe_ratio(0.1, 0.0, n_observations=30)
    assert short < long
    assert 0.5 < short < 0.75  # positive but far from proven


def test_psr_at_benchmark_is_half():
    assert probabilistic_sharpe_ratio(0.05, 0.05, 500) == pytest.approx(0.5)


def test_psr_negative_skew_fat_tails_reduce_confidence():
    clean = probabilistic_sharpe_ratio(0.15, 0.0, 500, skewness=0.0, kurtosis=3.0)
    ugly = probabilistic_sharpe_ratio(0.15, 0.0, 500, skewness=-1.5, kurtosis=8.0)
    assert ugly < clean


# ------------------------------------------------------------------------ DSR


def test_expected_max_sharpe_grows_with_trials():
    one = expected_max_sharpe(1, 0.01)
    ten = expected_max_sharpe(10, 0.01)
    thousand = expected_max_sharpe(1000, 0.01)
    assert one == 0.0
    assert 0 < ten < thousand


def test_dsr_punishes_heavy_search():
    # same observed Sharpe: credible if it was the only trial,
    # not credible if it was the best of 500
    honest = deflated_sharpe_ratio(0.1, n_trials=1, sharpe_variance=0.005, n_observations=750)
    mined = deflated_sharpe_ratio(0.1, n_trials=500, sharpe_variance=0.005, n_observations=750)
    assert honest > 0.99
    assert mined < 0.75
    assert mined < honest


def test_dsr_input_validation():
    with pytest.raises(ValueError):
        expected_max_sharpe(0, 0.01)
    with pytest.raises(ValueError):
        expected_max_sharpe(10, -0.1)
    with pytest.raises(ValueError):
        probabilistic_sharpe_ratio(0.1, 0.0, 1)


# ------------------------------------------------------------------- registry


def test_registry_appends_and_dedupes_by_fingerprint(tmp_path: Path):
    reg = TrialRegistry(tmp_path / "trials.jsonl")
    reg.record("momentum", {"lookback": 252}, 0.05, 800, "2022..2025")
    reg.record("momentum", {"lookback": 126}, 0.02, 800, "2022..2025")
    # re-run of an existing config: not a new trial
    reg.record("momentum", {"lookback": 252}, 0.05, 800, "2022..2025")
    assert reg.trial_count("momentum") == 2
    assert reg.trial_count() == 2


def test_registry_variance_uses_latest_run_per_config(tmp_path: Path):
    reg = TrialRegistry(tmp_path / "trials.jsonl")
    reg.record("f", {"a": 1}, 0.10, 500, "w")
    reg.record("f", {"a": 2}, 0.02, 500, "w")
    reg.record("f", {"a": 1}, 0.04, 500, "w")  # re-run supersedes 0.10
    n, var = reg.dsr_inputs("f")
    assert n == 2
    values = sorted([0.02, 0.04])
    mean = sum(values) / 2
    expected = sum((v - mean) ** 2 for v in values) / 2
    assert var == pytest.approx(expected)


def test_registry_family_filter_and_empty(tmp_path: Path):
    reg = TrialRegistry(tmp_path / "trials.jsonl")
    assert reg.trial_count() == 0
    assert reg.sharpe_variance() == 0.0
    reg.record("a", {"x": 1}, 0.1, 100, "w")
    reg.record("b", {"x": 1}, 0.2, 100, "w")
    assert reg.trial_count("a") == 1
    assert reg.trial_count() == 2
