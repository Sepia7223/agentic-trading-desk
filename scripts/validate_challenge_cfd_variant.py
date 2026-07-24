"""Challenge-mode feasibility: momentum concentrated to a CFD-sized universe.

The prop-challenge decision doc (docs/strategy-research/
PROP-CHALLENGE-DECISION.md) requires an honest answer to: does our momentum
edge survive (a) concentration to the ~2-3 dozen US share CFDs a credible
CFD prop firm actually lists, and (b) CFD financing?

Financing model (symmetric long-short book): longs pay benchmark+spread,
shorts receive benchmark-spread, so the benchmark cancels and the net drag
is GROSS x spread per year (spread ~2.5%). Equity borrow fees charged by the
engine are removed (CFD shorts don't pay stock borrow separately). Leverage
scales returns, volatility and financing together, so the post-financing
Sharpe is leverage-invariant — it is THE number that decides the route.

The universe below APPROXIMATES FTMO's 2026 US share-CFD list from the
research fan-out (23 legacy blue chips + the March 2026 additions); the
exact list must be re-pulled from ftmo.com/en/symbols before any fee.
Registered as a trial like every other variant. Per-share commission
minimums (~USD 0.02/share-style CFD schedules) are NOT modeled — another
reason to treat a marginal PASS here with suspicion.

Usage:
    PYTHONPATH="src;scripts" python scripts/validate_challenge_cfd_variant.py
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

CFD_SPREAD_ANNUAL = 0.025  # financing spread over/under benchmark, each side
EQUITY_BORROW_ANNUAL = 0.005  # what the engine charged; refunded for CFDs

# LEGACY = the ~23 blue chips FTMO listed BEFORE 2026 — the only honest
# universe for a 2022-2026 backtest. The 2026 additions (PLTR, SNOW, GME,
# MSTR, ...) were listed AFTER they had already run: including them for the
# whole window is look-ahead smuggled in through the firm's listing choices,
# so the EXPANDED run is reported only as a sensitivity, never as evidence.
LEGACY_UNIVERSE = [
    "AAPL",
    "MSFT",
    "AMZN",
    "GOOGL",
    "META",
    "NVDA",
    "TSLA",
    "NFLX",
    "AMD",
    "INTC",
    "ORCL",
    "CSCO",
    "CRM",
    "ADBE",
    "QCOM",
    "JPM",
    "BAC",
    "V",
    "MA",
    "WMT",
    "KO",
    "PEP",
    "PFE",
    "JNJ",
    "PG",
    "XOM",
    "CVX",
    "DIS",
    "BA",
    "UBER",
]
ADDITIONS_2026 = ["AVGO", "PLTR", "SNOW", "GME", "MSTR"]

DEV_START = date(2022, 1, 3)
VAL_END = date(2026, 6, 30)

CHALLENGE = (
    ChallengeRules(0.08, 0.10, False, 0.05, None, 5),
    ChallengeRules(0.05, 0.10, False, 0.05, None, 5),
)


def annualized(series: np.ndarray) -> tuple[float, float, float]:
    """(sharpe_annual, mean_annual, vol_annual) from daily returns."""

    sd = float(series.std())
    if sd == 0:
        return 0.0, float(series.mean()) * 252, 0.0
    return (
        float(series.mean() / sd) * 252**0.5,
        float(series.mean()) * 252,
        sd * 252**0.5,
    )


def run_variant(
    label: str,
    universe: list[str],
    prices: dict,
    intervals: dict,
    sectors: dict,
    ebt,
) -> tuple[np.ndarray, list[str]]:
    """Backtest one universe variant; return CFD-financed daily returns.

    basket=6: the engine trades only when >= 4*basket names are eligible
    (equity_backtest_v2.py), so a ~30-name universe needs basket <= 7;
    6 keeps headroom for membership/price gaps and equals a top/bottom-20%
    book on 30 names. Same basket for both variants so the look-ahead
    sensitivity is apples-to-apples.
    """

    available = sorted(set(universe) & set(prices))
    result = ebt.run(
        {t: prices[t] for t in available},
        intervals,
        sectors,
        start=DEV_START,
        end=VAL_END,
        lookback=252,
        skip=21,
        basket=6,
        hold_buffer=16,
        buffered=True,
        sector_neutral=False,
        rebalance_every=5,
        gross=1.0,
        half_spread_bps=2.5,
        slippage_bps=1.0,
        commission_bps=0.5,
        borrow_fee_annual=EQUITY_BORROW_ANNUAL,
        min_short_price=5.0,
        delay=0,
        start_equity=1000.0,
    )
    daily = np.array([r for _, r in result["daily_rets"]])
    # CFD financing swap: remove the engine's equity borrow charge (0.5%/yr
    # on the short half), add the CFD spread on BOTH halves (benchmark
    # cancels): net extra drag/yr at gross 1.0. Leverage-invariant in Sharpe.
    extra_drag_annual = 1.0 * CFD_SPREAD_ANNUAL - 0.5 * EQUITY_BORROW_ANNUAL
    cfd_daily = daily - extra_drag_annual / 252
    s_eq, m_eq, v_eq = annualized(daily)
    s_cfd, m_cfd, _ = annualized(cfd_daily)
    print(
        f"[{label}] {len(available)} names | equity-cost Sharpe {s_eq:.3f} "
        f"(mean {m_eq:.2%}/yr, vol {v_eq:.2%}/yr) | after CFD financing "
        f"(+{extra_drag_annual:.2%}/yr): Sharpe {s_cfd:.3f} (mean {m_cfd:.2%}/yr)"
    )
    return cfd_daily, available


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pit-dir", default="data/pit")
    p.add_argument("--out", default="data/pit/challenge_cfd_variant_result.json")
    args = p.parse_args(argv)
    pit = Path(args.pit_dir)

    import equity_backtest_v2 as ebt  # noqa: PLC0415 - scripts-path import

    intervals, sectors, _cov = ebt.load_universe(pit, "2021-01-01", "2026-06-30")
    prices = ebt.load_prices(pit / "bars")
    prices.pop("SPY", None)

    # PRIMARY: the legacy pre-2026 FTMO list (no listing look-ahead).
    cfd_daily, legacy_names = run_variant(
        "legacy-23", LEGACY_UNIVERSE, prices, intervals, sectors, ebt
    )
    # SENSITIVITY ONLY: with 2026 additions (embeds listing look-ahead).
    expanded_daily, _ = run_variant(
        "expanded+2026 (look-ahead, sensitivity only)",
        LEGACY_UNIVERSE + ADDITIONS_2026,
        prices,
        intervals,
        sectors,
        ebt,
    )

    n = len(cfd_daily)
    s_cfd, m_cfd, v_cfd = annualized(cfd_daily)
    s_exp = annualized(expanded_daily)[0]
    lookahead_gap = s_exp - s_cfd
    print(f"listing look-ahead gap (expanded - legacy Sharpe): {lookahead_gap:+.3f}")

    if float(cfd_daily.std()) < 1e-9:
        # zero-trade/degenerate run: recording a division-by-noise Sharpe
        # would poison the registry's cross-trial variance — fail loudly.
        raise SystemExit("degenerate run (no trades) - nothing to register")
    sr_daily = float(cfd_daily.mean() / cfd_daily.std())
    registry = TrialRegistry(pit / "trial_registry.jsonl")
    registry.record(
        family="challenge-cfd-concentrated",
        params={
            "universe": "ftmo-legacy-23",
            "basket": 6,
            "hold_buffer": 16,
            "sector_neutral": False,
            "cfd_spread_annual": CFD_SPREAD_ANNUAL,
        },
        sharpe=sr_daily,
        n_observations=n,
        window=f"{DEV_START.isoformat()}..{VAL_END.isoformat()}",
    )
    n_trials, sharpe_var = registry.dsr_inputs("challenge-cfd-concentrated")
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
    positive = 0
    for _, test_idx in splits:
        seg = cfd_daily[test_idx]
        if seg.std() > 0 and seg.mean() / seg.std() > 0:
            positive += 1
    print(f"CPCV: {positive}/{len(splits)} test folds with positive Sharpe")

    print("\nP(fund), generic 2-step 8->5 static-10 geometry, at challenge vols:")
    p_fund = {}
    for vol in (0.12, 0.16):
        out = simulate_challenge(CHALLENGE, s_cfd, vol, n_paths=20_000, max_days=500)
        p_fund[f"{vol:.0%}"] = round(out.p_total, 4)
        print(f"  vol {vol:.0%}: P(fund) = {out.p_total:.1%}")

    Path(args.out).write_text(
        json.dumps(
            {
                "universe_names": legacy_names,
                "n_days": n,
                "sharpe_after_cfd_financing": round(s_cfd, 4),
                "sharpe_expanded_lookahead": round(s_exp, 4),
                "lookahead_gap": round(lookahead_gap, 4),
                "mean_annual_after_cfd": round(m_cfd, 5),
                "vol_annual_gross1": round(v_cfd, 5),
                "dsr": round(dsr, 4),
                "cpcv_positive_folds": f"{positive}/{len(splits)}",
                "p_fund_by_vol": p_fund,
                "caveats": [
                    "legacy universe approximates FTMO's pre-2026 list; re-verify",
                    "per-share commission minimums not modeled",
                    "2022-2026 window is one mega-cap-friendly regime",
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
