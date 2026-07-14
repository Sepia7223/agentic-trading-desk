from __future__ import annotations

import math
import warnings
from types import SimpleNamespace

import numpy as np
import pytest

from trading_desk.strategy.configuration import StrategyConfiguration
from trading_desk.strategy.kalman import fit_local_linear_trend
from trading_desk.strategy.models import Regime
from trading_desk.strategy.regime import (
    build_causal_features,
    fit_regime_model,
    map_hidden_states,
)


def _permissive_config(**overrides: object) -> StrategyConfiguration:
    values: dict[str, object] = {
        "minimum_regime_probability": 0.0,
        "maximum_regime_uncertainty": 1.0,
        "hmm_minimum_effective_observations": 3.0,
    }
    values.update(overrides)
    return StrategyConfiguration.model_validate(values)


def _regime_closes(last_regime: str) -> np.ndarray:
    random = np.random.default_rng(10)
    regimes = {
        "bull": random.normal(0.005, 0.001, 130),
        "transitional": random.normal(0.0, 0.010, 130),
        "bear": random.normal(-0.006, 0.025, 130),
    }
    order = [name for name in ("bull", "transitional", "bear") if name != last_regime]
    order.append(last_regime)
    returns = np.concatenate([regimes[name] for name in order])
    return 100.0 * np.exp(np.cumsum(returns))


@pytest.mark.parametrize(
    ("last_regime", "expected"),
    [
        ("bull", Regime.BULL_LOW_VOL),
        ("transitional", Regime.TRANSITIONAL),
        ("bear", Regime.BEAR_HIGH_VOL),
    ],
)
def test_synthetic_regimes_map_to_semantic_states(last_regime: str, expected: Regime) -> None:
    config = _permissive_config()
    closes = _regime_closes(last_regime)
    kalman = fit_local_linear_trend(closes.tolist(), config)
    result = fit_regime_model(closes.tolist(), kalman, config)

    assert result.ready is True, result.reason
    assert result.current_regime is expected
    assert math.isclose(sum(item.probability for item in result.probabilities), 1.0, abs_tol=1e-8)


def test_state_index_permutations_do_not_change_semantic_mapping() -> None:
    statistics = np.array(
        [
            [0.004, 0.003, 0.002],
            [0.000, 0.012, 0.000],
            [-0.006, 0.025, -0.004],
        ]
    )
    original = map_hidden_states(statistics)
    permutation = np.array([2, 0, 1])
    permuted = map_hidden_states(statistics[permutation])

    original_by_statistics = {
        tuple(statistics[index]): regime for index, regime in original.items()
    }
    permuted_by_statistics = {
        tuple(statistics[permutation[index]]): regime for index, regime in permuted.items()
    }
    assert original_by_statistics == permuted_by_statistics


def test_fixed_seed_produces_reproducible_hmm_result() -> None:
    config = _permissive_config()
    closes = _regime_closes("bull")
    kalman = fit_local_linear_trend(closes.tolist(), config)

    first = fit_regime_model(closes.tolist(), kalman, config)
    second = fit_regime_model(closes.tolist(), kalman, config)

    assert first.model_dump() == second.model_dump()


def test_nonconvergence_fails_closed_without_retry() -> None:
    config = _permissive_config(
        hmm_training_iterations=2,
        hmm_convergence_tolerance=1e-12,
    )
    closes = _regime_closes("bull")
    kalman = fit_local_linear_trend(closes.tolist(), config)
    result = fit_regime_model(closes.tolist(), kalman, config)

    assert result.ready is False
    assert result.converged is False
    assert result.reason is not None and "did not converge" in result.reason


def test_singular_features_fail_closed() -> None:
    config = _permissive_config()
    closes = [100.0] * 300
    kalman = fit_local_linear_trend(closes, config)
    result = fit_regime_model(closes, kalman, config)

    assert result.ready is False
    assert result.reason is not None and "singular" in result.reason


