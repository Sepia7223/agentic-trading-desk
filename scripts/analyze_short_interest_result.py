"""Post-gauntlet analysis for the surviving days-to-cover variant.

Pre-registered follow-ups (validate_short_interest_signal.py docstring):
"SPA vs momentum only if a variant survives standalone." days-to-cover
survived (Sharpe 1.07/yr, DSR 0.9868, CPCV 15/15), so this script runs:

1. BORROW-FEE STRESS — the sleeve shorts the HIGH days-to-cover quintile
   (crowded shorts), where stock borrow can be elevated. The base cost
   model has no borrow. Stress at 1%/yr and 2%/yr on the short leg
   (= 0.5%/1.0%/yr on equity at gross 1.0). Bar (M12 cost-stress logic):
   the edge must not lose more than half its Sharpe at the 2% stress.
2. HANSEN SPA vs momentum-alone — candidates: DTC sleeve standalone and
   the 50/50 momentum/DTC composite (both recorded as trials in family
   "short-interest-composite"). This is the ADOPTION gate the earlier
   short-vol composite failed at p=0.395.

Usage:
    PYTHONPATH="src;scripts" python scripts/analyze_short_interest_result.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from trading_desk.trials import TrialRegistry, spa_test
from validate_short_interest_signal import (  # noqa: E402  (scripts path)
    DEV_START,
    VAL_END,
    build_series,
    load_partitions,
)

BORROW_STRESSES = (0.01, 0.02)  # annual borrow on the short leg (gross/2)


def annualized_sharpe(series: np.ndarray) -> float:
    sd = float(series.std())
    return float(series.mean() / sd) * 252**0.5 if sd > 0 else 0.0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pit-dir", default="data/pit")
    p.add_argument("--out", default="data/pit/short_interest_analysis.json")
    args = p.parse_args(argv)
    pit = Path(args.pit_dir)

    import equity_backtest_v2 as ebt  # noqa: PLC0415 - scripts path
    from validate_insider_signal import (  # noqa: PLC0415 - scripts path
        daily_returns,
        load_membership,
        load_prices,
        member_on,
    )

    partitions = load_partitions(pit / "consolidated_short_interest")
    prices = load_prices(pit / "bars")
    membership = load_membership(pit)
    all_days = sorted({d for s in prices.values() for d in s})
    trading_days = [d for d in all_days if DEV_START <= d <= VAL_END]
    rets = daily_returns(prices, trading_days)

    series_map = build_series(
        partitions, membership, rets, trading_days, member_on, "days-to-cover"
    )

    # momentum benchmark: the same engine/config the composite gate used
    intervals, sectors, _cov = ebt.load_universe(pit, "2021-01-01", "2026-06-30")
    eprices = ebt.load_prices(pit / "bars")
    eprices.pop("SPY", None)
    mom = ebt.run(
        eprices,
        intervals,
        sectors,
        start=DEV_START,
        end=VAL_END,
        lookback=252,
        skip=21,
        basket=30,
        hold_buffer=60,
        buffered=True,
        sector_neutral=True,
        rebalance_every=5,
        gross=1.0,
        half_spread_bps=2.5,
        slippage_bps=1.0,
        commission_bps=0.5,
        borrow_fee_annual=0.005,
        min_short_price=5.0,
        delay=0,
        start_equity=1000.0,
    )
    mom_map = {d: r for d, r in mom["daily_rets"]}

    common = sorted(set(series_map) & set(mom_map))
    dtc = np.array([series_map[d] for d in common])
    bench = np.array([mom_map[d] for d in common])
    n = len(common)
    vol = float(dtc.std()) * 252**0.5
    base_sharpe = annualized_sharpe(dtc)
    print(f"common days: {n}; DTC sleeve vol {vol:.2%}/yr, Sharpe {base_sharpe:.3f}")

    stress: dict[str, float] = {}
    for borrow in BORROW_STRESSES:
        stressed = dtc - (borrow * 0.5) / 252  # short leg = gross/2 of equity
        s = annualized_sharpe(stressed)
        stress[f"borrow_{borrow:.0%}"] = round(s, 4)
        print(f"borrow stress {borrow:.0%}/yr on short leg: Sharpe {s:.3f}")
    stress_ok = stress[f"borrow_{BORROW_STRESSES[-1]:.0%}"] >= base_sharpe / 2

    composite = 0.5 * bench + 0.5 * dtc
    registry = TrialRegistry(pit / "trial_registry.jsonl")
    for name, series in (("dtc-standalone", dtc), ("mom-dtc-50-50", composite)):
        registry.record(
            family="short-interest-composite",
            params={"candidate": name},
            sharpe=float(series.mean() / series.std()) if series.std() > 0 else 0.0,
            n_observations=n,
            window=f"{DEV_START.isoformat()}..{VAL_END.isoformat()}",
        )
    spa = spa_test(bench, {"dtc-standalone": dtc, "mom-dtc-50-50": composite})
    print(
        f"SPA vs momentum: p={spa['p_value']:.4f} "
        f"(momentum Sharpe {annualized_sharpe(bench):.3f}, "
        f"composite Sharpe {annualized_sharpe(composite):.3f})"
    )

    Path(args.out).write_text(
        json.dumps(
            {
                "n_days": n,
                "dtc_sharpe": round(base_sharpe, 4),
                "dtc_vol_annual": round(vol, 4),
                "momentum_sharpe": round(annualized_sharpe(bench), 4),
                "composite_sharpe": round(annualized_sharpe(composite), 4),
                "borrow_stress": stress,
                "borrow_stress_pass": stress_ok,
                "spa_p_value": round(float(spa["p_value"]), 4),
                "correlation_dtc_momentum": round(float(np.corrcoef(dtc, bench)[0, 1]), 4),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
