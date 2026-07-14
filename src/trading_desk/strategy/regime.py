"""Causal Gaussian-HMM regime detection with deterministic semantic mapping."""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from itertools import permutations

import numpy as np
from hmmlearn.hmm import GaussianHMM  # type: ignore[import-untyped]
from numpy.typing import NDArray
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

from trading_desk.strategy.configuration import StrategyConfiguration
from trading_desk.strategy.models import (
    FeatureStatistics,
    HMMRegimeResult,
    KalmanTrendResult,
    Regime,
    RegimeProbability,
    StateMapping,
    StateMappingStatistic,
)

HMM_MODEL_VERSION = "gaussian-diagonal-3state-v2"
FEATURE_NAMES = (
    "log_return",
    "realized_volatility",
    "normalized_trend",
    "normalized_level_distance",
    "rolling_drawdown",
)
_SEMANTIC_REGIMES = (
    Regime.BULL_LOW_VOL,
    Regime.TRANSITIONAL,
    Regime.BEAR_HIGH_VOL,
)


@dataclass(frozen=True, slots=True)
class CausalFeatureSet:
    values: NDArray[np.float64]
    source_indices: tuple[int, ...]
    names: tuple[str, ...] = FEATURE_NAMES


def build_causal_features(
    closes: tuple[float, ...] | list[float],
    kalman: KalmanTrendResult | None,
    rolling_window: int,
) -> CausalFeatureSet:
    """Build features at t using observations and Kalman states through t only."""

    values = np.asarray(closes, dtype=np.float64)
    if kalman is not None and len(kalman.steps) != len(values):
        raise ValueError("Kalman steps must align with closes")
    if len(values) <= rolling_window:
        return CausalFeatureSet(
            values=np.empty((0, len(FEATURE_NAMES)), dtype=np.float64),
            source_indices=(),
        )

    log_returns = np.zeros(len(values), dtype=np.float64)
    log_returns[1:] = np.log(values[1:] / values[:-1])
    rows: list[list[float]] = []
    indices: list[int] = []
    for index in range(rolling_window, len(values)):
        return_start = max(1, index - rolling_window + 1)
        return_window = log_returns[return_start : index + 1]
        realized_volatility = float(np.sqrt(np.mean(np.square(return_window))))
        close_window = values[index - rolling_window + 1 : index + 1]
        running_peak = float(np.max(close_window))
        drawdown = float(values[index] / running_peak - 1.0)
        if kalman is not None:
            step = kalman.steps[index]
            normalized_slope = step.normalized_slope
            distance_variance = max(step.level_uncertainty**2, 1e-12)
            level_distance = (float(values[index]) - step.filtered_level) / math.sqrt(
                distance_variance
            )
        else:
            x_values = np.arange(len(close_window), dtype=np.float64)
            centered_x = x_values - x_values.mean()
            denominator = float(np.dot(centered_x, centered_x))
            slope = float(np.dot(centered_x, close_window - close_window.mean()) / denominator)
            level_scale = max(abs(float(close_window[-1])), 1e-12)
            normalized_slope = slope / level_scale
            window_std = float(np.std(close_window))
            level_distance = (
                0.0
                if window_std <= 1e-12
                else (float(close_window[-1]) - float(np.mean(close_window))) / window_std
            )
        row = [
            float(log_returns[index]),
            realized_volatility,
            normalized_slope,
            level_distance,
            drawdown,
        ]
        if not all(math.isfinite(item) for item in row):
            raise ValueError("causal HMM feature became non-finite")
        rows.append(row)
        indices.append(index)
    return CausalFeatureSet(
        values=np.asarray(rows, dtype=np.float64),
        source_indices=tuple(indices),
    )


