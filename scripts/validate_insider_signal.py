"""Insider-cluster signal: build + validation gauntlet (Phase 1, honest).

PRE-REGISTERED SIGNAL (all variants recorded as trials): a ticker becomes
ACTIVE when >= min_buyers DISTINCT officers/directors have made open-market
purchases totalling >= min_dollars within the trailing window_days (using
knowledge_time only), and stays active for hold_days. Daily portfolio: long
equal-weight active names; performance measured as EXCESS over the equal-
weight PIT-member universe (a crude but honest market-neutralisation).

Gauntlet at the single-signal stage:
  - every parameter variant -> TrialRegistry (the honest N)
  - Deflated Sharpe of the selected variant against that N
  - CPCV consistency: fraction of C(6,2) test paths with positive excess
  - orthogonality: correlation of the excess series vs the live momentum
    strategy's daily returns (low correlation = genuinely new information)
SPA-vs-momentum is the Phase 2 (composite) gate, per the blueprint.

Window: dev+validation 2022-01..2025-06 ONLY. Insider data covers through
2026q1 (SEC publishes quarterly with a lag; 2026q2 not yet available).

Usage:
    PYTHONPATH="src;scripts" python scripts/validate_insider_signal.py
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import date
from pathlib import Path

import pandas as pd

from trading_desk.trials import (
    TrialRegistry,
    combinatorial_purged_splits,
    deflated_sharpe_ratio,
)

DEV_START = date(2022, 1, 3)
VAL_END = date(2025, 6, 30)

# pre-registered variants (ALL are recorded; selection pays the DSR toll)
VARIANTS = [
    {"min_buyers": 2, "window_days": 21, "min_dollars": 50_000, "hold_days": 63},
    {"min_buyers": 2, "window_days": 42, "min_dollars": 100_000, "hold_days": 63},
    {"min_buyers": 3, "window_days": 42, "min_dollars": 100_000, "hold_days": 126},
]


def load_prices(bars_dir: Path) -> dict[str, dict[date, float]]:
    prices: dict[str, dict[date, float]] = {}
    for f in sorted(bars_dir.glob("*.csv")):
        if f.stem == "SPY":
            continue
        series: dict[date, float] = {}
        for line in f.read_text(encoding="utf-8").splitlines()[1:]:
            parts = line.split(",")
            try:
                series[date.fromisoformat(parts[0])] = float(parts[5])
            except (ValueError, IndexError):
                continue
        if len(series) > 200:
            prices[f.stem] = series
    return prices


def load_membership(pit: Path) -> dict[str, list[tuple[date, date]]]:
    uni = json.loads(
        (pit / "universe_2021-01-01_2026-06-30.json").read_text(encoding="utf-8")
    )
    return {
        t: [(date.fromisoformat(a), date.fromisoformat(b)) for a, b in ivs]
        for t, ivs in uni["intervals"].items()
    }


def member_on(intervals, ticker: str, d: date) -> bool:
    return any(a <= d <= b for a, b in intervals.get(ticker, ()))


def active_days(
    purchases: pd.DataFrame,
    trading_days: list[date],
    variant: dict,
) -> dict[str, set[date]]:
    """Ticker -> set of trading days on which the cluster signal is active."""

    window = pd.Timedelta(days=variant["window_days"])
    active: dict[str, set[date]] = {}
    for ticker, group in purchases.groupby("ticker"):
        rows = group.sort_values("knowledge_time")
        kts = rows["knowledge_time"]
        triggers: list[date] = []
        for _, row in rows.iterrows():
            end = row["knowledge_time"]
            in_win = rows[(kts <= end) & (kts >= end - window)]
            if (
                in_win["owner_cik"].nunique() >= variant["min_buyers"]
                and in_win["dollars"].sum() >= variant["min_dollars"]
            ):
                triggers.append(end.date())
        if not triggers:
            continue
        days: set[date] = set()
        ti = 0
        for i, d in enumerate(trading_days):
            while ti < len(triggers) and triggers[ti] <= d:
                # active for hold_days trading days from trigger
                for j in range(i, min(i + variant["hold_days"], len(trading_days))):
                    days.add(trading_days[j])
                ti += 1
        active[str(ticker)] = days
    return active


def daily_returns(
    prices: dict[str, dict[date, float]], trading_days: list[date]
) -> dict[str, dict[date, float]]:
    rets: dict[str, dict[date, float]] = {}
    for ticker, series in prices.items():
        r: dict[date, float] = {}
        prev: float | None = None
        prev_d: date | None = None
        for d in trading_days:
            px = series.get(d)
            if px is not None and prev is not None and prev > 0 and prev_d is not None:
                r[d] = px / prev - 1
            if px is not None:
                prev, prev_d = px, d
        rets[ticker] = r
    return rets


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pit-dir", default="data/pit")
    p.add_argument("--out", default="data/pit/insider_signal_result.json")
    args = p.parse_args(argv)
    pit = Path(args.pit_dir)

    purchases = pd.read_parquet(pit / "insider_purchases.parquet")
    purchases["knowledge_time"] = pd.to_datetime(purchases["knowledge_time"], utc=True)
    prices = load_prices(pit / "bars")
    membership = load_membership(pit)
    all_days = sorted({d for s in prices.values() for d in s})
    trading_days = [d for d in all_days if DEV_START <= d <= VAL_END]
    rets = daily_returns(prices, trading_days)

    registry = TrialRegistry(pit / "trial_registry.jsonl")
    results = []
    for variant in VARIANTS:
        active = active_days(purchases, trading_days, variant)
        excess: list[float] = []
        n_active_names: list[int] = []
        for d in trading_days[1:]:
            longs = [
                t
                for t, days in active.items()
                if d in days and member_on(membership, t, d) and d in rets.get(t, {})
            ]
            uni_rets = [
                rets[t][d]
                for t in rets
                if d in rets[t] and member_on(membership, t, d)
            ]
            if not uni_rets:
                continue
            uni_mean = sum(uni_rets) / len(uni_rets)
            if longs:
                sig_mean = sum(rets[t][d] for t in longs) / len(longs)
                excess.append(sig_mean - uni_mean)
                n_active_names.append(len(longs))
            else:
                excess.append(0.0)
                n_active_names.append(0)
        n = len(excess)
        mean = sum(excess) / n
        sd = statistics.pstdev(excess)
        sharpe = mean / sd if sd > 0 else 0.0
        registry.record("insider-cluster", variant, sharpe, n, "2022-01..2025-06")
        results.append(
            {
                "variant": variant,
                "sharpe_daily": round(sharpe, 4),
                "sharpe_annualized": round(sharpe * (252**0.5), 3),
                "mean_daily_excess_bps": round(mean * 1e4, 3),
                "days_with_active_names": sum(1 for k in n_active_names if k > 0),
                "avg_active_names": round(
                    sum(n_active_names) / max(len(n_active_names), 1), 1
                ),
                "n_obs": n,
                "excess": excess,
            }
        )

    best = max(results, key=lambda r: r["sharpe_daily"])
    n_trials, sharpe_var = registry.dsr_inputs("insider-cluster")
    dsr = deflated_sharpe_ratio(
        best["sharpe_daily"], n_trials, sharpe_var, best["n_obs"]
    )
    # CPCV consistency on the selected variant's excess series
    splits = combinatorial_purged_splits(
        best["n_obs"], n_groups=6, test_groups=2, label_span=5, embargo=5
    )
    path_sharpes = []
    for _, test_idx in splits:
        seg = [best["excess"][i] for i in test_idx]
        sdv = statistics.pstdev(seg)
        path_sharpes.append((sum(seg) / len(seg)) / sdv if sdv > 0 else 0.0)
    consistency = sum(1 for s in path_sharpes if s > 0) / len(path_sharpes)

    # orthogonality vs the live momentum strategy
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
    paired = [
        (best["excess"][i], mom_by_day[d])
        for i, d in enumerate(trading_days[1:])
        if d in mom_by_day and i < len(best["excess"])
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
        "signal": "insider-cluster",
        "window": "2022-01..2025-06 (dev+validation only)",
        "variants": [
            {k: v for k, v in r.items() if k != "excess"} for r in results
        ],
        "selected": best["variant"],
        "gauntlet": {
            "registry_trials": n_trials,
            "deflated_sharpe": round(dsr, 4),
            "dsr_pass_0.95": dsr >= 0.95,
            "cpcv_paths_positive": round(consistency, 3),
            "cpcv_pass_0.60": consistency >= 0.60,
            "corr_vs_momentum": round(corr, 4),
            "orthogonal": abs(corr) < 0.3,
        },
        "data_note": "insider data through 2026q1 (SEC lag); final-test partially covered",
    }
    Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
