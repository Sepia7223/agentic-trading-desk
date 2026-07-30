"""Forward shadow sleeve: pure-function pins (offline, no network)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from shadow_shortvol_forward import (  # noqa: E402
    MIN_CANDIDATES,
    parse_ratios,
    sleeve_day,
)


def _uniform_window(symbols: list[str]) -> list[dict[str, float]]:
    # ratio ladder: sym_i gets ratio i/len — deterministic buckets
    n = len(symbols)
    day = {s: (i + 1) / (n + 1) for i, s in enumerate(symbols)}
    return [day] * 5


def test_sleeve_long_low_short_high_direction() -> None:
    symbols = [f"S{i:03d}" for i in range(60)]
    window = _uniform_window(symbols)
    # low-ratio names (start of list) rise, high-ratio names fall
    returns = {s: (0.01 if i < 30 else -0.01) for i, s in enumerate(symbols)}
    out = sleeve_day(window, returns, set(), set())
    assert out is not None
    assert out["gross"] == pytest.approx(0.01)  # (+1% - -1%)/2
    # first build: full turnover, cost = 1.0 * 2 * 4bps
    assert out["net"] == pytest.approx(0.01 - 8e-4)
    assert out["turnover"] == 1.0
    assert len(out["low"]) == 12 and len(out["high"]) == 12  # 20% of 60


def test_sleeve_stable_buckets_cost_nothing() -> None:
    symbols = [f"S{i:03d}" for i in range(60)]
    window = _uniform_window(symbols)
    returns = dict.fromkeys(symbols, 0.0)
    first = sleeve_day(window, returns, set(), set())
    assert first is not None
    second = sleeve_day(window, returns, set(first["low"]), set(first["high"]))
    assert second is not None
    assert second["turnover"] == 0.0
    assert second["net"] == second["gross"] == 0.0


def test_sleeve_refuses_thin_cross_section() -> None:
    symbols = [f"S{i:03d}" for i in range(MIN_CANDIDATES - 1)]
    window = _uniform_window(symbols)
    returns = dict.fromkeys(symbols, 0.01)
    assert sleeve_day(window, returns, set(), set()) is None


def test_parse_ratios_pipe_format(tmp_path: Path) -> None:
    f = tmp_path / "d.txt"
    f.write_text(
        "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n"
        "20260722|AAPL|400|0|1000|Q\n"
        "20260722|ZZZC|100|0|0|Q\n"  # zero total volume -> skipped
        "20260722|SKIP|1|0|10|Q\n",
        encoding="utf-8",
    )
    ratios = parse_ratios(f, {"AAPL", "ZZZC"})
    assert ratios == {"AAPL": 0.4}