def fit_regime_model(
    closes: tuple[float, ...] | list[float],
    kalman: KalmanTrendResult | None,
    config: StrategyConfiguration,
) -> HMMRegimeResult:
    empty_probabilities = _probability_models(np.zeros(3, dtype=np.float64))
    if kalman is not None and not kalman.ready:
        return _not_ready("Kalman trend is not ready", empty_probabilities)
    try:
        features = build_causal_features(closes, kalman, config.hmm_rolling_window)
    except ValueError:
        return _not_ready("HMM features could not be constructed", empty_probabilities)
    if len(features.values) < config.hmm_minimum_feature_observations:
        return _not_ready(
            "insufficient usable HMM feature observations after rolling-window loss",
            empty_probabilities,
            observations=len(features.values),
        )
    if not np.all(np.isfinite(features.values)):
        return _not_ready("HMM features are non-finite", empty_probabilities)

    scaler = StandardScaler()
    standardized = scaler.fit_transform(features.values)
    means = np.asarray(scaler.mean_, dtype=np.float64)
    scales = np.asarray(scaler.scale_, dtype=np.float64)
    variances = np.asarray(scaler.var_, dtype=np.float64)
    statistics = FeatureStatistics(
        names=features.names,
        means=tuple(float(value) for value in means),
        scales=tuple(float(value) for value in scales),
    )
    if (
        not np.all(np.isfinite(standardized))
        or not np.all(np.isfinite(means))
        or not np.all(np.isfinite(scales))
        or not np.all(np.isfinite(variances))
        or np.any(variances <= config.hmm_covariance_floor)
    ):
        return _not_ready(
            "HMM feature covariance is singular or invalid",
            empty_probabilities,
            statistics=statistics,
            observations=len(features.values),
        )
    if float(np.max(np.abs(standardized))) > config.maximum_absolute_standardized_feature:
        return _not_ready(
            "standardized HMM feature exceeds the configured magnitude limit",
            empty_probabilities,
            statistics=statistics,
            observations=len(features.values),
        )

    model = GaussianHMM(
        n_components=config.hmm_state_count,
        covariance_type="diag",
        n_iter=config.hmm_training_iterations,
        tol=config.hmm_convergence_tolerance,
        random_state=config.hmm_random_seed,
        min_covar=config.hmm_covariance_floor,
        implementation="log",
    )
    captured_warnings: tuple[str, ...] = ()
    try:
        with warnings.catch_warnings(record=True) as warning_records:
            warnings.simplefilter("always")
            model.fit(standardized)
            posterior = np.asarray(model.predict_proba(standardized), dtype=np.float64)
        captured_warnings = tuple(type(item.message).__name__ for item in warning_records)
    except (ValueError, np.linalg.LinAlgError, FloatingPointError):
        return _not_ready(
            "HMM fitting failed",
            empty_probabilities,
            statistics=statistics,
            observations=len(features.values),
        )

    unsafe_warning_terms = ("converg", "degener", "singular", "covariance", "zero")
    unsafe_warnings = tuple(
        type(item.message).__name__
        for item in warning_records
        if any(term in str(item.message).lower() for term in unsafe_warning_terms)
    )
    if unsafe_warnings:
        return _not_ready(
            "HMM fitting emitted an unsafe numerical warning",
            empty_probabilities,
            statistics=statistics,
            observations=len(features.values),
            fitting_warnings=unsafe_warnings,
        )

    history = tuple(float(value) for value in model.monitor_.history)
    converged = (
        bool(model.monitor_.converged)
        and len(history) >= 2
        and all(math.isfinite(value) for value in history)
        and abs(history[-1] - history[-2]) <= config.hmm_convergence_tolerance
    )
    if not converged:
        return _not_ready(
            "HMM did not converge under configured constraints",
            empty_probabilities,
            statistics=statistics,
            observations=len(features.values),
            fitting_warnings=captured_warnings,
        )
    start_probabilities = np.asarray(model.startprob_, dtype=np.float64)
    transition_matrix = np.asarray(model.transmat_, dtype=np.float64)
    means = np.asarray(model.means_, dtype=np.float64)
    if (
        start_probabilities.shape != (config.hmm_state_count,)
        or not np.all(np.isfinite(start_probabilities))
        or np.any(start_probabilities < 0)
        or not math.isclose(float(start_probabilities.sum()), 1.0, rel_tol=1e-6, abs_tol=1e-6)
        or transition_matrix.shape != (config.hmm_state_count, config.hmm_state_count)
        or not np.all(np.isfinite(transition_matrix))
        or np.any(transition_matrix < 0)
        or not np.allclose(transition_matrix.sum(axis=1), 1.0, rtol=1e-6, atol=1e-6)
        or not np.all(np.isfinite(means))
    ):
        return _not_ready(
            "HMM parameters are non-finite or not normalized",
            empty_probabilities,
            statistics=statistics,
            observations=len(features.values),
            fitting_warnings=captured_warnings,
        )
    if not _valid_hmm_covariance(np.asarray(model.covars_), config.hmm_covariance_floor):
        return _not_ready(
            "HMM covariance is singular or invalid",
            empty_probabilities,
            statistics=statistics,
            observations=len(features.values),
        )
    if (
        posterior.shape != (len(features.values), config.hmm_state_count)
        or not np.all(np.isfinite(posterior))
        or np.any(posterior < 0)
        or not np.allclose(posterior.sum(axis=1), 1.0, rtol=1e-6, atol=1e-6)
    ):
        return _not_ready(
            "HMM posterior probabilities are malformed",
            empty_probabilities,
            statistics=statistics,
            observations=len(features.values),
        )
    effective_observations = posterior.sum(axis=0)
    if np.any(effective_observations < config.hmm_minimum_effective_observations):
        return _not_ready(
            "at least one HMM state has insufficient effective observations",
            empty_probabilities,
            statistics=statistics,
            observations=len(features.values),
        )

    state_statistics = np.empty((config.hmm_state_count, 3), dtype=np.float64)
    for state in range(config.hmm_state_count):
        weights = posterior[:, state]
        weight_total = float(weights.sum())
        state_statistics[state, 0] = float(np.dot(weights, features.values[:, 0]) / weight_total)
        state_statistics[state, 1] = float(np.dot(weights, features.values[:, 1]) / weight_total)
        state_statistics[state, 2] = float(np.dot(weights, features.values[:, 2]) / weight_total)
    try:
        mapping, mapping_statistics = _map_hidden_states_with_statistics(
            state_statistics,
            effective_observations,
            config.hmm_mapping_minimum_score_margin,
        )
    except ValueError:
        return _not_ready(
            "HMM semantic state mapping is ambiguous",
            empty_probabilities,
            statistics=statistics,
            observations=len(features.values),
            fitting_warnings=captured_warnings,
        )
    current_hidden_probabilities = posterior[-1]
    if not math.isclose(float(current_hidden_probabilities.sum()), 1.0, rel_tol=1e-6, abs_tol=1e-6):
        return _not_ready(
            "HMM probabilities do not sum to one",
            empty_probabilities,
            statistics=statistics,
            observations=len(features.values),
        )

    semantic = np.zeros(3, dtype=np.float64)
    regime_index = {regime: index for index, regime in enumerate(_SEMANTIC_REGIMES)}
    for hidden_state, regime in mapping.items():
        semantic[regime_index[regime]] = current_hidden_probabilities[hidden_state]
    probabilities = _probability_models(semantic)
    selected_index = int(np.argmax(semantic))
    current_regime = _SEMANTIC_REGIMES[selected_index]
    selected_probability = float(semantic[selected_index])
    uncertainty = _normalized_entropy(semantic)
    ready = (
        selected_probability >= config.minimum_regime_probability
        and uncertainty <= config.maximum_regime_uncertainty
    )
    reason = None
    if selected_probability < config.minimum_regime_probability:
        reason = "current regime probability is below the configured minimum"
    elif uncertainty > config.maximum_regime_uncertainty:
        reason = "current regime uncertainty exceeds the configured maximum"
    return HMMRegimeResult(
        ready=ready,
        reason=reason,
        current_regime=current_regime,
        probabilities=probabilities,
        selected_regime_probability=selected_probability,
        uncertainty=uncertainty,
        state_mapping=tuple(
            StateMapping(hidden_state=state, regime=regime)
            for state, regime in sorted(mapping.items())
        ),
        converged=True,
        observations_used=len(features.values),
        feature_statistics=statistics,
        probability_method="endpoint_smoothed_posterior",
        mapping_statistics=mapping_statistics,
        fitting_warnings=captured_warnings,
        endpoint_hidden_state_probabilities=tuple(
            float(value) for value in current_hidden_probabilities
        ),
    )


