"""Challenge-mode candidate #2: short-volume L/S restricted to the CFD universe.

Motivation (see docs/strategy-research/PROP-CHALLENGE-DECISION.md): the
short-volume ratio signal is our strongest fully-validated edge (full
universe: net Sharpe 0.76, DSR 0.9993 PASS, CPCV 15/15 PASS). It was not
adopted for the paper account because the momentum+shortvol COMPOSITE could
not beat momentum under the SPA gate — an adoption question. Challenge-mode
asks a different, pre-registered question: does the STANDALONE signal retain
edge when restricted to the ~30 US share CFDs a credible prop firm actually
lists, after CFD financing? If yes at Sharpe ~0.4+, the challenge math
changes materially (P(fund) 50-65%+); if no, that is one more honest no.

Same protections as the momentum variant test: the LEGACY pre-2026 symbol
list only (no listing look-ahead), turnover-based trade costs (4bps/side),
CFD financing drag of gross x 2.5%/yr, trial-registry registration, DSR and
CPCV gates, degenerate runs fail loudly.

Usage:
    PYTHONPATH="src;scripts" python scripts/validate_challenge_shortvol_variant.py
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np

from trading_desk.research.challenge import ChallengeRules, simulate_challenge
from trading_desk.trials import TrialRegistry, deflated_sharpe_ratio
from trading_desk.trials.cpcv import combinatorial_purged_splits

COST_PER_SIDE = 4e-4  # half-spread 2.5 + slippage 1 + commission 0.5 bps
CFD_SPREAD_ANNUAL = 0.025  # financing drag per unit gross (benchmark cancels)
FORMATION_DAYS = 5  # the Phase-1 winning variant
BUCKET_FRACTION = 0.2
MIN_CANDIDATES = 20  # full-universe script used 50; 30-name book needs less
MIN_BUCKET = 5

DEV_START = date(2022, 1, 3)
VAL_END = date(2026, 6, 30)

CHALLENGE = (
    ChallengeRules(0.08, 0.10, False, 0.05, None, 5),
    ChallengeRules(0.05, 0.10, False, 0.05, None, 5),
)


def annualized(series: np.ndarray) -> tuple[float, float, float]:
    sd = float(series.std())
    if sd == 0:
        return 0.0, float(series.mean()) * 252, 0.0
    return (
        float(series.mean() / sd) * 252**0.5,
        float(series.mean()) * 252,
        sd * 252**0.5,
    )


def shortvol_series(
    ratios_by_day: dict[date, dict[str, float]],
    membership: dict,
    rets: dict[str, dict[date, float]],
    trading_days: list[date],
    member_on,
) -> dict[date, float]:
    """Daily L/S return net of turnover costs, mirroring the validated
    full-universe construction (long low short-ratio, short high)."""

    ratio_days = sorted(ratios_by_day)
    out: dict[date, float] = {}
    prev_low: set[str] = set()
    prev_high: set[str] = set()
    for d in trading_days:
        window = [rd for rd in ratio_days if rd < d][-FORMATION_DAYS:]
        if len(window) < FORMATION_DAYS:
            continue
        acc: dict[str, list[float]] = {}
        for rd in window:
            for sym, r in ratios_by_day[rd].items():
                acc.setdefault(sym, []).append(r)
        candidates = [
            (sum(v) / len(v), sym)
            for sym, v in acc.items()
            if len(v) == FORMATION_DAYS and member_on(membership, sym, d) and d in rets.get(sym, {})
        ]
        if len(candidates) < MIN_CANDIDATES:
            continue
        candidates.sort()
        k = max(int(len(candidates) * BUCKET_FRACTION), MIN_BUCKET)
        low = {sym for _, sym in candidates[:k]}
        high = {sym for _, sym in candidates[-k:]}
        low_r = sum(rets[s][d] for s in low) / len(low)
        high_r = sum(rets[s][d] for s in high) / len(high)
        gross = (low_r - high_r) / 2
        if prev_low:
            churn_low = len(low ^ prev_low) / (2 * len(low))
            churn_high = len(high ^ prev_high) / (2 * len(high))
        else:
            churn_low = churn_high = 1.0
        turnover = (churn_low + churn_high) / 2
        cost = turnover * 2 * COST_PER_SIDE
        out[d] = gross - cost
        prev_low, prev_high = low, high
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pit-dir", default="data/pit")
    p.add_argument("--out", default="data/pit/challenge_shortvol_variant_result.json")
    args = p.parse_args(argv)
    pit = Path(args.pit_dir)

    from validate_challenge_cfd_variant import (  # noqa: PLC0415 - scripts path
        LEGACY_UNIVERSE,
    )
    from validate_insider_signal import (  # noqa: PLC0415 - scripts path
        daily_returns,
        load_membership,
        load_prices,
        member_on,
    )
    from validate_short_volume_signal import (  # noqa: PLC0415 - scripts path
        load_short_ratios,
    )

    prices = load_prices(pit / "bars")
    membership = load_membership(pit)
    universe = sorted(set(LEGACY_UNIVERSE) & set(prices))
    print(f"CFD legacy universe: {len(universe)}/{len(LEGACY_UNIVERSE)} names with data")

    all_days = sorted({d for s in prices.values() for d in s})
    trading_days = [d for d in all_days if DEV_START <= d <= VAL_END]
    rets = daily_returns({t: prices[t] for t in universe}, trading_days)
    ratios_by_day = load_short_ratios(pit / "shortvol", set(universe))
    print(f"short-volume coverage: {len(ratios_by_day)} days")

    series = shortvol_series(ratios_by_day, membership, rets, trading_days, member_on)
    daily = np.array([series[d] for d in sorted(series)])
    n = len(daily)
    if n < 200 or float(daily.std()) < 1e-9:
        raise SystemExit(f"degenerate run (n={n}) - nothing to register")

    # CFD financing: the equity construction pays no borrow here, so the CFD
    # drag is the full spread on gross 1.0.
    cfd_daily = daily - CFD_SPREAD_ANNUAL / 252
    s_eq, m_eq, v_eq = annualized(daily)
    s_cfd, m_cfd, v_cfd = annualized(cfd_daily)
    print(
        f"shortvol on CFD universe (equity costs): Sharpe {s_eq:.3f} "
        f"(mean {m_eq:.2%}/yr, vol {v_eq:.2%}/yr, n={n})"
    )
    print(
        f"after CFD financing (+{CFD_SPREAD_ANNUAL:.1%}/yr): "
        f"Sharpe {s_cfd:.3f} (mean {m_cfd:.2%}/yr)"
    )

    sr_daily = float(cfd_daily.mean() / cfd_daily.std())
    registry = TrialRegistry(pit / "trial_registry.jsonl")
    registry.record(
        family="challenge-cfd-shortvol",
        params={
            "universe": "ftmo-legacy-23",
            "formation_days": FORMATION_DAYS,
            "bucket_fraction": BUCKET_FRACTION,
            "cfd_spread_annual": CFD_SPREAD_ANNUAL,
        },
        sharpe=sr_daily,
        n_observations=n,
        window=f"{DEV_START.isoformat()}..{VAL_END.isoformat()}",
    )
    n_trials, sharpe_var = registry.dsr_inputs("challenge-cfd-shortvol")
    dsr = deflated_sharpe_ratio(
        observed_sharpe=sr_daily,
        n_trials=max(n_trials, 1),
        sharpe_variance=max(sharpe_var, 1e-8),
        n_observations=n,
        skewness=float(((cfd_daily - cfd_daily.mean()) ** 3).mean() / cfd_daily.std() ** 3),
        kurtosis=float(((cfd_daily - cfd_daily.mean()) ** 4).mean() / cfd_daily.std() ** 4),
    )
    print(f"DSR (n_trials={n_trials}): {dsr:.4f}")

    splits = combinatorial_purged_splits(n, n_groups=6, test_groups=2, label_span=1, embargo=5)
    positive = sum(
        1
        for _, test_idx in splits
        if cfd_daily[test_idx].std() > 0
        and cfd_daily[test_idx].mean() / cfd_daily[test_idx].std() > 0
    )
    print(f"CPCV: {positive}/{len(splits)} test folds with positive Sharpe")

    print("\nP(fund), generic 2-step 8->5 static-10 geometry:")
    p_fund = {}
    for vol in (0.12, 0.16):
        out = simulate_challenge(CHALLENGE, s_cfd, vol, n_paths=20_000, max_days=500)
        p_fund[f"{vol:.0%}"] = round(out.p_total, 4)
        print(f"  vol {vol:.0%}: P(fund) = {out.p_total:.1%}")

    Path(args.out).write_text(
        json.dumps(
            {
                "universe_names": universe,
                "n_days": n,
                "sharpe_equity_costs": round(s_eq, 4),
                "sharpe_after_cfd_financing": round(s_cfd, 4),
                "mean_annual_after_cfd": round(m_cfd, 5),
                "vol_annual_gross1": round(v_cfd, 5),
                "dsr": round(dsr, 4),
                "cpcv_positive_folds": f"{positive}/{len(splits)}",
                "p_fund_by_vol": p_fund,
                "caveats": [
                    "legacy universe approximates FTMO's pre-2026 list",
                    "full-universe standalone published: net Sharpe 0.76 (reference)",
                    "daily-churn strategy: cost model is turnover-based 4bps/side",
                    "forward evidence still required before any fee",
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nwritten: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
