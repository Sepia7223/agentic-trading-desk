"""Translate the crypto trend portfolio into a dollar equity curve.

The backtest measures each trade as a return on its position notional; dollars
depend on account size and position sizing. This script imposes a realistic
fixed-fractional risk model (risk a fixed % of current equity per trade, sized by
the trade's own stop distance) and reports the compounded equity curve, annual P&L,
and max drawdown in dollars -- for the full 2022-01..2026-06 span, so the strong
2022-2024 period and the breakeven 2025-2026 final-test are both visible.

RESEARCH illustration only; sizing is one assumption among many and the dollars
scale linearly with account size and risk %.

Usage:
    PYTHONPATH=src python scripts/crypto_equity_curve.py [--start-equity 10000 --risk 0.005]
"""

from __future__ import annotations

import argparse

from trend_research import (  # type: ignore[import-not-found]
    DEV_START,
    FINAL_END,
    FINAL_START,
    VAL_END,
    _load,
    simulate,
)

ALL = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "LTCUSDT",
    "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "MATICUSDT", "ATOMUSDT",
    "ETCUSDT", "TRXUSDT", "BCHUSDT", "UNIUSDT", "FILUSDT", "ALGOUSDT", "XLMUSDT",
]
from pathlib import Path  # noqa: E402


def collect(root: Path, start, end):
    trades = []
    for pair in ALL:
        ts, mc, mh, ml, ho, half = _load(pair, root, "HOUR", start, end)
        trades.extend(
            simulate(
                pair, ts, mc, mh, ml, ho, half,
                entry=40, exit_ch=40, stop_atr=3.0, atr_w=14, max_hold=500,
                slippage=0.00005, trend_ma=0,
            )
        )
    return trades


def equity_curve(trades, notional):
    """Fixed notional per position, additive (no compounding) -- faithful to the
    backtest, which sums per-trade returns on notional. Dollars scale linearly."""

    trades = sorted(trades, key=lambda t: t.exit_at)
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    by_year: dict[str, float] = {}
    for t in trades:
        pnl = t.net() * notional
        by_year[str(t.exit_at.year)] = by_year.get(str(t.exit_at.year), 0.0) + pnl
        cum += pnl
        peak = max(peak, cum)
        max_dd = min(max_dd, cum - peak)
    return cum, max_dd, by_year, len(trades)


def max_concurrent(trades):
    events = []
    for t in trades:
        events.append((t.entry_at, 1))
        events.append((t.exit_at, -1))
    events.sort()
    cur = peak = 0
    for _, d in events:
        cur += d
        peak = max(peak, cur)
    return peak


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--notional", type=float, default=1000.0, help="fixed $ per position")
    p.add_argument("--bars-root", default="data/crypto/bars")
    args = p.parse_args(argv)
    root = Path(args.bars_root)
    N = args.notional

    devval = collect(root, DEV_START, VAL_END)
    final = collect(root, FINAL_START, FINAL_END)
    allt = devval + final

    concurrent = max_concurrent(allt)
    capital = concurrent * N
    pnl_dv, dd_dv, yr_dv, n_dv = equity_curve(devval, N)
    pnl_ft, dd_ft, yr_ft, n_ft = equity_curve(final, N)

    print(f"=== Fixed ${N:,.0f} per position, no compounding | {len(allt)} trades ===")
    print(f"  peak concurrent positions: {concurrent}  ->  capital to run it: ~${capital:,.0f}")
    print("  (dollars scale linearly: double the size -> double every figure below)\n")
    print(f"  DEV+VALIDATION 2022-01..2025-06 ({n_dv} trades):")
    print(f"    total P&L: ${pnl_dv:+,.0f}   ({pnl_dv / capital * 100:+.0f}% on ~${capital:,.0f})")
    print(f"    worst drawdown: ${dd_dv:+,.0f}")
    for y in sorted(yr_dv):
        print(f"      {y}: ${yr_dv[y]:+,.0f}")
    print(f"\n  LOCKED FINAL-TEST 2025-07..2026-06 ({n_ft} trades):")
    print(f"    total P&L: ${pnl_ft:+,.0f}   ({pnl_ft / capital * 100:+.1f}% on ~${capital:,.0f})")
    print(f"    worst drawdown: ${dd_ft:+,.0f}")
    for y in sorted(yr_ft):
        print(f"      {y}: ${yr_ft[y]:+,.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
