"""Confidence integration helpers: pure-function pins."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest

from trading_desk.confidence.integration import (
    crowding_penalty,
    dtc_buckets,
    load_sidecar,
    normalize_multipliers,
    realized_r,
    regime_vol_percentile,
    save_sidecar,
    signal_percentile,
    sleeve_agreement,
)


def test_signal_percentile_direction_aware() -> None:
    scores = {f"S{i}": D(i) for i in range(10)}
    assert signal_percentile(scores, "S9", "BUY") == 1.0  # strongest long
    assert signal_percentile(scores, "S9", "SELL_SHORT") == 0.0  # worst short
    assert signal_percentile(scores, "S0", "SELL_SHORT") == 1.0  # strongest short
    assert signal_percentile(scores, "MISSING", "BUY") == 0.5


def test_dtc_buckets_from_knowable_partition(tmp_path: Path) -> None:
    today = date(2026, 7, 25)
    knowable = today - timedelta(days=30)
    too_fresh = today - timedelta(days=2)
    universe = {f"S{i:03d}" for i in range(40)}
    for stamp, base in ((knowable, 1.0), (too_fresh, 100.0)):
        rows = [{"symbolCode": f"S{i:03d}", "daysToCoverQuantity": base + i} for i in range(40)]
        (tmp_path / f"{stamp.isoformat()}.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows), encoding="utf-8"
        )
    low, high = dtc_buckets(tmp_path, universe, today)
    # the too-fresh partition (base 100) must NOT be used: PIT lag
    assert "S000" in low and "S039" in high
    assert len(low) == 8 and len(high) == 8  # 20% of 40
    assert low.isdisjoint(high)


def test_dtc_buckets_empty_without_data(tmp_path: Path) -> None:
    assert dtc_buckets(tmp_path, {"AAPL"}, date(2026, 7, 25)) == (set(), set())


def test_sleeve_agreement_matrix() -> None:
    low, high = {"LOW"}, {"HIGH"}
    assert sleeve_agreement("LOW", "BUY", low, high) == 1.0
    assert sleeve_agreement("LOW", "SELL_SHORT", low, high) == 0.0
    assert sleeve_agreement("HIGH", "BUY", low, high) == 0.0
    assert sleeve_agreement("HIGH", "SELL_SHORT", low, high) == 1.0
    assert sleeve_agreement("NONE", "BUY", low, high) == 0.5


def _bars(daily_moves: list[float]) -> dict[str, list]:
    series = []
    px = 100.0
    start = date(2025, 1, 1)
    for i, move in enumerate(daily_moves):
        px *= 1 + move
        day = start + timedelta(days=i)
        series.append((day, D("1"), D("1"), D("1"), D(str(round(px, 4))), D("1")))
    return {"AAA": series, "BBB": series}


def test_regime_vol_percentile_flags_hot_regime() -> None:
    calm = [0.001, -0.001] * 120
    hot = [0.03, -0.03] * 15
    assert regime_vol_percentile(_bars(calm + hot)) > 0.9
    assert regime_vol_percentile(_bars(calm[:30])) == 0.5  # thin history


def test_crowding_penalty_scales_and_saturates() -> None:
    assert crowding_penalty(D("0.10"), D("0.40")) == pytest.approx(0.25)
    assert crowding_penalty(D("0.50"), D("0.40")) == 1.0
    assert crowding_penalty(D("0.10"), D("0")) == 1.0


def test_normalize_multipliers_preserves_batch_total() -> None:
    raw = {"A": 2.0, "B": 1.0, "C": 1.0}
    out = normalize_multipliers(raw)
    assert sum(out.values()) == pytest.approx(3.0)  # == number of entries
    assert out["A"] > out["B"] == out["C"]
    assert normalize_multipliers({}) == {}


def test_realized_r_math() -> None:
    # long: entry 100, exit 106, stop 15% -> +6 / 15 = 0.4R
    assert realized_r(D("100"), D("106"), True, D("0.15")) == pytest.approx(0.4)
    # short: entry 100, exit 106 -> -0.4R
    assert realized_r(D("100"), D("106"), False, D("0.15")) == pytest.approx(-0.4)
    assert realized_r(D("0"), D("1"), True, D("0.15")) == 0.0


def test_sidecar_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "sidecar.json"
    data = {"AAPL": {"confidence": 0.72, "bucket": "high", "target_r": 2.58}}
    save_sidecar(path, data)
    assert load_sidecar(path) == data
    assert load_sidecar(tmp_path / "missing.json") == {}
