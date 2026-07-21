"""Market-neutral cross-sectional mean-reversion on equities (v3 consistency).

Daily short-term reversal: rank the universe by past-`lookback`-day return; go LONG
the biggest losers, SHORT the biggest winners, equal-weight -> dollar-neutral (no
market beta), so the big directional drawdowns that make trend lumpy cannot happen.
Rebalanced every `hold` days; equity compounds; costs charged on turnover. Reports
the v3 metrics: return, max drawdown, % months positive, Sharpe, worst day, ruin
check, and trades/day.

Market-neutral at modest gross leverage cannot blow a $1,000 account by construction
(daily P&L is a small, bounded spread of diversified returns).

RESEARCH ONLY. Daily adjusted-close bars. Dev+validation 2022-01..2025-06 unless
--final-test (2025-07..2026-06).

Usage:
    python scripts/cross_sectional.py --lookback 5 --basket 8 --hold 3 --gross 1.0
"""

from __future__ import annotations

import argparse
import statistics
from datetime import date
from pathlib import Path

DEV_START = date(2022, 1, 1)
VAL_END = date(2025, 6, 30)
FINAL_START = date(2025, 7, 1)
FINAL_END = date(2026, 6, 30)


def load_all(root: Path):
    series = {}
    for f in sorted(root.glob("*.csv")):
        rows = f.read_text(encoding="utf-8").splitlines()[1:]
        s = {}
        for r in rows:
            parts = r.split(",")
            s[date.fromisoformat(parts[0])] = float(parts[5])  # adjclose
        if len(s) > 200:
            series[f.stem] = s
    all_dates = sorted(set().union(*[set(s) for s in series.values()]))
    return series, all_dates


def backtest(
    series, all_dates, start, end, *, lookback, basket, hold, gross, cost_bps, momentum, skip=0
):
    dates = all_dates  # full history; lookback may reach before `start`
    syms = list(series)
    daily_ret = []  # (date, portfolio_return_after_costs)
    trades = 0
    book_long: list[str] = []
    book_short: list[str] = []
    first = next((i for i, d in enumerate(dates) if d >= start), len(dates))
    start_k = max(lookback + 1, first)
    rebal = 0
    for k in range(start_k, len(dates)):
        d = dates[k]
        if d > end:
            break
        prev = dates[k - 1]
        # daily P&L from yesterday's book applied to today's return
        if book_long or book_short:
            lr = [x for s in book_long if (x := _ret(series[s], prev, d)) is not None]
            sr = [x for s in book_short if (x := _ret(series[s], prev, d)) is not None]
            long_ret = sum(lr) / len(lr) if lr else 0.0
            short_ret = sum(sr) / len(sr) if sr else 0.0
            port = gross / 2 * (long_ret - short_ret)
        else:
            port = 0.0
        # rebalance every `hold` days
        cost = 0.0
        if rebal % hold == 0:
            ranked = []
            rank_end = dates[k - skip] if skip else d
            for s in syms:
                r = _ret(series[s], dates[k - lookback], rank_end)
                if r is not None:
                    ranked.append((r, s))
            ranked.sort()
            losers = [s for _, s in ranked[:basket]]
            winners = [s for _, s in ranked[-basket:]]
            # reversal: long losers / short winners. momentum: long winners / short losers.
            new_long, new_short = (winners, losers) if momentum else (losers, winners)
            turnover = len(set(new_long) ^ set(book_long)) + len(set(new_short) ^ set(book_short))
            trades += turnover
            cost = turnover / max(2 * basket, 1) * gross * (cost_bps / 10000.0)
            book_long, book_short = new_long, new_short
        rebal += 1  # noqa: SIM113 - counts in-window days only (start offset + break)
        daily_ret.append((d, port - cost))
    return daily_ret, trades, len(dates)


def _ret(s: dict, d0: date, d1: date):
    if d0 in s and d1 in s and s[d0] > 0:
        return s[d1] / s[d0] - 1
    return None


def metrics(daily_ret, trades, ndays, start_equity):
    if not daily_ret:
        return {"days": 0}
    equity = start_equity
    curve = []
    for d, r in daily_ret:
        equity *= 1 + r
        curve.append((d, equity))
    peak = start_equity
    max_dd = 0.0
    for _, e in curve:
        peak = max(peak, e)
        max_dd = min(max_dd, (e - peak) / peak)
    by_month = {}
    for d, e in curve:
        by_month[f"{d.year}-{d.month:02d}"] = e
    months = sorted(by_month)
    mret, pe = [], start_equity
    for m in months:
        mret.append(by_month[m] / pe - 1)
        pe = by_month[m]
    rets = [r for _, r in daily_ret]
    sharpe = 0.0
    if statistics.pstdev(rets) > 0:
        sharpe = statistics.mean(rets) / statistics.pstdev(rets) * (252**0.5)
    wins = sum(1 for r in rets if r > 0)
    trading_days = len({d for d, _ in daily_ret})
    return {
        "final_equity": round(equity, 2),
        "total_return_pct": round((equity / start_equity - 1) * 100, 1),
        "cagr_pct": round(((equity / start_equity) ** (252 / max(len(rets), 1)) - 1) * 100, 1),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "annualised_sharpe": round(sharpe, 2),
        "pct_days_positive": round(wins / len(rets) * 100, 1),
        "pct_months_positive": round(sum(1 for r in mret if r > 0) / len(months) * 100, 1),
        "worst_day_pct": round(min(rets) * 100, 2),
        "best_day_pct": round(max(rets) * 100, 2),
        "ruin": min(e for _, e in curve) <= start_equity * 0.1,
        "trades_per_day": round(trades / trading_days, 2),
        "trades_total": trades,
    }


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--lookback", type=int, default=5)
    p.add_argument("--basket", type=int, default=8)
    p.add_argument("--hold", type=int, default=3)
    p.add_argument("--gross", type=float, default=1.0, help="gross leverage (1.0=100% long+short)")
    p.add_argument("--cost-bps", type=float, default=3.0)
    p.add_argument("--momentum", action="store_true", help="long winners/short losers")
    p.add_argument("--skip", type=int, default=0, help="skip most-recent N days in ranking")
    p.add_argument("--start-equity", type=float, default=1000.0)
    p.add_argument("--final-test", action="store_true")
    p.add_argument("--full", action="store_true", help="continuous 2022-01..2026-06")
    p.add_argument("--root", default="data/stocks")
    args = p.parse_args(argv)
    if args.full:
        start, end = DEV_START, FINAL_END
    else:
        start, end = (FINAL_START, FINAL_END) if args.final_test else (DEV_START, VAL_END)
    series, all_dates = load_all(Path(args.root))
    daily_ret, trades, nd = backtest(
        series,
        all_dates,
        start,
        end,
        lookback=args.lookback,
        basket=args.basket,
        hold=args.hold,
        gross=args.gross,
        cost_bps=args.cost_bps,
        momentum=args.momentum,
        skip=args.skip,
    )
    m = metrics(daily_ret, trades, nd, args.start_equity)
    window = "FINAL-TEST" if args.final_test else "dev+val"
    print(
        f"=== X-sectional reversal | lookback={args.lookback} basket={args.basket} "
        f"hold={args.hold} gross={args.gross} | {len(series)} stocks | {window} ==="
    )
    for k, v in m.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
