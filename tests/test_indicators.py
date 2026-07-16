from __future__ import annotations

import math

import pytest

from trading_desk.strategy import indicators


def test_ema_series_seeds_with_sma_and_then_smooths() -> None:
    result = indicators.ema_series([1, 2, 3, 4, 5], 3)

    assert result[:2] == [None, None]
    assert result[2] == 2
    assert result[3] == 3
    assert result[4] == 4


def test_rsi_wilder_returns_100_for_monotonic_gain() -> None:
    result = indicators.rsi_wilder([float(i) for i in range(1, 30)], 14)

    assert result[13] is None
    assert result[14] == 100
    assert result[-1] == 100


def test_rsi_wilder_returns_50_for_flat_window() -> None:
    result = indicators.rsi_wilder([100.0] * 30, 14)

    assert result[13] is None
    assert result[14:] == [50.0] * 16


def test_macd_line_is_fast_ema_minus_slow_ema() -> None:
    close = [float(i) for i in range(1, 80)]
    fast = indicators.ema_series(close, 12)
    slow = indicators.ema_series(close, 26)
    line, signal, hist = indicators.macd(close)

    assert line[-1] == pytest.approx(fast[-1] - slow[-1])
    assert signal[-1] is not None
    assert hist[-1] == pytest.approx(line[-1] - signal[-1])


def test_trix_is_positive_for_a_steady_rising_series() -> None:
    close = [100.0 + i for i in range(100)]

    line, signal = indicators.trix(close)

    assert len(line) == len(close)
    assert len(signal) == len(close)
    assert line[-1] is not None and line[-1] > 0
    assert signal[-1] is not None and signal[-1] > 0


def test_bollinger_uses_population_standard_deviation() -> None:
    close = [float(i) for i in range(1, 21)]
    mid, upper, lower, percent_b = indicators.bollinger(close, 20, 2)

    expected_mid = sum(close) / 20
    expected_sd = math.sqrt(sum((x - expected_mid) ** 2 for x in close) / 20)

    assert mid == expected_mid
    assert upper == pytest.approx(expected_mid + 2 * expected_sd)
    assert lower == pytest.approx(expected_mid - 2 * expected_sd)
    assert percent_b == pytest.approx((close[-1] - lower) / (upper - lower))


def test_compute_regression_for_original_indicator_self_test_series() -> None:
    close = [round(100 + 18 * math.sin(i / 22) + i * 0.06, 2) for i in range(290)]

    assert indicators._round(indicators.compute(close)) == {
        "n_bars": 290,
        "warning": None,
        "close": 127.05,
        "ema20": 119.4774,
        "ema50": 112.8521,
        "ema200": 108.703,
        "ema20_slope": 4.0113,
        "ema50_slope": 2.8141,
        "ema200_slope": 0.8619,
        "rsi14": 98.7798,
        "rsi14_prev": 98.6881,
        "macd_line": 5.0762,
        "macd_signal": 4.7391,
        "macd_hist": 0.3371,
        "macd_hist_prev": 0.3722,
        "trix": 0.6418,
        "trix_prev": 0.6349,
        "trix_signal": 0.5929,
        "trix_signal_prev": 0.5807,
        "bars_since_below_ema20": 40,
        "bb_mid": 119.164,
        "bb_upper": 129.0103,
        "bb_lower": 109.3177,
        "percent_b": 0.9005,
    }
