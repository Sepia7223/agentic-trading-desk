"""Challenge-mode candidate #3: days-to-cover restricted to the CFD universe.

The DTC sleeve passed its pre-registered full-universe gauntlet (Sharpe
1.04, DSR 0.9868, CPCV 15/15, borrow-stress robust). The challenge venue
question is whether it survives the ~30 US share CFDs a credible prop firm
lists — the restriction that killed short-vol (-0.66) and left momentum
marginal (0.13). One registered trial, no grid: same construction, legacy
pre-2026 universe (no listing look-ahead), bucket floor lowered to fit a
30-name cross-section (6/side), CFD financing drag of gross x 2.5%/yr.

Usage:
    PYTHONPATH="src;scripts" python scripts/validate_challenge_dtc_variant.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from trading_desk.research.challenge import ChallengeRules, simulate_challenge
from trading_desk.trials import TrialRegistry, deflated_sharpe_ratio
from trading_desk.trials.cpcv import combinatorial_purged_splits

CFD_SPREAD_ANNUAL = 0.025
CFD_MIN_CANDIDATES = 20

CHALLENGE = (
    ChallengeRules(0.08, 0.10, False, 0.05, None, 5),
    ChallengeRules(0.05, 0.10, False, 0.05, None, 5),
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pit-dir", default="data/pit")
    p.add_argument("--out", default="data/pit/challenge_dtc_variant_result.json")
    args = p.parse_args(argv)
    pit = Path(args.pit_dir)

    from validate_challenge_cfd_variant import LEGACY_UNIVERSE  # noqa: PLC0415
    from validate_insider_signal import (  # noqa: PLC0415 - scripts path
        daily_returns,
        load_membership,
        load_prices,
        member_on,
    )
    from validate_short_interest_signal import (  # noqa: PLC0415 - scripts path
        DEV_START,
        VAL_END,
        build_series,
        load_partitions,
    )

    partitions = load_partitions(pit / "consolidated_short_interest")
    prices = load_prices(pit / "bars")
    membership = load_membership(pit)
    universe = sorted(set(LEGACY_UNIVERSE) & set(prices))
    print(f"CFD legacy universe: {len(universe)} names")

    all_days = sorted({d for s in prices.values() for d in s})
    trading_days = [d for d in all_days if DEV_START <= d <= VAL_END]
    rets = daily_returns({t: prices[t] for t in universe}, trading_days)

    series_map = build_series(
        partitions,
        membership,
        rets,
        trading_days,
        member_on,
        "days-to-cover",
        min_candidates=CFD_MIN_CANDIDATES,
    )
    daily = np.array([series_map[d] for d in sorted(series_map)])
    n = len(daily)
    if n < 200 or float(daily.std()) < 1e-9:
        raise SystemExit(f"degenerate run (n={n}) - nothing to register")

    cfd_daily = daily - CFD_SPREAD_ANNUAL / 252
    sd = float(cfd_daily.std())
    s_cfd = float(cfd_daily.mean() / sd) * 252**0.5
    vol = sd * 252**0.5
    print(f"DTC on CFD universe after financing: Sharpe {s_cfd:.3f}, vol {vol:.2%}/yr, n={n}")

    sr_daily = float(cfd_daily.mean() / sd)
    registry = TrialRegistry(pit / "trial_registry.jsonl")
    registry.record(
        family="challenge-cfd-dtc",
        params={
            "universe": "ftmo-legacy-23",
            "min_candidates": CFD_MIN_CANDIDATES,
            "cfd_spread_annual": CFD_SPREAD_ANNUAL,
        },
        sharpe=sr_daily,
        n_observations=n,
        window=f"{DEV_START.isoformat()}..{VAL_END.isoformat()}",
    )
    n_trials, sharpe_var = registry.dsr_inputs("challenge-cfd-dtc")
    dsr = deflated_sharpe_ratio(
        observed_sharpe=sr_daily,
        n_trials=max(n_trials, 1),
        sharpe_variance=max(sharpe_var, 1e-8),
        n_observations=n,
        skewness=float(((cfd_daily - cfd_daily.mean()) ** 3).mean() / sd**3),
        kurtosis=float(((cfd_daily - cfd_daily.mean()) ** 4).mean() / sd**4),
    )
    splits = combinatorial_purged_splits(n, n_groups=6, test_groups=2, label_span=1, embargo=5)
    positive = sum(
        1
        for _, test_idx in splits
        if cfd_daily[test_idx].std() > 0 and cfd_daily[test_idx].mean() > 0
    )
    print(f"DSR (n_trials={n_trials}): {dsr:.4f} | CPCV {positive}/{len(splits)}")

    p_fund = {}
    for vol_target in (0.12, 0.16):
        out = simulate_challenge(CHALLENGE, s_cfd, vol_target, n_paths=20_000, max_days=500)
        p_fund[f"{vol_target:.0%}"] = round(out.p_total, 4)
        print(f"P(fund) at {vol_target:.0%} vol: {out.p_total:.1%}")

    Path(args.out).write_text(
        json.dumps(
            {
                "n_days": n,
                "sharpe_after_cfd_financing": round(s_cfd, 4),
                "vol_annual_gross1": round(vol, 4),
                "dsr": round(dsr, 4),
                "cpcv_positive_folds": f"{positive}/{len(splits)}",
                "p_fund_by_vol": p_fund,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
