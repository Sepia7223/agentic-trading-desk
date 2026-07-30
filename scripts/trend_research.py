"""Trend/breakout research harness with full acceptance evidence (configurable TF).

Donchian channel breakout (Turtle-style): enter on an N-bar breakout, protective
ATR stop, let winners run via an M-bar opposite-channel trailing exit. Trend is the
net-positive family found in prior work; this harness tests whether a faster
timeframe (MINUTE_15 / HOUR) reaches 3-8 trades/weekday while staying net-positive
with realized R:R > 1 (win-rate floor dropped under decision v2).

Produces every acceptance metric (frequency, net, PF, avg/largest win & loss, R:R,
MAE/MFE, stop metrics, drawdown, by-pair/month/regime, cost-stress) and evaluates
the v2 gates. RESEARCH ONLY; offline; dev+validation unless --final-test. Bidirectional.

Usage:
    PYTHONPATH=src python scripts/trend_research.py --timeframe MINUTE_15 \
        --entry 20 --exit 10 --stop-atr 2.0 [--pairs ...] [--out r.json]
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from trading_desk.strategy.validation_cli import PAIR_EPICS
from trading_desk.strategy.validation_runner import load_bars

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "EURJPY"]
DEV_START = datetime(2022, 1, 1, tzinfo=UTC)
VAL_END = datetime(2025, 6, 30, 23, 59, 59, tzinfo=UTC)
FINAL_START = datetime(2025, 7, 1, tzinfo=UTC)
FINAL_END = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)
BARS_PER_DAY = {"MINUTE_5": 288, "MINUTE_15": 96, "HOUR": 24}


@dataclass
class Trade:
    pair: str
    direction: int
    entry_at: datetime
    exit_at: datetime
    gross: float
    exec_cost: float
    mae: float
    mfe: float
    exit_reason: str
    regime: str
    month: str
    held_bars: int
    stop_frac: float = 0.0  # protective stop distance as a fraction of entry price

    def net(self, cost_mult: float = 1.0) -> float:
        return self.gross - cost_mult * self.exec_cost


def _load(pair: str, root: Path, tf: str, start: datetime, end: datetime):
    epic = PAIR_EPICS[pair][0] if pair in PAIR_EPICS else pair
    ts, mc, mh, ml, ho, half = [], [], [], [], [], []
    for b in load_bars(root / f"{pair}_{tf}.csv", epic=epic):
        if start <= b.timestamp <= end:
            mo = (b.open_bid + b.open_ask) / 2
            ts.append(b.timestamp)
            mc.append((b.close_bid + b.close_ask) / 2)
            mh.append((b.high_bid + b.high_ask) / 2)
            ml.append((b.low_bid + b.low_ask) / 2)
            ho.append(mo)
            half.append((b.open_ask - b.open_bid) / 2 / mo)
    return ts, mc, mh, ml, ho, half


def _atr(mh, ml, mc, w):
    n = len(mc)
    tr = [0.0] * n
    for i in range(1, n):
        tr[i] = max(mh[i] - ml[i], abs(mh[i] - mc[i - 1]), abs(ml[i] - mc[i - 1]))
    atr = [0.0] * n
    run = 0.0
    for i in range(n):
        run += tr[i]
        if i >= w:
            run -= tr[i - w]
        if i >= w:
            atr[i] = run / w
    return atr


def simulate(
    pair, ts, mc, mh, ml, ho, half, *, entry, exit_ch, stop_atr, atr_w, max_hold,
    slippage, trend_ma=0,
):
    n = len(mc)
    atr = _atr(mh, ml, mc, atr_w)
    slow = 200
    trades = []
    i = max(entry, atr_w, slow, trend_ma)
    in_pos = 0
    e_i = 0
    e_mid = 0.0
    stop_px = 0.0
    mae = mfe = 0.0
    regime = "RANGE"
    while i < n - 1:
        if in_pos == 0:
            hi = max(mh[i - entry : i])
            lo = min(ml[i - entry : i])
            direction = 0
            if mc[i] > hi:
                direction = 1
            elif mc[i] < lo:
                direction = -1
            # trend filter: only trade breakouts aligned with the slow MA
            if direction != 0 and trend_ma > 0:
                ma = sum(mc[i - trend_ma : i]) / trend_ma
                if (direction == 1 and mc[i] < ma) or (direction == -1 and mc[i] > ma):
                    direction = 0
            if direction != 0 and atr[i] > 0:
                fill = i + 1
                in_pos = direction
                e_i = fill
                e_mid = ho[fill]
                stop_px = e_mid - direction * stop_atr * atr[i]
                e_stop_frac = stop_atr * atr[i] / e_mid
                mae = mfe = 0.0
                fast = sum(mc[i - 20 : i]) / 20
                slw = sum(mc[i - slow : i]) / slow
                band = abs(fast - slw) / slw
                regime = "RANGE" if band < 0.001 else ("TREND_UP" if fast > slw else "TREND_DOWN")
            i += 1
            continue
        # in position: update trailing exit channel + protective stop
        favor = (mh[i] - e_mid) if in_pos == 1 else (e_mid - ml[i])
        against = (e_mid - ml[i]) if in_pos == 1 else (mh[i] - e_mid)
        mfe = max(mfe, favor / e_mid)
        mae = min(mae, -against / e_mid)
        exit_lo = min(ml[i - exit_ch : i]) if in_pos == 1 else None
        exit_hi = max(mh[i - exit_ch : i]) if in_pos == -1 else None
        stop_hit = (ml[i] <= stop_px) if in_pos == 1 else (mh[i] >= stop_px)
        chan_hit = (mc[i] < exit_lo) if in_pos == 1 else (mc[i] > exit_hi)
        timeout = (i - e_i) >= max_hold
        if stop_hit or chan_hit or timeout:
            fill = i + 1
            x_mid = ho[fill]
            gross = in_pos * (x_mid - e_mid) / e_mid
            cost = half[e_i] + half[fill] + 2 * slippage
            reason = "stop" if stop_hit else ("channel" if chan_hit else "time")
            trades.append(
                Trade(
                    pair=pair,
                    direction=in_pos,
                    entry_at=ts[e_i],
                    exit_at=ts[fill],
                    gross=gross,
                    exec_cost=cost,
                    mae=mae,
                    mfe=mfe,
                    exit_reason=reason,
                    regime=regime,
                    month=f"{ts[e_i].year}-{ts[e_i].month:02d}",
                    held_bars=fill - e_i,
                    stop_frac=e_stop_frac,
                )
            )
            in_pos = 0
            i = fill + 1
            continue
        i += 1
    return trades


def _weekdays(start, end, all_days=False):
    days = (end.date() - start.date()).days + 1
    if all_days:
        return days
    return sum(1 for k in range(days) if (start.date() + dt.timedelta(days=k)).weekday() < 5)


def _wd_month(m):
    y, mo = (int(x) for x in m.split("-"))
    nd = calendar.monthrange(y, mo)[1]
    return sum(1 for d in range(1, nd + 1) if datetime(y, mo, d).weekday() < 5)


def _stats(trades, weekdays, cost_mult=1.0):
    n = len(trades)
    if n == 0:
        return {"trades": 0}
    nets = [t.net(cost_mult) for t in trades]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x < 0]
    gp = sum(wins)
    gl = -sum(losses)
    net = sum(nets)
    aw = gp / len(wins) if wins else 0.0
    al = gl / len(losses) if losses else 0.0
    cum = peak = mdd = 0.0
    for x in nets:
        cum += x
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    stopped = sum(1 for t in trades if t.exit_reason == "stop")
    return {
        "trades": n,
        "trades_per_weekday": round(n / weekdays, 3) if weekdays else None,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": round(len(wins) / n, 4),
        "gross_profit": round(gp, 6),
        "gross_loss": round(gl, 6),
        "net_profit": round(net, 6),
        "profit_factor": round(gp / gl, 3) if gl else None,
        "avg_win": round(aw, 7),
        "avg_loss": round(al, 7),
        "reward_risk_realized": round(aw / al, 3) if al else None,
        "expectancy": round(net / n, 7),
        "largest_win": round(max(nets), 6),
        "largest_loss": round(min(nets), 6),
        "max_drawdown": round(mdd, 6),
        "avg_mae": round(sum(t.mae for t in trades) / n, 7),
        "avg_mfe": round(sum(t.mfe for t in trades) / n, 7),
        "stop_exit_count": stopped,
        "pct_stopped": round(stopped / n, 4),
    }


def _gates(st):
    if not st.get("trades"):
        return {"pass": False, "reasons": ["no trades"]}
    r = []
    tpw = st.get("trades_per_weekday") or 0
    if tpw < 3:
        r.append(f"freq {tpw}<3")
    if tpw > 8:
        r.append(f"freq {tpw}>8")
    if st["net_profit"] <= 0:
        r.append("net<=0")
    rr = st.get("reward_risk_realized")
    if rr is None or rr <= 1.0:
        r.append(f"RR {rr}<=1")
    if st["expectancy"] <= 0:
        r.append("exp<=0")
    return {"pass": len(r) == 0, "reasons": r}


def analyse(pair, trades, weekdays):
    st = _stats(trades, weekdays)
    by_regime = {
        rg: _stats([t for t in trades if t.regime == rg], weekdays)
        for rg in ("TREND_UP", "TREND_DOWN", "RANGE")
        if any(t.regime == rg for t in trades)
    }
    by_month = {
        m: _stats([t for t in trades if t.month == m], max(_wd_month(m), 1))
        for m in sorted({t.month for t in trades})
    }
    cost_stress = {f"{m:.2f}x": _stats(trades, weekdays, m) for m in (1.25, 1.5, 2.0)}
    return {
        "pair": pair,
        "gates": _gates(st),
        "summary": st,
        "by_regime": by_regime,
        "by_month": by_month,
        "cost_stress": cost_stress,
    }


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--pairs", default=",".join(PAIRS))
    p.add_argument("--timeframe", default="MINUTE_15", choices=("MINUTE_5", "MINUTE_15", "HOUR"))
    p.add_argument("--entry", type=int, default=20)
    p.add_argument("--exit", type=int, default=10)
    p.add_argument("--stop-atr", type=float, default=2.0)
    p.add_argument("--atr-window", type=int, default=14)
    p.add_argument("--trend-ma", type=int, default=0, help="0=off; require price on MA's side")
    p.add_argument("--max-hold", type=int, default=500)
    p.add_argument("--slippage", type=float, default=0.00005)
    p.add_argument("--final-test", action="store_true")
    p.add_argument("--all-days", action="store_true", help="count all calendar days (24/7 crypto)")
    p.add_argument("--bars-root", default="data/validation/bars")
    p.add_argument("--out", default=None)
    args = p.parse_args(argv)
    start, end = (FINAL_START, FINAL_END) if args.final_test else (DEV_START, VAL_END)
    weekdays = _weekdays(start, end, args.all_days)
    root = Path(args.bars_root)
    pairs = [x.strip() for x in args.pairs.split(",") if x.strip()]
    per_pair = []
    all_trades = []
    for pair in pairs:
        ts, mc, mh, ml, ho, half = _load(pair, root, args.timeframe, start, end)
        trades = simulate(
            pair, ts, mc, mh, ml, ho, half,
            entry=args.entry, exit_ch=args.exit, stop_atr=args.stop_atr,
            atr_w=args.atr_window, max_hold=args.max_hold, slippage=args.slippage,
            trend_ma=args.trend_ma,
        )
        all_trades.extend(trades)
        per_pair.append(analyse(pair, trades, weekdays))
    passing = [r["pair"] for r in per_pair if r["gates"]["pass"]]
    report = {
        "strategy": "trend-breakout-v1",
        "timeframe": args.timeframe,
        "window": "final-test" if args.final_test else "dev+validation",
        "params": {"entry": args.entry, "exit": args.exit, "stop_atr": args.stop_atr,
                   "max_hold": args.max_hold, "slippage": args.slippage},
        "weekdays": weekdays,
        "aggregate": _stats(all_trades, weekdays),
        "pairs_passing": passing,
        "pairs_passing_count": len(passing),
        "standard_met": len(passing) >= 4,
        "per_pair": per_pair,
    }
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(
        f"=== trend-breakout {args.timeframe} entry={args.entry} exit={args.exit} "
        f"stop={args.stop_atr} | {report['window']} ==="
    )
    for r in per_pair:
        st = r["summary"]
        if not st.get("trades"):
            print(f"  {r['pair']:7} no trades")
            continue
        g = r["gates"]
        print(
            f"  {r['pair']:7} n={st['trades']:5} freq={st['trades_per_weekday']:.2f} "
            f"win={st['win_rate']:.1%} RR={st['reward_risk_realized']} "
            f"net={st['net_profit']:+.5f} exp={st['expectancy']:+.7f} PF={st['profit_factor']} "
            f"| {'PASS' if g['pass'] else 'fail:' + ';'.join(g['reasons'])}"
        )
    print(
        f">>> pairs passing v2 gates: {len(passing)}/{len(pairs)} {passing} "
        f"| MET(>=4): {report['standard_met']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
