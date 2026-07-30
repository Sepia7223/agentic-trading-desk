"""Glue between the confidence module and the paper session (pure + I/O).

Everything the session needs to compute ConfidenceInputs from data it
already has, plus the position sidecar (per-open-position confidence,
bucket and target R) and the realized-R math used when trades close.

Sizing note: multipliers are NORMALIZED across the batch of new entries so
the batch's TOTAL risk equals what the stress budget already granted -
confidence redistributes risk toward proven conviction, it does not
inflate the account's total risk. The total-risk dial remains the
governed stress budget, changed only by explicit human decision.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

MIN_MULT = 0.25
MAX_MULT = 3.0
DTC_SENTINEL = 999.0
DTC_BUCKET_FRACTION = 0.2
PUBLICATION_LAG_BDAYS = 9
DEFAULT_TARGET_R = 2.0


def signal_percentile(scores: dict[str, Decimal], symbol: str, direction: str) -> float:
    """Rank strength of this entry within today's cross-section, 0..1.

    Longs: fraction of names scoring BELOW this one. Shorts: fraction
    scoring ABOVE (a deeply negative momentum score is a strong short).
    """

    if symbol not in scores or len(scores) < 2:
        return 0.5
    mine = scores[symbol]
    others = [s for sym, s in scores.items() if sym != symbol]
    below = sum(1 for s in others if s < mine) / len(others)
    return below if direction == "BUY" else 1.0 - below


def _add_business_days(d: date, n: int) -> date:
    cur = d
    added = 0
    while added < n:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            added += 1
    return cur


def dtc_buckets(si_dir: Path, universe: set[str], today: date) -> tuple[set[str], set[str]]:
    """(low_dtc, high_dtc) quintiles over universe from the latest KNOWABLE
    consolidated short-interest partition; empty sets when no data."""

    best: date | None = None
    for path in sorted(Path(si_dir).glob("*.jsonl")):
        sd = date.fromisoformat(path.stem)
        if _add_business_days(sd, PUBLICATION_LAG_BDAYS) < today and (best is None or sd > best):
            best = sd
    if best is None:
        return set(), set()
    scored: list[tuple[float, str]] = []
    for line in (
        (Path(si_dir) / f"{best.isoformat()}.jsonl").read_text(encoding="utf-8").splitlines()
    ):
        if not line.strip():
            continue
        rec = json.loads(line)
        sym = rec.get("symbolCode")
        dtc = rec.get("daysToCoverQuantity")
        if isinstance(sym, str) and sym in universe and dtc is not None:
            value = float(dtc)
            if 0 < value < DTC_SENTINEL:
                scored.append((value, sym))
    if len(scored) < 25:
        return set(), set()
    scored.sort()
    k = max(int(len(scored) * DTC_BUCKET_FRACTION), 5)
    return {s for _, s in scored[:k]}, {s for _, s in scored[-k:]}


def sleeve_agreement(symbol: str, direction: str, low_dtc: set[str], high_dtc: set[str]) -> float:
    """1.0 when the validated DTC sleeve agrees with the trade direction,
    0.0 when it opposes, 0.5 when it has no reading."""

    if symbol in low_dtc:  # low days-to-cover = sleeve is bullish the name
        return 1.0 if direction == "BUY" else 0.0
    if symbol in high_dtc:
        return 0.0 if direction == "BUY" else 1.0
    return 0.5


def regime_vol_percentile(bars: dict[str, list], window: int = 20, history: int = 250) -> float:
    """Percentile of current cross-sectional volatility vs its own past.

    m_t = universe-mean |daily return|; compare mean(m[-window:]) against
    the distribution of trailing window-means. 0.5 when history is thin.
    """

    day_rets: dict[date, list[float]] = {}
    for series in bars.values():
        closes = [(row[0], float(row[4])) for row in series[-(history + window + 2) :]]
        for i in range(1, len(closes)):
            prev, cur = closes[i - 1][1], closes[i][1]
            if prev > 0:
                day_rets.setdefault(closes[i][0], []).append(abs(cur / prev - 1))
    days = sorted(day_rets)
    m = [sum(day_rets[d]) / len(day_rets[d]) for d in days]
    if len(m) < 2 * window:
        return 0.5
    current = sum(m[-window:]) / window
    trailing = [sum(m[i - window : i]) / window for i in range(window, len(m))]
    below = sum(1 for value in trailing if value < current)
    return below / len(trailing)


def crowding_penalty(cluster_weight: Decimal, gross: Decimal) -> float:
    """Largest correlated-cluster weight as a fraction of gross, 0..1."""

    if gross <= 0:
        return 1.0
    return min(1.0, float(cluster_weight / gross))


def normalize_multipliers(raw: dict[str, float]) -> dict[str, float]:
    """Scale so the batch total equals base total (sum of 1.0s), clamped.

    Confidence redistributes the granted risk; it never inflates it.
    """

    if not raw:
        return {}
    scale = len(raw) / sum(raw.values())
    return {sym: max(MIN_MULT, min(MAX_MULT, mult * scale)) for sym, mult in raw.items()}


def realized_r(
    entry_price: Decimal, exit_price: Decimal, is_long: bool, stop_fraction: Decimal
) -> float:
    """Realized R-multiple: pnl per share over the initial risk per share."""

    if entry_price <= 0 or stop_fraction <= 0:
        return 0.0
    move = (exit_price - entry_price) if is_long else (entry_price - exit_price)
    return float(move / (entry_price * stop_fraction))


def load_sidecar(path: Path) -> dict[str, dict]:
    p = Path(path)
    if not p.exists():
        return {}
    return dict(json.loads(p.read_text(encoding="utf-8")))


def save_sidecar(path: Path, sidecar: dict[str, dict]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sidecar, indent=1, sort_keys=True), encoding="utf-8")


def market_direction(
    bars: dict[str, list],
    *,
    ma_window: int = 100,
    bull_threshold: float = 0.55,
    bear_threshold: float = 0.45,
) -> str:
    """Breadth-based market-direction gate: "BULL", "BEAR", or "NEUTRAL".

    Fraction of symbols whose latest close sits above their own ``ma_window``
    simple moving average. Broad participation up favours longs (BULL); broad
    participation down favours shorts (BEAR); a split tape is NEUTRAL. Computed
    only from bars already fetched -- no extra network call. The directional
    counterpart to regime_vol_percentile (which measures volatility, not
    trend): the session uses it to avoid shorting a rising market and going
    long into a falling one.
    """

    above = 0
    counted = 0
    for series in bars.values():
        if len(series) < ma_window:
            continue
        closes = [float(row[4]) for row in series[-ma_window:]]
        sma = sum(closes) / len(closes)
        counted += 1
        if closes[-1] > sma:
            above += 1
    if counted == 0:
        return "NEUTRAL"
    breadth = above / counted
    if breadth >= bull_threshold:
        return "BULL"
    if breadth <= bear_threshold:
        return "BEAR"
    return "NEUTRAL"
