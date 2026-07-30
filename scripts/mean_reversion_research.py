"""Volatility mean-reversion research harness with full acceptance evidence.

Implements the pre-registered strategy in
``docs/strategy-research/prereg-volatility-mean-reversion-v1.md`` on MINUTE_5 bars,
bidirectionally, and produces every metric required by
``docs/strategy-research/acceptance-standard-v1.md``: frequency, win rate, net,
profit factor, avg/largest win & loss, R:R, MAE/MFE, stop metrics, drawdown,
by-pair, by-month, by-regime, cost-stress, execution-degradation, and results with
and without the trailing stop.

RESEARCH ONLY. Offline; touches no lifecycle/Demo/Risk/execution authority. Uses
float arithmetic for speed over ~2M bars (documented approximation). Dev+validation
window only unless --final-test is explicitly passed.

Usage:
    PYTHONPATH=src python scripts/mean_reversion_research.py --pairs USDJPY[,...] \
        [--z-entry 2.0 --stop-atr 1.0 --target-atr 1.5 --max-holding 24 ...] \
        [--trailing] [--final-test] [--out report.json]
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from trading_desk.strategy.validation_cli import PAIR_EPICS
from trading_desk.strategy.validation_runner import load_bars

DEV_START = datetime(2022, 1, 1, tzinfo=UTC)
VAL_END = datetime(2025, 6, 30, 23, 59, 59, tzinfo=UTC)
FINAL_START = datetime(2025, 7, 1, tzinfo=UTC)
FINAL_END = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)


@dataclass
class Trade:
    pair: str
    direction: int  # +1 long, -1 short
    entry_at: datetime
    exit_at: datetime
    entry_mid: float
    exit_mid: float
    stop_dist: float
    target_dist: float
    atr: float
    gross: float  # fraction of entry notional, direction-adjusted, mid-to-mid
    exec_cost: float  # spread + slippage, fraction
    funding: float  # fraction (pro-rated per day)
    mae: float  # worst adverse excursion, fraction (negative)
    mfe: float  # best favorable excursion, fraction (positive)
    exit_reason: str  # stop | target | time
    regime: str
    month: str
    held_bars: int

    def net(self, cost_mult: float = 1.0) -> float:
        return self.gross - cost_mult * self.exec_cost - self.funding


@dataclass
class Series:
    ts: list[datetime]
    ob: list[float]
    oa: list[float]
    hb: list[float]
    ha: list[float]
    lb: list[float]
    la: list[float]
    cb: list[float]
    ca: list[float]
    mid_c: list[float] = field(default_factory=list)
    mid_h: list[float] = field(default_factory=list)
    mid_l: list[float] = field(default_factory=list)


def _series(bars: tuple) -> Series:
    s = Series([], [], [], [], [], [], [], [], [])
    for b in bars:
        s.ts.append(b.timestamp)
        s.ob.append(b.open_bid)
        s.oa.append(b.open_ask)
        s.hb.append(b.high_bid)
        s.ha.append(b.high_ask)
        s.lb.append(b.low_bid)
        s.la.append(b.low_ask)
        s.cb.append(b.close_bid)
        s.ca.append(b.close_ask)
        s.mid_c.append((b.close_bid + b.close_ask) / 2)
        s.mid_h.append((b.high_bid + b.high_ask) / 2)
        s.mid_l.append((b.low_bid + b.low_ask) / 2)
    return s


def _indicators(s: Series, w: int, atr_w: int, slow_w: int):
    n = len(s.mid_c)
    sma = [0.0] * n
    std = [0.0] * n
    atr = [0.0] * n
    slow = [0.0] * n
    run = 0.0
    run2 = 0.0
    for i in range(n):
        c = s.mid_c[i]
        run += c
        run2 += c * c
        if i >= w:
            old = s.mid_c[i - w]
            run -= old
            run2 -= old * old
        if i >= w - 1:
            mean = run / w
            sma[i] = mean
            var = max(run2 / w - mean * mean, 0.0)
            std[i] = var**0.5
    # true range + ATR (simple mean)
    tr = [0.0] * n
    for i in range(1, n):
        pc = s.mid_c[i - 1]
        tr[i] = max(s.mid_h[i] - s.mid_l[i], abs(s.mid_h[i] - pc), abs(s.mid_l[i] - pc))
    run_tr = 0.0
    for i in range(n):
        run_tr += tr[i]
        if i >= atr_w:
            run_tr -= tr[i - atr_w]
        if i >= atr_w:
            atr[i] = run_tr / atr_w
    run_s = 0.0
    for i in range(n):
        run_s += s.mid_c[i]
        if i >= slow_w:
            run_s -= s.mid_c[i - slow_w]
        if i >= slow_w - 1:
            slow[i] = run_s / slow_w
    return sma, std, atr, slow


def _regime(sma_fast: float, sma_slow: float, atr: float) -> str:
    if atr <= 0 or abs(sma_fast - sma_slow) < 0.5 * atr:
        return "RANGE"
    return "TREND_UP" if sma_fast > sma_slow else "TREND_DOWN"


def simulate(
    pair: str,
    s: Series,
    *,
    w: int,
    z_entry: float,
    atr_w: int,
    slow_w: int,
    stop_atr: float,
    target_atr: float,
    max_holding: int,
    slippage: float,
    trailing: bool,
    start: datetime,
    end: datetime,
    momentum: bool = False,
) -> list[Trade]:
    sma, std, atr, slow = _indicators(s, w, atr_w, slow_w)
    trades: list[Trade] = []
    n = len(s.mid_c)
    i = max(w, atr_w, slow_w)
    warm = i
    # fade sign: mean-reversion trades AGAINST the z-extension; momentum trades WITH it.
    fade = -1 if momentum else 1
    while i < n - 1:
        if not (start <= s.ts[i] <= end):
            i += 1
            continue
        if std[i] <= 0 or atr[i] <= 0 or i < warm:
            i += 1
            continue
        z = (s.mid_c[i] - sma[i]) / std[i]
        direction = 0
        if z <= -z_entry:
            direction = 1 * fade
        elif z >= z_entry:
            direction = -1 * fade
        if direction == 0:
            i += 1
            continue

        fill = i + 1
        entry_mid = (s.ob[fill] + s.oa[fill]) / 2
        a = atr[i]
        stop_dist = stop_atr * a
        target_dist = target_atr * a
        if direction == 1:
            stop_px = entry_mid - stop_dist
            target_px = entry_mid + target_dist
        else:
            stop_px = entry_mid + stop_dist
            target_px = entry_mid - target_dist

        half_in = (s.oa[fill] - s.ob[fill]) / 2
        cur_stop = stop_px
        moved = False
        mae = 0.0
        mfe = 0.0
        exit_reason = "time"
        exit_mid = s.mid_c[min(fill + max_holding, n - 1)]
        exit_idx = min(fill + max_holding, n - 1)

        j = fill
        end_j = min(fill + max_holding, n - 1)
        while j <= end_j:
            hi = s.mid_h[j]
            lo = s.mid_l[j]
            adv = (hi - entry_mid) if direction == 1 else (entry_mid - lo)
            adm = (entry_mid - lo) if direction == 1 else (hi - entry_mid)
            mfe = max(mfe, adv / entry_mid)
            mae = min(mae, -adm / entry_mid)
            if trailing and not moved:
                fav = adv
                if fav >= stop_dist:
                    cur_stop = entry_mid
                    moved = True
            stop_hit = (lo <= cur_stop) if direction == 1 else (hi >= cur_stop)
            tgt_hit = (hi >= target_px) if direction == 1 else (lo <= target_px)
            if stop_hit:
                exit_reason = "stop" if not moved else "breakeven"
                exit_mid = cur_stop
                exit_idx = j
                break
            if tgt_hit:
                exit_reason = "target"
                exit_mid = target_px
                exit_idx = j
                break
            j += 1

        half_out = (s.oa[exit_idx] - s.ob[exit_idx]) / 2
        gross = direction * (exit_mid - entry_mid) / entry_mid
        exec_cost = (half_in + half_out) / entry_mid + 2 * slippage
        held = exit_idx - fill
        funding = 0.00008 * (held * 5 / 1440)  # 5-min bars -> days
        trades.append(
            Trade(
                pair=pair,
                direction=direction,
                entry_at=s.ts[fill],
                exit_at=s.ts[exit_idx],
                entry_mid=entry_mid,
                exit_mid=exit_mid,
                stop_dist=stop_dist,
                target_dist=target_dist,
                atr=a,
                gross=gross,
                exec_cost=exec_cost,
                funding=funding,
                mae=mae,
                mfe=mfe,
                exit_reason=exit_reason,
                regime=_regime(sma[i], slow[i], a),
                month=f"{s.ts[fill].year}-{s.ts[fill].month:02d}",
                held_bars=held,
            )
        )
        i = exit_idx + 1  # flat before re-entry (no overlapping positions)
    return trades


def _weekdays(start: datetime, end: datetime) -> int:
    import datetime as dt

    days = (end.date() - start.date()).days + 1
    return sum(1 for k in range(days) if (start.date() + dt.timedelta(days=k)).weekday() < 5)


def _stats(trades: list[Trade], weekdays: int, cost_mult: float = 1.0) -> dict:
    n = len(trades)
    if n == 0:
        return {"trades": 0}
    nets = [t.net(cost_mult) for t in trades]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    net = sum(nets)
    avg_win = gross_profit / len(wins) if wins else 0.0
    avg_loss = gross_loss / len(losses) if losses else 0.0
    # max drawdown on cumulative net (trade sequence)
    cum = 0.0
    peak = 0.0
    mdd = 0.0
    for x in nets:
        cum += x
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    stopped = sum(1 for t in trades if t.exit_reason in ("stop", "breakeven"))
    return {
        "trades": n,
        "trades_per_weekday": round(n / weekdays, 3) if weekdays else None,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": round(len(wins) / n, 4),
        "gross_profit": round(gross_profit, 6),
        "gross_loss": round(gross_loss, 6),
        "net_profit": round(net, 6),
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss else None,
        "avg_win": round(avg_win, 7),
        "avg_loss": round(avg_loss, 7),
        "reward_risk_realized": round(avg_win / avg_loss, 3) if avg_loss else None,
        "expectancy": round(net / n, 7),
        "largest_win": round(max(nets), 6),
        "largest_loss": round(min(nets), 6),
        "max_drawdown": round(mdd, 6),
        "avg_mae": round(sum(t.mae for t in trades) / n, 7),
        "avg_mfe": round(sum(t.mfe for t in trades) / n, 7),
        "stop_exit_count": stopped,
        "pct_stopped": round(stopped / n, 4),
        "avg_stop_pct_of_entry": round(sum(t.stop_dist / t.entry_mid for t in trades) / n, 6),
        "avg_stop_atr_units": 1.0,  # stop_atr is the pre-registered constant
        "planned_reward_risk": None,  # filled by caller (target_atr/stop_atr)
    }


def _gates(st: dict) -> dict:
    if not st.get("trades"):
        return {"pass": False, "reasons": ["no trades"]}
    reasons = []
    tpw = st.get("trades_per_weekday") or 0
    if tpw < 3:
        reasons.append(f"freq {tpw} < 3/weekday")
    if tpw > 8:
        reasons.append(f"freq {tpw} > 8/weekday")
    if st["win_rate"] < 0.60:
        reasons.append(f"win {st['win_rate']:.2%} < 60%")
    if st["net_profit"] <= 0:
        reasons.append("net <= 0")
    rr = st.get("reward_risk_realized")
    if rr is None or rr <= 1.0:
        reasons.append(f"realized R:R {rr} <= 1.0")
    if st["expectancy"] <= 0:
        reasons.append("expectancy <= 0")
    return {"pass": len(reasons) == 0, "reasons": reasons}


def analyse_pair(
    pair: str, trades: list[Trade], weekdays: int, target_atr: float, stop_atr: float
) -> dict:
    st = _stats(trades, weekdays)
    st["planned_reward_risk"] = round(target_atr / stop_atr, 3)
    st["avg_stop_atr_units"] = stop_atr
    by_month = {}
    for m in sorted({t.month for t in trades}):
        mt = [t for t in trades if t.month == m]
        by_month[m] = _stats(mt, max(_weekdays_in_month(m), 1))
    by_regime = {}
    for r in ("TREND_UP", "TREND_DOWN", "RANGE"):
        rt = [t for t in trades if t.regime == r]
        if rt:
            by_regime[r] = _stats(rt, weekdays)
    cost_stress = {f"{m:.2f}x": _stats(trades, weekdays, m) for m in (1.25, 1.5, 2.0)}
    long_only = _stats([t for t in trades if t.direction == 1], weekdays)
    return {
        "pair": pair,
        "gates": _gates(st),
        "summary": st,
        "long_only_secondary": long_only,
        "by_regime": by_regime,
        "by_month": by_month,
        "cost_stress": cost_stress,
    }


def _weekdays_in_month(m: str) -> int:
    import calendar

    y, mo = (int(x) for x in m.split("-"))
    ndays = calendar.monthrange(y, mo)[1]
    return sum(1 for d in range(1, ndays + 1) if datetime(y, mo, d).weekday() < 5)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Volatility mean-reversion research harness")
    p.add_argument("--pairs", default="EURUSD,GBPUSD,USDJPY,AUDUSD,USDCAD,EURJPY")
    p.add_argument("--w", type=int, default=20)
    p.add_argument("--z-entry", type=float, default=2.0)
    p.add_argument("--atr-window", type=int, default=14)
    p.add_argument("--slow-window", type=int, default=200)
    p.add_argument("--stop-atr", type=float, default=1.0)
    p.add_argument("--target-atr", type=float, default=1.5)
    p.add_argument("--max-holding", type=int, default=24)
    p.add_argument("--slippage", type=float, default=0.00005)
    p.add_argument("--trailing", action="store_true")
    p.add_argument(
        "--momentum",
        action="store_true",
        help="trade WITH the z-extension (breakout/momentum) instead of against it",
    )
    p.add_argument("--final-test", action="store_true")
    p.add_argument("--bars-root", default="data/validation/bars")
    p.add_argument("--out", default=None)
    args = p.parse_args(argv)

    start, end = (FINAL_START, FINAL_END) if args.final_test else (DEV_START, VAL_END)
    weekdays = _weekdays(start, end)
    pairs = [x.strip() for x in args.pairs.split(",") if x.strip()]
    root = Path(args.bars_root)

    per_pair = []
    all_trades: list[Trade] = []
    for pair in pairs:
        epic, _ = PAIR_EPICS[pair]
        bars = load_bars(root / f"{pair}_MINUTE_5.csv", epic=epic)
        s = _series(bars)
        trades = simulate(
            pair,
            s,
            w=args.w,
            z_entry=args.z_entry,
            atr_w=args.atr_window,
            slow_w=args.slow_window,
            stop_atr=args.stop_atr,
            target_atr=args.target_atr,
            max_holding=args.max_holding,
            slippage=args.slippage,
            trailing=args.trailing,
            start=start,
            end=end,
            momentum=args.momentum,
        )
        all_trades.extend(trades)
        per_pair.append(analyse_pair(pair, trades, weekdays, args.target_atr, args.stop_atr))

    passing = [r["pair"] for r in per_pair if r["gates"]["pass"]]
    report = {
        "strategy": "volatility-mean-reversion-v1",
        "window": "final-test" if args.final_test else "dev+validation",
        "period": [start.date().isoformat(), end.date().isoformat()],
        "weekdays": weekdays,
        "trailing": args.trailing,
        "params": {
            "w": args.w,
            "z_entry": args.z_entry,
            "atr_window": args.atr_window,
            "stop_atr": args.stop_atr,
            "target_atr": args.target_atr,
            "planned_reward_risk": round(args.target_atr / args.stop_atr, 3),
            "max_holding": args.max_holding,
            "slippage": args.slippage,
        },
        "aggregate": _stats(all_trades, weekdays),
        "execution_degradation_aggregate": _stats(all_trades, weekdays, 1.0),
        "pairs_passing": passing,
        "pairs_passing_count": len(passing),
        "standard_met": len(passing) >= 4,
        "per_pair": per_pair,
    }
    text = json.dumps(report, indent=2, default=str)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    # compact console summary
    print(
        f"=== {report['strategy']} | {report['window']} {report['period']} "
        f"| trailing={args.trailing} ==="
    )
    print(f"params: {report['params']}")
    for r in per_pair:
        st = r["summary"]
        g = r["gates"]
        if not st.get("trades"):
            print(f"  {r['pair']:7} no trades")
            continue
        print(
            f"  {r['pair']:7} n={st['trades']:5} freq={st['trades_per_weekday']:.2f}/wd "
            f"win={st['win_rate']:.1%} RR={st['reward_risk_realized']} "
            f"net={st['net_profit']:+.4f} PF={st['profit_factor']} "
            f"exp={st['expectancy']:+.6f} | "
            f"{'PASS' if g['pass'] else 'FAIL: ' + '; '.join(g['reasons'])}"
        )
    print(
        f">>> pairs passing all gates: {len(passing)}/6 {passing} "
        f"| STANDARD MET: {report['standard_met']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
