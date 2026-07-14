from __future__ import annotations

import math

import numpy as np
import pytest

from trading_desk.strategy.configuration import StrategyConfiguration
from trading_desk.strategy.kalman import fit_local_linear_trend


def _config() -> StrategyConfiguration:
    return StrategyConfiguration()


def test_constant_series_has_near_zero_slope() -> None:
    result = fit_local_linear_trend([100.0] * 100, _config())

    assert result.ready is True
    assert result.current_slope is not None
    assert abs(result.current_slope) < 1e-8


def test_rising_and_falling_series_have_expected_slope_signs() -> None:
    rising = fit_local_linear_trend(np.linspace(100, 130, 120).tolist(), _config())
    falling = fit_local_linear_trend(np.linspace(130, 100, 120).tolist(), _config())

    assert rising.ready and rising.current_slope is not None and rising.current_slope > 0
    assert falling.ready and falling.current_slope is not None and falling.current_slope < 0


def test_noisy_rising_series_remains_finite_and_positive() -> None:
    random = np.random.default_rng(42)
    prices = 100 + np.arange(200) * 0.1 + random.normal(0, 0.2, 200)
    result = fit_local_linear_trend(prices.tolist(), _config())

    assert result.ready is True
    assert result.current_slope is not None and result.current_slope > 0
    assert all(
        math.isfinite(step.level_uncertainty)
        and step.level_uncertainty >= 0
        and math.isfinite(step.slope_uncertainty)
        and step.slope_uncertainty >= 0
        for step in result.steps
    )


def test_price_shock_increases_innovation_magnitude() -> None:
    prices = [100.0 + index * 0.05 for index in range(100)]
    baseline = fit_local_linear_trend(prices, _config())
    shocked = fit_local_linear_trend([*prices, prices[-1] + 20], _config())

    assert baseline.ready and shocked.ready
    normal_innovation = max(abs(step.innovation) for step in baseline.steps[-20:])
    assert abs(shocked.steps[-1].innovation) > normal_innovation * 10


def test_insufficient_or_nonfinite_kalman_data_fails_closed() -> None:
    insufficient = fit_local_linear_trend([100.0] * 10, _config())
    nonfinite = fit_local_linear_trend([100.0] * 20 + [math.nan], _config())

    assert insufficient.ready is False
    assert nonfinite.ready is False


def test_kalman_initialization_and_warmup_are_explicit() -> None:
    config = _config()
    warmup = fit_local_linear_trend([100.0] * (config.kalman_minimum_observations - 1), config)
    ready = fit_local_linear_trend([100.0] * config.kalman_minimum_observations, config)

    assert warmup.ready is False
    assert ready.ready is True
    assert ready.steps[0].filtered_level == 100.0
    assert ready.steps[0].filtered_slope == 0.0
    assert ready.steps[0].level_uncertainty >= 0
    assert ready.steps[0].slope_uncertainty >= 0


def test_normalized_slope_is_comparable_across_price_scales() -> None:
    low = np.linspace(1.0, 1.2, 120)
    high = low * 20_000.0
    low_result = fit_local_linear_trend(low.tolist(), _config())
    high_result = fit_local_linear_trend(high.tolist(), _config())

    assert low_result.current_normalized_slope is not None
    assert high_result.current_normalized_slope is not None
    assert low_result.current_normalized_slope == pytest.approx(
        high_result.current_normalized_slope, rel=0.02
    )
