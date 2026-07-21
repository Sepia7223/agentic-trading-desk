"""v3 consistency search: mean-reversion with compounding + strict risk sizing.

Targets decision-v3 (consistency, minimal losses, compounding, no ruin from $1,000).
Mean-reversion (fade a z-extension, take profit on reversion to the mean, tight ATR
stop) is the consistent-profile candidate. Position sizing is fixed-fractional: each
trade risks a small % of CURRENT equity (so a stop-out costs a bounded, small amount
and the account cannot be blown), with a portfolio heat cap on concurrent risk.
Equity compounds. Reports the metrics v3 actually cares about: final equity from
$1,000, max drawdown, % of months profitable, longest losing streak, worst single
loss, and a ruin check.

RESEARCH ONLY. Reuses trend_research._load/_atr; crypto data, dev+validation window
unless --final-test.

Usage:
    PYTHONPATH="src;scripts" python scripts/consistency_search.py --timeframe HOUR \
        --z-entry 2.0 --stop-atr 1.5 --risk 0.005 --max-heat 0.06
"""

from __future__ import annotations

import argparse
import heapq
import statistics
from pathlib import Path

from trend_research import (  # type: ignore[import-not-found]
    DEV_START,
    FINAL_END,
    FINAL_START,
    VAL_END,
    _atr,
    _load,
)

ALL = [
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "LTCUSDT",
    "DOGEUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "DOTUSDT",
    "MATICUSDT",
    "ATOMUSDT",
    "ETCUSDT",
    "TRXUSDT",
    "BCHUSDT",
    "UNIUSDT",
    "FILUSDT",
    "ALGOUSDT",
    "XLMUSDT",
]


def mr_trades(pair, ts, mc, mh, ml, ho, half, *, w, z_entry, z_stop, stop_atr, max_hold, slippage):
    """Return (entry_at, exit_at, net_return_on_notional, stop_frac) per trade."""
    n = len(mc)
    atr = _atr(mh, ml, mc, w if w else 14)
    # rolling mean/std of close over w
    out = []
    run = run2 = 0.0
    sma = [0.0] * n
    std = [0.0] * n
    for i in range(n):
        run += mc[i]
        run2 += mc[i] * mc[i]
        if i >= w:
            run -= mc[i - w]
            run2 -= mc[i - w] * mc[i - w]
        if i >= w - 1:
            m = run / w
            sma[i] = m
            std[i] = max(run2 / w - m * m, 0.0) ** 0.5
    i = max(w, 14)
    in_pos = 0
    e_i = 0
    e_mid = 0.0
    stop_px = 0.0
    while i < n - 1:
        if in_pos == 0:
            if std[i] > 0 and atr[i] > 0:
                z = (mc[i] - sma[i]) / std[i]
                d = 1 if z <= -z_entry else (-1 if z >= z_entry else 0)
                if d != 0:
                    fill = i + 1
                    in_pos = d
                    e_i = fill
                    e_mid = ho[fill]
                    stop_px = e_mid - d * stop_atr * atr[i]
                    e_sf = stop_atr * atr[i] / e_mid
            i += 1
            continue
        z = (mc[i] - sma[i]) / std[i] if std[i] > 0 else 0.0
        reverted = (in_pos == 1 and z >= 0) or (in_pos == -1 and z <= 0)
        stop_hit = (ml[i] <= stop_px) if in_pos == 1 else (mh[i] >= stop_px)
        timeout = (i - e_i) >= max_hold
        if stop_hit or reverted or timeout:
            fill = i + 1
            x = stop_px if stop_hit else ho[fill]
            gross = in_pos * (x - e_mid) / e_mid
            cost = half[e_i] + half[fill] + 2 * slippage
            out.append((ts[e_i], ts[fill], gross - cost, e_sf))
            in_pos = 0
            i = fill + 1
            continue
        i += 1
    return out