def map_hidden_states(
    state_statistics: NDArray[np.float64], minimum_score_margin: float = 0.20
) -> dict[int, Regime]:
    """Map arbitrary state indices using return, volatility, and slope statistics."""

    statistics = np.asarray(state_statistics, dtype=np.float64)
    if statistics.shape != (3, 3) or not np.all(np.isfinite(statistics)):
        raise ValueError("state statistics must be a finite 3x3 matrix")
    mapping, _ = _map_hidden_states_with_statistics(
        statistics,
        np.ones(3, dtype=np.float64),
        minimum_score_margin,
    )
    return mapping


def _map_hidden_states_with_statistics(
    statistics: NDArray[np.float64],
    effective_observations: NDArray[np.float64],
    minimum_score_margin: float,
) -> tuple[dict[int, Regime], tuple[StateMappingStatistic, ...]]:
    statistics = np.asarray(statistics, dtype=np.float64)
    occupancy = np.asarray(effective_observations, dtype=np.float64)
    if (
        statistics.shape != (3, 3)
        or occupancy.shape != (3,)
        or not np.all(np.isfinite(statistics))
        or not np.all(np.isfinite(occupancy))
    ):
        raise ValueError("state mapping inputs must be finite")
    centered = statistics - statistics.mean(axis=0)
    scales = statistics.std(axis=0)
    safe_scales = np.where(scales > 1e-12, scales, 1.0)
    normalized = centered / safe_scales
    bull_scores = normalized[:, 0] - 0.75 * normalized[:, 1] + normalized[:, 2]
    bear_scores = -normalized[:, 0] + 0.75 * normalized[:, 1] - normalized[:, 2]
    transitional_scores = (
        -np.abs(normalized[:, 0]) - 0.25 * np.abs(normalized[:, 1]) - np.abs(normalized[:, 2])
    )
    assignments = []
    for bull_state, transitional_state, bear_state in permutations(range(3)):
        score = float(
            bull_scores[bull_state]
            + transitional_scores[transitional_state]
            + bear_scores[bear_state]
        )
        assignments.append((score, bull_state, transitional_state, bear_state))
    assignments.sort(key=lambda item: (-item[0], item[1:]))
    best, second = assignments[0], assignments[1]
    if best[0] - second[0] < minimum_score_margin:
        raise ValueError("semantic mapping score margin is ambiguous")
    bull_state, transitional_state, bear_state = best[1:]
    mapping = {
        bull_state: Regime.BULL_LOW_VOL,
        transitional_state: Regime.TRANSITIONAL,
        bear_state: Regime.BEAR_HIGH_VOL,
    }
    summaries = tuple(
        StateMappingStatistic(
            hidden_state=state,
            mean_return=float(statistics[state, 0]),
            mean_volatility=float(statistics[state, 1]),
            mean_trend=float(statistics[state, 2]),
            effective_observations=float(occupancy[state]),
            bull_score=float(bull_scores[state]),
            bear_score=float(bear_scores[state]),
            transitional_score=float(transitional_scores[state]),
        )
        for state in range(3)
    )
    return mapping, summaries