def test_insufficient_effective_state_observations_fail_closed() -> None:
    config = _permissive_config(hmm_minimum_effective_observations=50.0)
    random = np.random.default_rng(3)
    returns = np.concatenate(
        [
            random.normal(0.004, 0.001, 300),
            random.normal(0.0, 0.01, 45),
            random.normal(-0.005, 0.02, 45),
        ]
    )
    closes = 100.0 * np.exp(np.cumsum(returns))
    kalman = fit_local_linear_trend(closes.tolist(), config)
    result = fit_regime_model(closes.tolist(), kalman, config)

    assert result.ready is False
    assert result.reason is not None and "effective observations" in result.reason


def test_scaler_statistics_use_only_the_training_window() -> None:
    config = _permissive_config()
    closes = _regime_closes("bull")
    kalman = fit_local_linear_trend(closes.tolist(), config)
    features = build_causal_features(closes.tolist(), kalman, config.hmm_rolling_window)
    result = fit_regime_model(closes.tolist(), kalman, config)

    assert result.feature_statistics is not None
    np.testing.assert_allclose(result.feature_statistics.means, features.values.mean(axis=0))
    np.testing.assert_allclose(result.feature_statistics.scales, features.values.std(axis=0))


def test_causal_features_before_a_cutoff_ignore_appended_future_values() -> None:
    config = _permissive_config()
    prefix = _regime_closes("transitional")
    extended = np.concatenate([prefix, np.linspace(prefix[-1] * 2, prefix[-1] * 3, 30)])
    prefix_kalman = fit_local_linear_trend(prefix.tolist(), config)
    extended_kalman = fit_local_linear_trend(extended.tolist(), config)
    prefix_features = build_causal_features(
        prefix.tolist(), prefix_kalman, config.hmm_rolling_window
    )
    extended_features = build_causal_features(
        extended.tolist(), extended_kalman, config.hmm_rolling_window
    )

    np.testing.assert_allclose(
        prefix_features.values,
        extended_features.values[: len(prefix_features.values)],
        rtol=0,
        atol=1e-12,
    )


def test_twenty_raw_bars_cannot_fit_hmm_after_rolling_feature_loss() -> None:
    config = _permissive_config()
    result = fit_regime_model([100.0 + index for index in range(20)], None, config)

    assert result.ready is False
    assert result.observations_used == 0
    assert result.reason is not None and "rolling-window loss" in result.reason


def test_hmm_usable_observation_floor_counts_rolling_window_loss() -> None:
    config = _permissive_config()
    raw_count = config.hmm_rolling_window + config.hmm_minimum_feature_observations - 1
    closes = [100.0 + index * 0.1 for index in range(raw_count)]
    result = fit_regime_model(closes, None, config)

    assert result.ready is False
    assert result.observations_used == config.hmm_minimum_feature_observations - 1
    assert result.reason is not None and "usable HMM feature observations" in result.reason


def test_endpoint_probability_is_last_cutoff_smoothed_posterior() -> None:
    config = _permissive_config()
    closes = _regime_closes("bull")
    kalman = fit_local_linear_trend(closes.tolist(), config)
    result = fit_regime_model(closes.tolist(), kalman, config)

    assert result.probability_method == "endpoint_smoothed_posterior"
    assert len(result.endpoint_hidden_state_probabilities) == 3
    semantic = {item.regime: item.probability for item in result.probabilities}
    mapping = {item.hidden_state: item.regime for item in result.state_mapping}
    for state, probability in enumerate(result.endpoint_hidden_state_probabilities):
        assert semantic[mapping[state]] == pytest.approx(probability)


def test_exact_and_near_mapping_ties_fail_closed() -> None:
    exact = np.ones((3, 3))
    near = np.array(
        [
            [0.001, 0.0100, 0.0010],
            [0.00100001, 0.010001, 0.00100001],
            [0.00100002, 0.010002, 0.00100002],
        ]
    )
    with pytest.raises(ValueError, match="ambiguous"):
        map_hidden_states(exact)
    with pytest.raises(ValueError, match="ambiguous"):
        map_hidden_states(near, minimum_score_margin=10.0)


