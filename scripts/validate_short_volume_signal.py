"""Short-volume-ratio signal: build + validation gauntlet (Phase 1, honest).

PRE-REGISTERED SIGNAL: daily short_ratio = ShortVolume / TotalVolume from the
free FINRA CNMS files, averaged over a trailing formation window ending the
prior session (files publish the same evening -> knowable next day). Cross-
sectional portfolio among PIT members: LONG the lowest-ratio bucket, SHORT the
highest (Boehmer-Jones-Zhang direction), L/S measured as (low - high)/2 daily.

HONEST expectation stated up front: WEAK. Public daily short volume is
dominated by market-maker liquidity provision; the strong published results
used proprietary order data. The gauntlet decides; failure gets documented.

Gauntlet: every variant -> TrialRegistry; DSR on the selected variant; CPCV
consistency; correlation vs the live momentum strategy.

Usage:
    PYTHONPATH="src;scripts" python scripts/validate_short_volume_signal.py
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import date
from pathlib import Path

from trading_desk.trials import (
    TrialRegistry,
    combinatorial_purged_splits,
    deflated_sharpe_ratio,
)
from validate_insider_signal import (  # type: ignore[import-untyped]
    DEV_START,
    VAL_END,
    daily_returns,
    load_membership,
    load_prices,
    member_on,
)

VARIANTS = [
    {"formation_days": 5, "bucket_fraction": 0.1},
    {"formation_days": 10, "bucket_fraction": 0.1},
    {"formation_days": 5, "bucket_fraction": 0.2},
]


def load_short_ratios(
    shortvol_dir: Path, universe: set[str]
) -> dict[date, dict[str, float]]:
    """day -> {symbol: short_ratio} for universe symbols."""

    out: dict[date, dict[str, float]] = {}
    for path in sorted(shortvol_dir.glob("*.txt")):
        day = date.fromisoformat(path.stem)
        ratios: dict[str, float] = {}
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[1:]:
            parts = line.split("|")
            if len(parts) < 5:
                continue
            sym = parts[1]
            if sym not in universe:
                continue
            try:
                short_v = float(parts[2])
                total_v = float(parts[4])
            except ValueError:
                continue
            if total_v > 0:
                ratios[sym] = short_v / total_v
        if ratios:
            out[day] = ratios
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pit-dir", default="data/pit")
    p.add_argument("--out", default="data/pit/short_volume_signal_result.json")
    args = p.parse_args(argv)
    pit = Path(args.pit_dir)

    prices = load_prices(pit / "bars")
    membership = load_membership(pit)
    universe = set(membership)
    ratios_by_day = load_short_ratios(pit / "shortvol", universe)
    all_days = sorted({d for s in prices.values() for d in s})
    trading_days = [d for d in all_days if DEV_START <= d <= VAL_END]
    rets = daily_returns(prices, trading_days)
    ratio_days = sorted(ratios_by_day)

    registry = TrialRegistry(pit / "trial_registry.jsonl")
    results = []
    for variant in VARIANTS:
        form = variant["formation_days"]
        frac = variant["bucket_fraction"]
        ls: list[float] = []
        for i, d in enumerate(trading_days):
            if i < 1:
                continue
            # formation: ratio days strictly BEFORE d, most recent `form` of them
            window = [rd for rd in ratio_days if rd < d][-form:]
            if len(window) < form:
                continue
            avg: dict[str, list[float]] = {}
            for rd in window:
                for sym, r in ratios_by_day[rd].items():
                    avg.setdefault(sym, []).append(r)
            candidates = [
                (sum(v) / len(v), sym)
                for sym, v in avg.items()
                if len(v) == form
                and member_on(membership, sym, d)
                and d in rets.get(sym, {})
            ]
            if len(candidates) < 50:
                continue
            candidates.sort()
            k = max(int(len(candidates) * frac), 5)
            low = [sym for _, sym in candidates[:k]]  # lightly shorted -> long
            high = [sym for _, sym in candidates[-k:]]  # heavily shorted -> short
            low_r = sum(rets[s][d] for s in low) / len(low)
            high_r = sum(rets[s][d] for s in high) / len(high)
            ls.append((low_r - high_r) / 2)
        n = len(ls)
        if n < 100:
            results.append({"variant": variant, "error": "insufficient data", "n_obs": n})
            continue
        mean = sum(ls) / n
        sd = statistics.pstdev(ls)
        sharpe = mean / sd if sd > 0 else 0.0
        registry.record("short-volume", variant, sharpe, n, "2022-01..2025-06")
        results.append(
            {
                "variant": variant,
                "sharpe_daily": round(sharpe, 4),
                "sharpe_annualized": round(sharpe * (252**0.5), 3),
                "mean_daily_ls_bps": round(mean * 1e4, 3),
                "n_obs": n,
                "ls": ls,
            }
        )

    scored = [r for r in results if "sharpe_daily" in r]
    if not scored:
        print(json.dumps({"signal": "short-volume", "error": "no scorable variants"}))
        return 1
    best = max(scored, key=lambda r: r["sharpe_daily"])
    n_trials, sharpe_var = registry.dsr_inputs("short-volume")
    dsr = deflated_sharpe_ratio(
        best["sharpe_daily"], n_trials, sharpe_var, best["n_obs"]
    )
    splits = combinatorial_purged_splits(
        best["n_obs"], n_groups=6, test_groups=2, label_span=5, embargo=5
    )
    path_sharpes = []
    for _, test_idx in splits:
        seg = [best["ls"][i] for i in test_idx]
        sdv = statistics.pstdev(seg)
        path_sharpes.append((sum(seg) / len(seg)) / sdv if sdv > 0 else 0.0)
    consistency = sum(1 for s in path_sharpes if s > 0) / len(path_sharpes)

    import equity_backtest_v2 as ebt  # noqa: PLC0415 - scripts-path import

    intervals, sectors, _cov = ebt.load_universe(pit, "2021-01-01", "2026-06-30")
    eprices = ebt.load_prices(pit / "bars")
    eprices.pop("SPY", None)
    mom = ebt.run(
        eprices, intervals, sectors,
        start=DEV_START, end=VAL_END,
        lookback=252, skip=21, basket=30, hold_buffer=60, buffered=True,
        sector_neutral=True, rebalance_every=5, gross=1.0,
        half_spread_bps=2.5, slippage_bps=1.0, commission_bps=0.5,
        borrow_fee_annual=0.005, min_short_price=5.0, delay=0,
        start_equity=1000.0,
    )
    mom_by_day = {d: r for d, r in mom["daily_rets"]}
    # align: reconstruct the day for each ls observation
    ls_days = []
    seen = 0
    for i, d in enumerate(trading_days):
        if i < 1:
            continue
        window = [rd for rd in sorted(ratios_by_day) if rd < d]
        if len(window) >= best["variant"]["formation_days"]:
            if seen < len(best["ls"]):
                ls_days.append(d)
                seen += 1
    paired = [
        (best["ls"][i], mom_by_day[d])
        for i, d in enumerate(ls_days)
        if d in mom_by_day
    ]
    corr = 0.0
    if len(paired) > 50:
        xs, ys = [a for a, _ in paired], [b for _, b in paired]
        mx, my = statistics.mean(xs), statistics.mean(ys)
        cov = sum((a - mx) * (b - my) for a, b in paired)
        vx = sum((a - mx) ** 2 for a in xs)
        vy = sum((b - my) ** 2 for b in ys)
        corr = cov / (vx * vy) ** 0.5 if vx > 0 and vy > 0 else 0.0

    report = {
        "signal": "short-volume",
        "window": "2022-01..2025-06 (dev+validation only)",
        "variants": [{k: v for k, v in r.items() if k != "ls"} for r in results],
        "selected": best["variant"],
        "gauntlet": {
            "registry_trials": n_trials,
            "deflated_sharpe": round(dsr, 4),
            "dsr_pass_0.95": dsr >= 0.95,
            "cpcv_paths_positive": round(consistency, 3),
            "cpcv_pass_0.60": consistency >= 0.60,
            "corr_vs_momentum": round(corr, 4),
        },
        "honest_note": (
            "public daily short volume graded WEAK by the research up front; "
            "the strong variant (bi-monthly short interest) is key-gated"
        ),
    }
    Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
