"""Phase 2: costed composite vs momentum-alone under the SPA gate.

Builds three PRE-REGISTERED sleeve-weight composites from the dev+validation
daily return streams — momentum (already net of costs from the engine),
short-volume L/S (costed HERE by tracking actual bucket turnover), insider
cluster excess (costed by entry/exit turnover) — and asks the only question
that matters: does any composite beat momentum-alone after accounting for the
search? (Hansen SPA, all composites as candidates.) DSR on the winner as a
second lens. All trials recorded.

Cost model per traded dollar (one side): half-spread 2.5bps + slippage 1bps +
commission 0.5bps = 4bps, matching the engine's assumptions.

Usage:
    PYTHONPATH="src;scripts" python scripts/validate_composite.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from trading_desk.trials import TrialRegistry, deflated_sharpe_ratio, spa_test
from validate_insider_signal import (  # type: ignore[import-untyped]
    DEV_START,
    VAL_END,
    active_days,
    daily_returns,
    load_membership,
    load_prices,
    member_on,
)
from validate_short_volume_signal import (  # type: ignore[import-untyped]
    load_short_ratios,
)

COST_PER_SIDE = 4e-4  # 4 bps: half-spread 2.5 + slippage 1 + commission 0.5

COMPOSITES = [
    {"momentum": 0.5, "short_volume": 0.5, "insider": 0.0},
    {"momentum": 0.6, "short_volume": 0.3, "insider": 0.1},
    {"momentum": 0.7, "short_volume": 0.3, "insider": 0.0},
]

SHORTVOL_VARIANT = {"formation_days": 5, "bucket_fraction": 0.2}  # Phase 1 winner
INSIDER_VARIANT = {  # Phase 1 selection (weak standalone, negative correlation)
    "min_buyers": 2,
    "window_days": 42,
    "min_dollars": 100_000,
    "hold_days": 63,
}


def shortvol_costed_series(pit: Path, membership, prices, trading_days, rets):
    """Daily L/S return NET of turnover costs; returns {date: net_return}."""

    ratios_by_day = load_short_ratios(pit / "shortvol", set(membership))
    ratio_days = sorted(ratios_by_day)
    form = SHORTVOL_VARIANT["formation_days"]
    frac = SHORTVOL_VARIANT["bucket_fraction"]
    out: dict = {}
    prev_low: set[str] = set()
    prev_high: set[str] = set()
    for i, d in enumerate(trading_days):
        if i < 1:
            continue
        window = [rd for rd in ratio_days if rd < d][-form:]
        if len(window) < form:
            continue
        acc: dict[str, list[float]] = {}
        for rd in window:
            for sym, r in ratios_by_day[rd].items():
                acc.setdefault(sym, []).append(r)
        candidates = [
            (sum(v) / len(v), sym)
            for sym, v in acc.items()
            if len(v) == form and member_on(membership, sym, d) and d in rets.get(sym, {})
        ]
        if len(candidates) < 50:
            continue
        candidates.sort()
        k = max(int(len(candidates) * frac), 5)
        low = {sym for _, sym in candidates[:k]}
        high = {sym for _, sym in candidates[-k:]}
        low_r = sum(rets[s][d] for s in low) / len(low)
        high_r = sum(rets[s][d] for s in high) / len(high)
        gross = (low_r - high_r) / 2
        # turnover: fraction of each half-book replaced today (one-way),
        # each replaced weight pays cost on exit AND entry (2 sides)
        if prev_low:
            churn_low = len(low ^ prev_low) / (2 * len(low))
            churn_high = len(high ^ prev_high) / (2 * len(high))
        else:
            churn_low = churn_high = 1.0  # initial build
        turnover = (churn_low + churn_high) / 2  # per unit of gross/2 per side
        cost = turnover * 2 * COST_PER_SIDE  # exit + entry
        out[d] = gross - cost
        prev_low, prev_high = low, high
    return out


def insider_costed_series(pit: Path, membership, trading_days, rets):
    purchases = pd.read_parquet(pit / "insider_purchases.parquet")
    purchases["knowledge_time"] = pd.to_datetime(purchases["knowledge_time"], utc=True)
    active = active_days(purchases, trading_days, INSIDER_VARIANT)
    out: dict = {}
    prev: set[str] = set()
    for d in trading_days[1:]:
        longs = {
            t
            for t, days in active.items()
            if d in days and member_on(membership, t, d) and d in rets.get(t, {})
        }
        uni = [rets[t][d] for t in rets if d in rets[t] and member_on(membership, t, d)]
        if not uni:
            continue
        uni_mean = sum(uni) / len(uni)
        if longs:
            gross = sum(rets[t][d] for t in longs) / len(longs) - uni_mean
            churn = len(longs ^ prev) / (2 * len(longs)) if prev else 1.0
            out[d] = gross - churn * 2 * COST_PER_SIDE
        else:
            out[d] = 0.0
        prev = longs
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pit-dir", default="data/pit")
    p.add_argument("--out", default="data/pit/composite_result.json")
    args = p.parse_args(argv)
    pit = Path(args.pit_dir)

    prices = load_prices(pit / "bars")
    membership = load_membership(pit)
    all_days = sorted({d for s in prices.values() for d in s})
    trading_days = [d for d in all_days if DEV_START <= d <= VAL_END]
    rets = daily_returns(prices, trading_days)

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
    mom_series = {d: r for d, r in mom["daily_rets"]}
    sv_series = shortvol_costed_series(pit, membership, prices, trading_days, rets)
    ins_series = insider_costed_series(pit, membership, trading_days, rets)

    common = sorted(set(mom_series) & set(sv_series) & set(ins_series))
    bench = np.array([mom_series[d] for d in common])
    sv = np.array([sv_series[d] for d in common])
    ins = np.array([ins_series[d] for d in common])
    n = len(common)

    def stats(series: np.ndarray) -> dict:
        sd = float(series.std())
        sharpe = float(series.mean() / sd) if sd > 0 else 0.0
        return {
            "sharpe_daily": round(sharpe, 4),
            "sharpe_annualized": round(sharpe * 252**0.5, 3),
            "mean_daily_bps": round(float(series.mean()) * 1e4, 3),
        }

    registry = TrialRegistry(pit / "trial_registry.jsonl")
    candidates: dict[str, np.ndarray] = {}
    comp_stats = []
    for weights in COMPOSITES:
        series = (
            weights["momentum"] * bench
            + weights["short_volume"] * sv
            + weights["insider"] * ins
        )
        name = (
            f"m{weights['momentum']:.1f}"
            f"_sv{weights['short_volume']:.1f}"
            f"_in{weights['insider']:.1f}"
        )
        candidates[name] = series
        s = stats(series)
        sharpe_val = s["sharpe_daily"]
        registry.record("composite", weights, sharpe_val, n, "2022-01..2025-06")
        comp_stats.append({"weights": weights, **s})

    spa = spa_test(bench, candidates, n_boot=1000, mean_block=21.0, seed=11)
    best_name = max(candidates, key=lambda k: float(candidates[k].mean()))
    n_trials, sharpe_var = registry.dsr_inputs("composite")
    best_sharpe = max(c["sharpe_daily"] for c in comp_stats)
    dsr = deflated_sharpe_ratio(best_sharpe, n_trials, sharpe_var, n)

    report = {
        "phase": "2 - costed composite vs momentum",
        "window": "2022-01..2025-06 (dev+validation only)",
        "n_obs": n,
        "sleeves_net_of_costs": {
            "momentum": stats(bench),
            "short_volume_costed": stats(sv),
            "insider_costed": stats(ins),
            "sleeve_correlations": {
                "sv_vs_mom": round(float(np.corrcoef(sv, bench)[0, 1]), 4),
                "ins_vs_mom": round(float(np.corrcoef(ins, bench)[0, 1]), 4),
                "sv_vs_ins": round(float(np.corrcoef(sv, ins)[0, 1]), 4),
            },
        },
        "composites": comp_stats,
        "spa_gate": {
            "benchmark": "momentum-alone (net)",
            "p_value": spa["p_value"],
            "passes_0.05": spa["p_value"] < 0.05,
            "best_candidate": best_name,
        },
        "dsr_best_composite": {
            "registry_trials": n_trials,
            "deflated_sharpe": round(dsr, 4),
        },
    }
    Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