def test_mapping_handles_conflicting_return_and_volatility_with_unique_labels() -> None:
    statistics = np.array(
        [
            [0.010, 0.040, 0.006],
            [0.004, 0.002, 0.003],
            [-0.008, 0.030, -0.006],
        ]
    )
    mapping = map_hidden_states(statistics)

    assert set(mapping.values()) == {
        Regime.BULL_LOW_VOL,
        Regime.TRANSITIONAL,
        Regime.BEAR_HIGH_VOL,
    }
    assert len(mapping) == len(set(mapping.values())) == 3


@pytest.mark.parametrize(
    "closes",
    [
        [100.0] * 300,
        [100.0 + index * 1e-12 for index in range(300)],
        [*([100.0] * 299), 1e9],
        [1e-8 + index * 1e-11 for index in range(300)],
        [1e12 + index * 1e8 for index in range(300)],
    ],
)
def test_feature_scaling_extremes_are_finite_or_fail_closed_safely(
    closes: list[float],
) -> None:
    config = _permissive_config()
    kalman = fit_local_linear_trend(closes, config)
    result = fit_regime_model(closes, kalman if kalman.ready else None, config)

    if result.ready:
        assert result.feature_statistics is not None
        assert all(math.isfinite(value) for value in result.feature_statistics.means)
        assert all(math.isfinite(value) for value in result.feature_statistics.scales)
    else:
        assert result.reason is not None


def test_invalid_hmm_transition_matrix_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    class InvalidMatrixHMM:
        def __init__(self, **_: object) -> None:
            self.monitor_ = SimpleNamespace(converged=True, history=(0.0, 0.0))
            self.startprob_ = np.array([0.4, 0.3, 0.3])
            self.transmat_ = np.array([[0.8, 0.1, 0.0], [0.2, 0.7, 0.1], [0.1, 0.1, 0.8]])
            self.means_ = np.zeros((3, 5))
            self.covars_ = np.ones((3, 5))

        def fit(self, values: np.ndarray) -> InvalidMatrixHMM:
            return self

        def predict_proba(self, values: np.ndarray) -> np.ndarray:
            return np.full((len(values), 3), 1 / 3)

    monkeypatch.setattr("trading_desk.strategy.regime.GaussianHMM", InvalidMatrixHMM)
    closes = _regime_closes("bull")
    config = _permissive_config()
    kalman = fit_local_linear_trend(closes.tolist(), config)
    result = fit_regime_model(closes.tolist(), kalman, config)

    assert result.ready is False
    assert result.reason is not None and "not normalized" in result.reason


def test_unsafe_numerical_warning_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    class WarningHMM:
        def __init__(self, **_: object) -> None:
            self.monitor_ = SimpleNamespace(converged=True, history=(0.0, 0.0))
            self.startprob_ = np.full(3, 1 / 3)
            self.transmat_ = np.full((3, 3), 1 / 3)
            self.means_ = np.zeros((3, 5))
            self.covars_ = np.ones((3, 5))

        def fit(self, values: np.ndarray) -> WarningHMM:
            warnings.warn("degenerate solution", RuntimeWarning, stacklevel=2)
            return self

        def predict_proba(self, values: np.ndarray) -> np.ndarray:
            return np.full((len(values), 3), 1 / 3)

    monkeypatch.setattr("trading_desk.strategy.regime.GaussianHMM", WarningHMM)
    closes = _regime_closes("bull")
    config = _permissive_config()
    kalman = fit_local_linear_trend(closes.tolist(), config)
    result = fit_regime_model(closes.tolist(), kalman, config)

    assert result.ready is False
    assert result.reason is not None and "unsafe numerical warning" in result.reason
    assert result.fitting_warnings == ("RuntimeWarning",)
