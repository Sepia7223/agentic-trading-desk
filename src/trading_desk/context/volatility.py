"""Causal ATR, realized-volatility, compression, and expansion classification."""

from __future__ import annotations

from decimal import Decimal, localcontext

from trading_desk.context.config import MarketContextConfiguration
from trading_desk.context.models import CompressionState, VolatilityState


def classify_volatility(
    highs: tuple[float, ...],
    lows: tuple[float, ...],
    closes: tuple[float, ...],
    config: MarketContextConfiguration,
) -> tuple[VolatilityState, Decimal, Decimal, Decimal, CompressionState]:
    if (
        len(closes) < config.minimum_history
        or len(highs) != len(closes)
        or len(lows) != len(closes)
    ):
        return (
            VolatilityState.UNKNOWN,
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            CompressionState.UNKNOWN,
        )
    decimal_closes = tuple(Decimal(str(value)) for value in closes)
    true_ranges = _true_ranges(highs, lows, closes)
    window = config.volatility_window
    atr_series = tuple(
        sum(true_ranges[index - window + 1 : index + 1], Decimal("0")) / Decimal(window)
        for index in range(window - 1, len(true_ranges))
    )
    returns = tuple(
        (right - left) / left
        for left, right in zip(decimal_closes, decimal_closes[1:], strict=False)
    )
    realized_series = tuple(
        _standard_deviation(returns[index - window + 1 : index + 1])
        for index in range(window - 1, len(returns))
    )
    atr = atr_series[-1]
    realized = realized_series[-1] if realized_series else Decimal("0")
    percentile = _percentile_rank(realized_series, realized)
    bandwidth = _bollinger_bandwidth(decimal_closes[-window:])
    compression = bandwidth <= Decimal("0.01") or percentile <= config.compression_percentile
    if percentile >= config.extreme_volatility_percentile:
        state = VolatilityState.EXTREME
    elif compression:
        state = VolatilityState.COMPRESSION
    elif percentile >= Decimal("85") and true_ranges[-1] > atr * Decimal("1.5"):
        state = VolatilityState.EXPANSION
    elif percentile >= config.high_volatility_percentile:
        state = VolatilityState.HIGH
    elif percentile <= Decimal("25"):
        state = VolatilityState.LOW
    else:
        state = VolatilityState.NORMAL
    return (
        state,
        realized,
        atr,
        percentile,
        CompressionState.COMPRESSED if compression else CompressionState.NORMAL,
    )


def percentile_rank(values: tuple[float, ...], current: float) -> Decimal:
    decimals = tuple(Decimal(str(value)) for value in values)
    return _percentile_rank(decimals, Decimal(str(current)))


def _true_ranges(
    highs: tuple[float, ...], lows: tuple[float, ...], closes: tuple[float, ...]
) -> tuple[Decimal, ...]:
    result: list[Decimal] = []
    for index, (high_value, low_value) in enumerate(zip(highs, lows, strict=True)):
        high, low = Decimal(str(high_value)), Decimal(str(low_value))
        previous = Decimal(str(closes[index - 1])) if index else Decimal(str(closes[0]))
        result.append(max(high - low, abs(high - previous), abs(low - previous)))
    return tuple(result)


def _standard_deviation(values: tuple[Decimal, ...]) -> Decimal:
    if len(values) < 2:
        return Decimal("0")
    mean = sum(values, Decimal("0")) / Decimal(len(values))
    variance = sum(((value - mean) ** 2 for value in values), Decimal("0")) / Decimal(len(values))
    with localcontext() as context:
        context.prec = 28
        return variance.sqrt()


def _percentile_rank(values: tuple[Decimal, ...], current: Decimal) -> Decimal:
    if not values:
        return Decimal("0")
    below = sum(value <= current for value in values)
    return Decimal(100 * below) / Decimal(len(values))


def _bollinger_bandwidth(values: tuple[Decimal, ...]) -> Decimal:
    mean = sum(values, Decimal("0")) / Decimal(len(values))
    if mean <= 0:
        return Decimal("0")
    return Decimal("4") * _standard_deviation(values) / mean
