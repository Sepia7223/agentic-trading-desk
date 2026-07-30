"""Versioned, completed-bar-only Decimal statistics shared by strategies."""

from __future__ import annotations

from decimal import Decimal
from math import isfinite
from statistics import fmean

INDICATOR_DEFINITION_VERSION = "portfolio-indicators-v1"


def decimal_prices(values: tuple[float, ...]) -> tuple[Decimal, ...]:
    if not values or any(not isfinite(item) or item <= 0 for item in values):
        raise ValueError("price series must be finite, positive, and non-empty")
    return tuple(Decimal(str(item)) for item in values)


def mean(values: tuple[Decimal, ...]) -> Decimal:
    if not values:
        raise ValueError("mean requires observations")
    return sum(values, Decimal("0")) / Decimal(len(values))


def average_true_range(
    highs: tuple[Decimal, ...], lows: tuple[Decimal, ...], closes: tuple[Decimal, ...], window: int
) -> Decimal:
    if window < 2 or not (len(highs) == len(lows) == len(closes)) or len(closes) <= window:
        raise ValueError("ATR history is insufficient or inconsistent")
    true_ranges = tuple(
        max(
            highs[index] - lows[index],
            abs(highs[index] - closes[index - 1]),
            abs(lows[index] - closes[index - 1]),
        )
        for index in range(len(closes) - window, len(closes))
    )
    return mean(true_ranges)


def prior_range(
    highs: tuple[Decimal, ...], lows: tuple[Decimal, ...], window: int
) -> tuple[Decimal, Decimal]:
    if window < 2 or len(highs) != len(lows) or len(highs) <= window:
        raise ValueError("range history is insufficient or inconsistent")
    # Current evaluation bar is deliberately excluded.
    return min(lows[-window - 1 : -1]), max(highs[-window - 1 : -1])


def linear_slope(values: tuple[Decimal, ...], window: int) -> Decimal:
    if window < 2 or len(values) < window:
        raise ValueError("slope history is insufficient")
    sample = values[-window:]
    x_mean = Decimal(window - 1) / Decimal("2")
    y_mean = mean(sample)
    numerator = sum(
        ((Decimal(index) - x_mean) * (value - y_mean) for index, value in enumerate(sample)),
        Decimal("0"),
    )
    denominator = sum(((Decimal(index) - x_mean) ** 2 for index in range(window)), Decimal("0"))
    return numerator / denominator


def population_std(values: tuple[Decimal, ...]) -> Decimal:
    if len(values) < 2:
        raise ValueError("standard deviation requires two observations")
    value = Decimal(str(fmean(float((item - mean(values)) ** 2) for item in values)))
    return value.sqrt()
