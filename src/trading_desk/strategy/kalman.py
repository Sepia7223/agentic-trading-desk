"""Explicit local-linear-trend Kalman filter for deterministic price trends."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from trading_desk.strategy.configuration import StrategyConfiguration
from trading_desk.strategy.models import KalmanStep, KalmanTrendResult

KALMAN_MODEL_VERSION = "local-linear-v2"


def fit_local_linear_trend(
    observations: Sequence[float], config: StrategyConfiguration
) -> KalmanTrendResult:
    count = len(observations)
    if count < config.kalman_minimum_observations:
        return _not_ready(count, "insufficient observations for Kalman trend")
    values = np.asarray(observations, dtype=np.float64)
    if values.ndim != 1 or not np.all(np.isfinite(values)):
        return _not_ready(count, "Kalman observations are non-finite or malformed")

    transition = np.array([[1.0, 1.0], [0.0, 1.0]], dtype=np.float64)
    observation_matrix = np.array([[1.0, 0.0]], dtype=np.float64)
    identity = np.eye(2, dtype=np.float64)
    process_covariance = np.diag(
        [config.kalman_process_level_noise, config.kalman_process_slope_noise]
    ).astype(np.float64)
    observation_variance = float(config.kalman_observation_noise)
    state = np.array([values[0], 0.0], dtype=np.float64)
    covariance = np.diag(
        [config.kalman_initial_level_variance, config.kalman_initial_slope_variance]
    ).astype(np.float64)
    steps: list[KalmanStep] = []

    for value in values:
        predicted_state = transition @ state
        predicted_covariance = transition @ covariance @ transition.T + process_covariance
        innovation = float(value - (observation_matrix @ predicted_state)[0])
        innovation_variance = float(
            (observation_matrix @ predicted_covariance @ observation_matrix.T)[0, 0]
            + observation_variance
        )
        if not math.isfinite(innovation_variance) or innovation_variance <= 0:
            return _not_ready(count, "Kalman innovation variance is not positive")

        gain = (predicted_covariance @ observation_matrix.T) / innovation_variance
        state = predicted_state + gain[:, 0] * innovation
        residual_transform = identity - gain @ observation_matrix
        covariance = (
            residual_transform @ predicted_covariance @ residual_transform.T
            + gain * observation_variance @ gain.T
        )
        covariance = (covariance + covariance.T) / 2.0
        if not _valid_covariance(covariance) or not np.all(np.isfinite(state)):
            return _not_ready(count, "Kalman state or covariance became invalid")

        level_variance = max(float(covariance[0, 0]), 0.0)
        slope_variance = max(float(covariance[1, 1]), 0.0)
        step_values = (
            float(state[0]),
            float(state[1]),
            float(predicted_state[0]),
            innovation,
            innovation_variance,
            innovation / math.sqrt(innovation_variance),
            math.sqrt(level_variance),
            math.sqrt(slope_variance),
        )
        if not all(math.isfinite(item) for item in step_values):
            return _not_ready(count, "Kalman output became non-finite")
        level_scale = max(abs(step_values[0]), 1e-12)
        normalized_slope = step_values[1] / level_scale
        normalized_slope_uncertainty = step_values[7] / level_scale
        if not math.isfinite(normalized_slope) or not math.isfinite(normalized_slope_uncertainty):
            return _not_ready(count, "Kalman normalized slope became non-finite")
        steps.append(
            KalmanStep(
                filtered_level=step_values[0],
                filtered_slope=step_values[1],
                predicted_level=step_values[2],
                innovation=step_values[3],
                innovation_variance=step_values[4],
                normalized_innovation=step_values[5],
                level_uncertainty=step_values[6],
                slope_uncertainty=step_values[7],
                normalized_slope=normalized_slope,
                normalized_slope_uncertainty=normalized_slope_uncertainty,
            )
        )

    final = steps[-1]
    deviation_variance = final.level_uncertainty**2 + observation_variance
    if not math.isfinite(deviation_variance) or deviation_variance <= 0:
        return _not_ready(count, "Kalman deviation variance is not positive")
    normalized_deviation = (float(values[-1]) - final.filtered_level) / math.sqrt(
        deviation_variance
    )
    if not math.isfinite(normalized_deviation):
        return _not_ready(count, "Kalman normalized deviation is non-finite")
    return KalmanTrendResult(
        ready=True,
        current_filtered_level=final.filtered_level,
        current_slope=final.filtered_slope,
        current_slope_uncertainty=final.slope_uncertainty,
        current_normalized_slope=final.normalized_slope,
        current_normalized_slope_uncertainty=final.normalized_slope_uncertainty,
        normalized_price_deviation=normalized_deviation,
        observations_used=count,
        steps=tuple(steps),
    )


def _valid_covariance(covariance: NDArray[np.float64]) -> bool:
    if covariance.shape != (2, 2) or not np.all(np.isfinite(covariance)):
        return False
    eigenvalues = np.linalg.eigvalsh(covariance)
    return bool(np.all(np.isfinite(eigenvalues)) and np.min(eigenvalues) >= -1e-10)


def _not_ready(observations: int, reason: str) -> KalmanTrendResult:
    return KalmanTrendResult(ready=False, reason=reason, observations_used=observations)
