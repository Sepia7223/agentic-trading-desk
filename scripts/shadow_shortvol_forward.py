"""Nightly forward shadow log for the short-volume sleeve (mini PC).

The Phase-2 verdict (INFORMATION-EDGE-RESULTS.md) moved the momentum+
short-vol composite to SHADOW: forward out-of-sample evidence, not more
backtesting, resolves whether it beats momentum-alone. This script is that
evidence stream. It was missing from the nightly deployment — the shortvol
history lives only on the laptop — so this logger rebuilds the sleeve
FORWARD from FINRA's public daily files (no key needed), one honest row
per trading day, append-only.

Each run backfills up to --max-backfill missing trading days:
  1. downloads the FINRA CNMS daily short-volume files it lacks (cached),
  2. fetches recent daily bars for the paper universe (same Yahoo path the
     paper session uses),
  3. recomputes the validated sleeve construction (5-day formation, 20%
     buckets, long low short-ratio / short high, turnover-costed at
     4bps/side) for each missing day,
  4. appends {date, gross, net, turnover, buckets} to
     data/shadow/shortvol_forward.jsonl. Bucket membership is stored in
     the row so the NEXT run prices turnover across runs honestly.

The momentum reference series for the eventual forward SPA test is the
paper journal's own session records — not duplicated here.

Usage (cron, after the 18:30 paper session):
    15 19 * * 1-5 .../scripts/run_shadow_shortvol.sh
    PYTHONPATH="src:scripts" python scripts/shadow_shortvol_forward.py
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

FINRA_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{stamp}.txt"
_UA = {"User-Agent": "agentic-trading-desk research ops@itsolutions.cw"}
FORMATION_DAYS = 5
BUCKET_FRACTION = 0.2
MIN_BUCKET = 5
MIN_CANDIDATES = 50  # matches the validated full-universe construction
COST_PER_SIDE = 4e-4


def fetch_finra_day(cache_dir: Path, d: date, timeout: float = 30.0) -> Path | None:
    """Download (or reuse cached) FINRA daily short-volume file for d."""

    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{d.isoformat()}.txt"
    if path.exists():
        return path
    req = urllib.request.Request(FINRA_URL.format(stamp=d.strftime("%Y%m%d")), headers=_UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            path.write_bytes(resp.read())
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return None  # not published (holiday) or not yet posted; retry next run
    return path


def parse_ratios(path: Path, universe: set[str]) -> dict[str, float]:
    ratios: dict[str, float] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[1:]:
        parts = line.split("|")
        if len(parts) < 5 or parts[1] not in universe:
            continue
        try:
            short_v, total_v = float(parts[2]), float(parts[4])
        except ValueError:
            continue
        if total_v > 0:
            ratios[parts[1]] = short_v / total_v
    return ratios


def sleeve_day(
    ratio_window: list[dict[str, float]],
    returns_today: dict[str, float],
    prev_low: set[str],
    prev_high: set[str],
) -> dict | None:
    """One forward day of the validated sleeve; None if too few candidates."""

    acc: dict[str, list[float]] = {}
    for day_ratios in ratio_window:
        for sym, r in day_ratios.items():
            acc.setdefault(sym, []).append(r)
    candidates = sorted(
        (sum(v) / len(v), sym)
        for sym, v in acc.items()
        if len(v) == len(ratio_window) and sym in returns_today
    )
    if len(candidates) < MIN_CANDIDATES:
        return None
    k = max(int(len(candidates) * BUCKET_FRACTION), MIN_BUCKET)
    low = {sym for _, sym in candidates[:k]}
    high = {sym for _, sym in candidates[-k:]}
    low_r = sum(returns_today[s] for s in low) / len(low)
    high_r = sum(returns_today[s] for s in high) / len(high)
    gross = (low_r - high_r) / 2
    if prev_low:
        churn = (len(low ^ prev_low) / (2 * len(low)) + len(high ^ prev_high) / (2 * len(high))) / 2
    else:
        churn = 1.0
    net = gross - churn * 2 * COST_PER_SIDE
    return {
        "gross": round(gross, 8),
        "net": round(net, 8),
        "turnover": round(churn, 6),
        "n_candidates": len(candidates),
        "low": sorted(low),
        "high": sorted(high),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pit-dir", default="data/pit")
    p.add_argument("--shadow-dir", default="data/shadow")
    p.add_argument("--max-backfill", type=int, default=7)
    p.add_argument("--sleep", type=float, default=0.35)
    args = p.parse_args(argv)

    from paper_trade import fetch_recent_bars, load_universe  # noqa: PLC0415

    shadow = Path(args.shadow_dir)
    shadow.mkdir(parents=True, exist_ok=True)
    log_path = shadow / "shortvol_forward.jsonl"
    rows = (
        [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line]
        if log_path.exists()
        else []
    )
    logged = {r["date"] for r in rows}
    prev_low = set(rows[-1]["low"]) if rows else set()
    prev_high = set(rows[-1]["high"]) if rows else set()

    symbols, _sectors = load_universe(Path(args.pit_dir))
    print(f"universe: {len(symbols)}; fetching bars…")
    bars = fetch_recent_bars(symbols, args.sleep)

    # trading days = dates where a decent share of the universe has bars
    day_counts: dict[date, int] = {}
    for series in bars.values():
        for row in series[-40:]:
            day_counts[row[0]] = day_counts.get(row[0], 0) + 1
    trading_days = sorted(d for d, c in day_counts.items() if c >= len(bars) // 2)
    todo = [d for d in trading_days[-args.max_backfill :] if d.isoformat() not in logged]
    if not todo:
        print("nothing to backfill")
        return 0

    with log_path.open("a", encoding="utf-8") as fh:
        for d in todo:
            idx = trading_days.index(d)
            if idx < FORMATION_DAYS:
                continue
            window_days = trading_days[idx - FORMATION_DAYS : idx]
            ratio_window = []
            for wd in window_days:
                path = fetch_finra_day(shadow / "shortvol", wd)
                if path is None:
                    break
                ratio_window.append(parse_ratios(path, set(symbols)))
            if len(ratio_window) < FORMATION_DAYS:
                print(f"{d}: FINRA files incomplete; will retry next run")
                continue
            returns_today: dict[str, float] = {}
            for sym, series in bars.items():
                closes = {row[0]: float(row[4]) for row in series}
                prev_days = [t for t in trading_days[: idx + 1] if t in closes]
                if len(prev_days) >= 2 and prev_days[-1] == d:
                    c0, c1 = closes[prev_days[-2]], closes[d]
                    if c0 > 0:
                        returns_today[sym] = c1 / c0 - 1
            result = sleeve_day(ratio_window, returns_today, prev_low, prev_high)
            if result is None:
                print(f"{d}: <{MIN_CANDIDATES} candidates; skipped")
                continue
            entry = {"date": d.isoformat(), **result}
            fh.write(json.dumps(entry) + "\n")
            fh.flush()
            prev_low, prev_high = set(result["low"]), set(result["high"])
            print(
                f"{d}: net {result['net']:+.5f} "
                f"(turnover {result['turnover']:.2f}, n={result['n_candidates']})"
            )
            time.sleep(0.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