def _valid_hmm_covariance(covariance: NDArray[np.float64], floor: float) -> bool:
    if not np.all(np.isfinite(covariance)):
        return False
    if covariance.ndim == 3:
        return all(float(np.min(np.linalg.eigvalsh(item))) >= floor for item in covariance)
    if covariance.ndim == 2:
        return bool(np.all(covariance >= floor))
    return False


def _normalized_entropy(probabilities: NDArray[np.float64]) -> float:
    positive = probabilities[probabilities > 0]
    entropy = -float(np.sum(positive * np.log(positive)))
    return entropy / math.log(3.0)


def _probability_models(probabilities: NDArray[np.float64]) -> tuple[RegimeProbability, ...]:
    return tuple(
        RegimeProbability(regime=regime, probability=float(probabilities[index]))
        for index, regime in enumerate(_SEMANTIC_REGIMES)
    )


def _not_ready(
    reason: str,
    probabilities: tuple[RegimeProbability, ...],
    *,
    statistics: FeatureStatistics | None = None,
    observations: int = 0,
    fitting_warnings: tuple[str, ...] = (),
) -> HMMRegimeResult:
    return HMMRegimeResult(
        ready=False,
        reason=reason,
        probabilities=probabilities,
        observations_used=observations,
        feature_statistics=statistics,
        fitting_warnings=fitting_warnings,
    )
