"""Offline tests for the FX forward paper-trading loop."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from shadow_fx_forward import MidRow, to_bars  # noqa: E402


def test_to_bars_synthesizes_valid_bidask() -> None:
    rows: list[MidRow] = [
        (datetime(2024, 1, 1, tzinfo=UTC), 1.1000, 1.1050, 1.0950, 1.1010),
        (datetime(2024, 1, 2, tzinfo=UTC), 1.1010, 1.1080, 1.1000, 1.1075),
    ]
    bars = to_bars(rows)
    assert len(bars) == 2
    first = bars[0]
    assert first.open_bid < first.open_ask
    assert first.close_bid < first.close_ask
    assert first.high_ask > first.low_bid
    assert bars[1].timestamp > bars[0].timestamp


def test_to_bars_drops_non_increasing_timestamps() -> None:
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    rows: list[MidRow] = [
        (ts, 1.10, 1.20, 1.00, 1.15),
        (ts, 1.15, 1.25, 1.05, 1.20),
    ]
    assert len(to_bars(rows)) == 1
