"""Tests for the breadth-based bull/bear market-direction gate."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from trading_desk.confidence.integration import market_direction

Series = list[tuple[date, Decimal, Decimal, Decimal, Decimal, Decimal]]


def _series(step: float, n: int = 120, start: float = 100.0) -> Series:
    base = date(2026, 1, 1)
    out: Series = []
    px = start
    for i in range(n):
        px += step
        close = Decimal(str(round(px, 4)))
        out.append((base + timedelta(days=i), close, close, close, close, Decimal("0")))
    return out


def test_bull_when_broad_uptrend() -> None:
    bars = {f"S{i}": _series(0.5) for i in range(10)}
    assert market_direction(bars) == "BULL"


def test_bear_when_broad_downtrend() -> None:
    bars = {f"S{i}": _series(-0.5) for i in range(10)}
    assert market_direction(bars) == "BEAR"


def test_neutral_when_split() -> None:
    bars: dict[str, Series] = {}
    for i in range(10):
        bars[f"U{i}"] = _series(0.5)
    for i in range(10):
        bars[f"D{i}"] = _series(-0.5)
    assert market_direction(bars) == "NEUTRAL"


def test_neutral_when_history_thin() -> None:
    assert market_direction({"X": _series(0.5, n=10)}) == "NEUTRAL"
