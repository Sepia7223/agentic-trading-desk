"""Statistical validation suite for equity_backtest_v2 (reviewer gates).

Runs the v2 engine through the robustness battery the reviewer required before
any result is trusted:

  windows     — multiple non-overlapping sub-windows (regime coverage), not one
                lucky span.
  bootstrap   — BLOCK bootstrap (not i.i.d. daily resampling) of the realised
                daily-return series -> confidence intervals on CAGR and Sharpe.
  delay       — execution-delay stress (signals filled one day late).
  costs       — stressed execution costs (1.5x, 2x) and doubled borrow fee.
  buffered    — buffered vs daily rebalancing comparison (turnover vs edge).
  implement   — small-account implementability report: $/position at a given
                account size vs a minimum-ticket threshold.

Deterministic: bootstrap uses a fixed seed. RESEARCH tooling; produces evidence,
grants no authority.

Usage:
    PYTHONPATH=scripts python scripts/validation_suite_v2.py \
        --start 2022-01-01 --end 2025-06-30 [--out suite.json]
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
from datetime import date
from pathlib import Path

from equity_backtest_v2 import (  # type: ignore[import-not-found]
    load_prices,
    load_universe,
    run,
    summarize,
)


def block_bootstrap(
    rets: list[float], n_iter: int = 500, block: int = 21, seed: int = 42
) -> dict:
    """Resample the daily-return series in contiguous blocks; CI on CAGR/Sharpe."""
    rng = random.Random(seed)
    n = len(rets)
    cagrs: list[float] = []
    sharpes: list[float] = []
    for _ in range(n_iter):
        sample: list[float] = []
        while len(sample) < n:
            i = rng.randrange(0, max(n - block, 1))
            sample.extend(rets[i : i + block])
        sample = sample[:n]
        eq = 1.0
        for r in sample:
            eq *= 1 + r
        years = n / 252
        cagrs.append(eq ** (1 / years) - 1 if years > 0 else 0.0)
        sd = statistics.pstdev(sample)
        sharpes.append(statistics.mean(sample) / sd * (252**0.5) if sd > 0 else 0.0)
    cagrs.sort()
    sharpes.sort()

    def pct(xs: list[float], q: float) -> float:
        return xs[min(int(q * len(xs)), len(xs) - 1)]

    return {
        "iterations": n_iter,
        "block_days": block,
        "cagr_pct_ci90": [round(pct(cagrs, 0.05) * 100, 1), round(pct(cagrs, 0.95) * 100, 1)],
        "cagr_pct_median": round(pct(cagrs, 0.5) * 100, 1),
        "sharpe_ci90": [round(pct(sharpes, 0.05), 2), round(pct(sharpes, 0.95), 2)],
        "sharpe_median": round(pct(sharpes, 0.5), 2),
        "prob_cagr_negative": round(sum(1 for c in cagrs if c <= 0) / len(cagrs), 3),
    }


def implementability(account: float, gross: float, basket: int) -> dict:
    per_position = account * (gross / 2) / basket
    return {
        "account": account,
        "gross": gross,
        "positions": 2 * basket,
        "dollars_per_position": round(per_position, 2),
        "workable_with_fractional_shares": per_position >= 5,
        "workable_without_fractional": per_position >= 500,
        "note": (
            "long-short needs marginable account; fractional SHORTS are rarely "
            "available -> without fractional shorting, each short position needs "
            "at least ~1 share of a typical S&P name (often $50-500+)."
        ),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2022-01-01")
    p.add_argument("--end", default="2025-06-30")
    p.add_argument("--universe-window", default="2021-01-01:2026-06-30")
    p.add_argument("--lookback", type=int, default=252)
    p.add_argument("--skip", type=int, default=21)
    p.add_argument("--basket", type=int, default=30)
    p.add_argument("--gross", type=float, default=1.0)
    p.add_argument("--pit-dir", default="data/pit")
    p.add_argument("--accounts", default="1000,10000,100000")
    p.add_argument("--out", default=None)
    args = p.parse_args(argv)

    pit = Path(args.pit_dir)
    uw_start, uw_end = args.universe_window.split(":")
    intervals, sectors, coverage = load_universe(pit, uw_start, uw_end)
    prices = load_prices(pit / "bars")
    spy = prices.pop("SPY", None)

    base_kwargs = dict(
        lookback=args.lookback,
        skip=args.skip,
        basket=args.basket,
        hold_buffer=2 * args.basket,
        buffered=False,
        rebalance_every=1,
        gross=args.gross,
        half_spread_bps=2.5,
        slippage_bps=1.0,
        commission_bps=0.5,
        borrow_fee_annual=0.005,
        min_short_price=5.0,
        delay=0,
        start_equity=1000.0,
    )

    def run_case(label: str, start: str, end: str, **over) -> dict:
        kw = {**base_kwargs, **over}
        res = run(
            prices, intervals, sectors,
            start=date.fromisoformat(start), end=date.fromisoformat(end), **kw
        )
        m = summarize(res, kw["start_equity"], spy)
        keep = (
            "total_return_pct", "cagr_pct", "max_drawdown_pct", "annualised_sharpe",
            "calmar_like", "pct_months_positive", "beta_vs_spy",
            "max_abs_sector_net_pct", "annual_turnover_multiple",
            "cost_per_dollar_traded_bps", "position_changes_per_day",
            "top5_name_pnl_share", "worst_day_pct", "ruin",
        )
        return {"label": label, "window": [start, end],
                **{k: m.get(k) for k in keep}}, res

    suite: dict = {"engine": "equity_backtest_v2", "params": base_kwargs,
                   "coverage": None if coverage is None else {
                       "full": coverage["full"],
                       "partial": coverage["partial_ends_early"],
                       "missing": coverage["missing"],
                       "missing_pct": coverage["missing_pct"]}}

    # 1) full window + collect daily returns for bootstrap
    full, res_full = run_case("full", args.start, args.end)
    suite["full_window"] = full
    rets = [r for _, r in res_full["daily_rets"]]
    # 2) block bootstrap
    suite["block_bootstrap"] = block_bootstrap(rets)
    # 3) non-overlapping sub-windows (yearly)
    subs = []
    y0, y1 = int(args.start[:4]), int(args.end[:4])
    for y in range(y0, y1 + 1):
        ws = max(args.start, f"{y}-01-01")
        we = min(args.end, f"{y}-12-31")
        if ws < we:
            case, _ = run_case(f"year-{y}", ws, we)
            subs.append(case)
    suite["sub_windows"] = subs
    # 4) stresses
    stresses = []
    for label, over in (
        ("delay-1d", {"delay": 1}),
        ("costs-1.5x", {"half_spread_bps": 3.75, "slippage_bps": 1.5,
                        "commission_bps": 0.75}),
        ("costs-2x", {"half_spread_bps": 5.0, "slippage_bps": 2.0,
                      "commission_bps": 1.0}),
        ("borrow-2x", {"borrow_fee_annual": 0.01}),
        ("buffered", {"buffered": True, "hold_buffer": 2 * args.basket}),
        ("weekly-rebalance", {"rebalance_every": 5}),
    ):
        case, _ = run_case(label, args.start, args.end, **over)
        stresses.append(case)
    suite["stresses"] = stresses
    # 5) implementability
    suite["implementability"] = [
        implementability(float(a), args.gross, args.basket)
        for a in args.accounts.split(",")
    ]

    text = json.dumps(suite, indent=1, default=str)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