def compound(trades, start_equity, risk, max_heat):
    """Compounding fixed-fractional risk with a portfolio heat cap. Returns curve."""
    trades = sorted(trades, key=lambda t: t[0])  # by entry
    equity = start_equity
    open_risk = 0.0
    curve = []  # (time, equity)
    worst_loss = 0.0
    streak = cur_streak = 0
    results = []  # realised R multiples in exit order
    events = [(entry, "entry", net, sf, exit_) for entry, exit_, net, sf in trades]
    events.sort()
    openq: list = []  # heap of (exit_at, risk_amt, R)
    for entry, _typ, net, sf, exit_ in events:
        while openq and openq[0][0] <= entry:
            xt, ramt, R = heapq.heappop(openq)
            pnl = R * ramt
            equity += pnl
            open_risk -= ramt
            results.append(R)
            worst_loss = min(worst_loss, pnl)
            if pnl < 0:
                cur_streak += 1
                streak = max(streak, cur_streak)
            else:
                cur_streak = 0
            curve.append((xt, equity))
        # try to open
        if open_risk + risk <= max_heat:
            ramt = risk * equity
            R = net / sf if sf > 1e-9 else 0.0
            R = max(R, -1.2)
            heapq.heappush(openq, (exit_, ramt, R))
            open_risk += risk
    while openq:
        xt, ramt, R = heapq.heappop(openq)
        pnl = R * ramt
        equity += pnl
        results.append(R)
        worst_loss = min(worst_loss, pnl)
        curve.append((xt, equity))
    return equity, curve, worst_loss, streak, results


def metrics(start, equity, curve, worst_loss, streak, results):
    if not curve:
        return {"trades": 0}
    peak = start
    max_dd = 0.0
    for _, e in curve:
        peak = max(peak, e)
        max_dd = min(max_dd, (e - peak) / peak)
    # monthly
    by_month: dict[str, float] = {}
    for t, e in curve:
        by_month[f"{t.year}-{t.month:02d}"] = e  # last equity in month
    months = sorted(by_month)
    mret = []
    pe = start
    for m in months:
        mret.append(by_month[m] / pe - 1)
        pe = by_month[m]
    pos_months = sum(1 for r in mret if r > 0)
    sharpe = 0.0
    if len(mret) > 1 and statistics.pstdev(mret) > 0:
        sharpe = (statistics.mean(mret) / statistics.pstdev(mret)) * (12**0.5)
    ruin = min(e for _, e in curve) <= start * 0.1
    n = len(results)
    wins = sum(1 for r in results if r > 0)
    return {
        "trades": n,
        "final_equity": round(equity, 2),
        "total_return_pct": round((equity / start - 1) * 100, 1),
        "max_drawdown_pct": round(max_dd * 100, 1),
        "months": len(months),
        "pct_months_positive": round(pos_months / len(months) * 100, 1) if months else 0,
        "longest_losing_streak": streak,
        "worst_single_loss": round(worst_loss, 2),
        "win_rate": round(wins / n * 100, 1) if n else 0,
        "annualised_sharpe": round(sharpe, 2),
        "ruin_from_start": ruin,
    }


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--timeframe", default="HOUR", choices=("HOUR", "MINUTE_15"))
    p.add_argument("--w", type=int, default=20)
    p.add_argument("--z-entry", type=float, default=2.0)
    p.add_argument("--z-stop", type=float, default=3.5)
    p.add_argument("--stop-atr", type=float, default=1.5)
    p.add_argument("--max-hold", type=int, default=48)
    p.add_argument("--risk", type=float, default=0.005)
    p.add_argument("--max-heat", type=float, default=0.06)
    p.add_argument("--slippage", type=float, default=0.00005)
    p.add_argument("--start-equity", type=float, default=1000.0)
    p.add_argument("--final-test", action="store_true")
    p.add_argument("--bars-root", default="data/crypto/bars")
    args = p.parse_args(argv)
    start, end = (FINAL_START, FINAL_END) if args.final_test else (DEV_START, VAL_END)
    root = Path(args.bars_root)
    allt = []
    for pair in ALL:
        ts, mc, mh, ml, ho, half = _load(pair, root, args.timeframe, start, end)
        allt.extend(
            mr_trades(
                pair,
                ts,
                mc,
                mh,
                ml,
                ho,
                half,
                w=args.w,
                z_entry=args.z_entry,
                z_stop=args.z_stop,
                stop_atr=args.stop_atr,
                max_hold=args.max_hold,
                slippage=args.slippage,
            )
        )
    days = (end.date() - start.date()).days + 1
    freq = len(allt) / days
    eq, curve, worst, streak, results = compound(allt, args.start_equity, args.risk, args.max_heat)
    m = metrics(args.start_equity, eq, curve, worst, streak, results)
    m["trades_total"] = len(allt)
    m["trades_per_day_portfolio"] = round(freq, 2)
    window = "FINAL-TEST" if args.final_test else "dev+val"
    print(
        f"=== MR consistency | {args.timeframe} z={args.z_entry} stop={args.stop_atr}ATR "
        f"risk={args.risk:.1%} heat={args.max_heat:.0%} | {window} ==="
    )
    for k, v in m.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
