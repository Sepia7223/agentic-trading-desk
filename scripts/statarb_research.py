"""Statistical-arbitrage research harness with full acceptance evidence (v2).

Implements the pre-registered strategy in
``docs/strategy-research/decision-v2-relax-winrate-statarb.md``: rolling-hedge-ratio
spread z-score mean-reversion over all 15 pairwise spreads of the six pairs, on
MINUTE_5, with PnL/costs normalised by gross notional (1+|beta|) and beta clamped
for stability. Produces every metric the acceptance standard requires and evaluates
the v2 gates (win-rate floor dropped; 3-8/weekday, net>0, expectancy>0, realized
R:R>1, >=4 spreads passing, all retained).

Rolling beta/mean/std are computed in O(1) per bar from running sums, so all 15
spreads run quickly. RESEARCH ONLY; offline; no lifecycle/Demo/Risk/execution
authority. Dev+validation window unless --final-test is passed.

Usage:
    PYTHONPATH=src python scripts/statarb_research.py [--z-entry 2.0 --z-stop 3.5 \
        --w 100 --max-holding 96] [--trailing] [--final-test] [--out report.json]
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import combinations
from math import log
from pathlib import Path

from trading_desk.strategy.validation_cli import PAIR_EPICS
from trading_desk.strategy.validation_runner import load_bars

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "EURJPY"]
DEV_START = datetime(2022, 1, 1, tzinfo=UTC)
VAL_END = datetime(2025, 6, 30, 23, 59, 59, tzinfo=UTC)
FINAL_START = datetime(2025, 7, 1, tzinfo=UTC)
FINAL_END = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)
BETA_LO, BETA_HI = 0.2, 5.0


@dataclass
class Trade:
    spread: str
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
    beta: float

    def net(self, cost_mult: float = 1.0) -> float:
        return self.gross - cost_mult * self.exec_cost


def _load(pair: str, root: Path, start: datetime, end: datetime) -> dict:
    epic, _ = PAIR_EPICS[pair]
    out = {}
    for b in load_bars(root / f"{pair}_MINUTE_5.csv", epic=epic):
        if start <= b.timestamp <= end:
            mid_o = (b.open_bid + b.open_ask) / 2
            out[b.timestamp] = (
                (b.close_bid + b.close_ask) / 2,  # mid close
                mid_o,  # mid open
                (b.open_ask - b.open_bid) / 2 / mid_o,  # half-spread fraction
            )
    return out


def _regime(a_close: list[float], i: int, w: int, slow: int) -> str:
    if i < slow:
        return "RANGE"
    fast = sum(a_close[i - w : i]) / w
    slw = sum(a_close[i - slow : i]) / slow
    band = abs(fast - slw) / slw
    if band < 0.001:
        return "RANGE"
    return "TREND_UP" if fast > slw else "TREND_DOWN"


def simulate_spread(
    a: str,
    b: str,
    da: dict,
    db: dict,
    *,
    w: int,
    z_entry: float,
    z_stop: float,
    max_holding: int,
    slippage: float,
    trailing: bool,
) -> list[Trade]:
    ts = sorted(set(da) & set(db))
    n = len(ts)
    if n < w + 10:
        return []
    la = [log(da[t][0]) for t in ts]
    lb = [log(db[t][0]) for t in ts]
    a_close = [da[t][0] for t in ts]
    slow = 200

    # running sums over trailing window [i-w, i)
    sa = sb = saa = sab = sbb = 0.0

    def push(k: float, m: float, sign: int):
        nonlocal sa, sb, saa, sab, sbb
        sa += sign * k
        sb += sign * m
        saa += sign * k * k
        sab += sign * k * m
        sbb += sign * m * m

    for k in range(w):
        push(la[k], lb[k], +1)

    trades: list[Trade] = []
    in_pos = 0
    entry_i = 0
    entry_ls = 0.0
    entry_beta = 1.0
    entry_half = 0.0
    cur_stop_z = z_stop
    mae = mfe = 0.0

    for i in range(w, n - 1):
        abar = sa / w
        bbar = sb / w
        var_b = max(sbb / w - bbar * bbar, 1e-18)
        cov = sab / w - abar * bbar
        var_a = max(saa / w - abar * abar, 1e-18)
        beta = min(max(cov / var_b, BETA_LO), BETA_HI)
        mean_s = abar - beta * bbar
        var_s = max(var_a - 2 * beta * cov + beta * beta * var_b, 1e-18)
        std_s = var_s**0.5
        cur_ls = la[i] - beta * lb[i]
        z = (cur_ls - mean_s) / std_s

        if in_pos == 0:
            if z <= -z_entry or z >= z_entry:
                in_pos = 1 if z <= -z_entry else -1
                fill = i + 1
                entry_i = fill
                entry_beta = beta
                entry_ls = la[fill] - beta * lb[fill]
                entry_half = da[ts[fill]][2] + beta * db[ts[fill]][2]
                cur_stop_z = z_stop
                mae = mfe = 0.0
                regime = _regime(a_close, i, w, slow)
        else:
            cur_ls_pos = la[i] - entry_beta * lb[i]
            norm = 1 + abs(entry_beta)
            pnl = in_pos * (cur_ls_pos - entry_ls) / norm
            mfe = max(mfe, pnl)
            mae = min(mae, pnl)
            if trailing and abs(z) <= z_entry / 2:
                cur_stop_z = min(cur_stop_z, z_entry)  # tighten toward entry band
            reverted = (in_pos == 1 and z >= 0) or (in_pos == -1 and z <= 0)
            stopped = abs(z) >= cur_stop_z
            timeout = (i - entry_i) >= max_holding
            if reverted or stopped or timeout:
                norm = 1 + abs(entry_beta)
                out_half = da[ts[i]][2] + entry_beta * db[ts[i]][2]
                exec_cost = (entry_half + out_half) / norm + 2 * slippage
                trades.append(
                    Trade(
                        spread=f"{a}-{b}",
                        direction=in_pos,
                        entry_at=ts[entry_i],
                        exit_at=ts[i],
                        gross=in_pos * (cur_ls_pos - entry_ls) / norm,
                        exec_cost=exec_cost,
                        mae=mae,
                        mfe=mfe,
                        exit_reason="revert" if reverted else ("stop" if stopped else "time"),
                        regime=regime,
                        month=f"{ts[entry_i].year}-{ts[entry_i].month:02d}",
                        held_bars=i - entry_i,
                        beta=entry_beta,
                    )
                )
                in_pos = 0

        push(la[i - w], lb[i - w], -1)
        push(la[i], lb[i], +1)
    return trades


def _weekdays(start: datetime, end: datetime) -> int:
    days = (end.date() - start.date()).days + 1
    return sum(1 for k in range(days) if (start.date() + dt.timedelta(days=k)).weekday() < 5)


def _weekdays_in_month(m: str) -> int:
    y, mo = (int(x) for x in m.split("-"))
    nd = calendar.monthrange(y, mo)[1]
    return sum(1 for d in range(1, nd + 1) if datetime(y, mo, d).weekday() < 5)


def _stats(trades: list[Trade], weekdays: int, cost_mult: float = 1.0) -> dict:
    n = len(trades)
    if n == 0:
        return {"trades": 0}
    nets = [t.net(cost_mult) for t in trades]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x < 0]
    gp = sum(wins)
    gl = -sum(losses)
    net = sum(nets)
    avg_win = gp / len(wins) if wins else 0.0
    avg_loss = gl / len(losses) if losses else 0.0
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
        "avg_beta": round(sum(t.beta for t in trades) / n, 3),
    }


def _gates(st: dict) -> dict:
    """v2 gates: win-rate floor DROPPED; frequency, net, expectancy, R:R retained."""
    if not st.get("trades"):
        return {"pass": False, "reasons": ["no trades"]}
    reasons = []
    tpw = st.get("trades_per_weekday") or 0
    if tpw < 3:
        reasons.append(f"freq {tpw} < 3/weekday")
    if tpw > 8:
        reasons.append(f"freq {tpw} > 8/weekday")
    if st["net_profit"] <= 0:
        reasons.append("net <= 0")
    rr = st.get("reward_risk_realized")
    if rr is None or rr <= 1.0:
        reasons.append(f"realized R:R {rr} <= 1.0")
    if st["expectancy"] <= 0:
        reasons.append("expectancy <= 0")
    return {"pass": len(reasons) == 0, "reasons": reasons}


def analyse(spread: str, trades: list[Trade], weekdays: int) -> dict:
    st = _stats(trades, weekdays)
    by_month = {
        m: _stats([t for t in trades if t.month == m], max(_weekdays_in_month(m), 1))
        for m in sorted({t.month for t in trades})
    }
    by_regime = {
        r: _stats([t for t in trades if t.regime == r], weekdays)
        for r in ("TREND_UP", "TREND_DOWN", "RANGE")
        if any(t.regime == r for t in trades)
    }
    cost_stress = {f"{m:.2f}x": _stats(trades, weekdays, m) for m in (1.25, 1.5, 2.0)}
    return {
        "spread": spread,
        "gates": _gates(st),
        "summary": st,
        "by_regime": by_regime,
        "by_month": by_month,
        "cost_stress": cost_stress,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Statistical-arbitrage research harness")
    p.add_argument("--w", type=int, default=100)
    p.add_argument("--z-entry", type=float, default=2.0)
    p.add_argument("--z-stop", type=float, default=3.5)
    p.add_argument("--max-holding", type=int, default=96)
    p.add_argument("--slippage", type=float, default=0.00005)
    p.add_argument("--trailing", action="store_true")
    p.add_argument("--final-test", action="store_true")
    p.add_argument("--bars-root", default="data/validation/bars")
    p.add_argument("--out", default=None)
    args = p.parse_args(argv)

    start, end = (FINAL_START, FINAL_END) if args.final_test else (DEV_START, VAL_END)
    weekdays = _weekdays(start, end)
    root = Path(args.bars_root)
    mids = {pair: _load(pair, root, start, end) for pair in PAIRS}

    per_spread = []
    all_trades: list[Trade] = []
    for a, b in combinations(PAIRS, 2):
        trades = simulate_spread(
            a,
            b,
            mids[a],
            mids[b],
            w=args.w,
            z_entry=args.z_entry,
            z_stop=args.z_stop,
            max_holding=args.max_holding,
            slippage=args.slippage,
            trailing=args.trailing,
        )
        all_trades.extend(trades)
        per_spread.append(analyse(f"{a}-{b}", trades, weekdays))

    passing = [r["spread"] for r in per_spread if r["gates"]["pass"]]
    report = {
        "strategy": "statistical-arbitrage-v1",
        "window": "final-test" if args.final_test else "dev+validation",
        "period": [start.date().isoformat(), end.date().isoformat()],
        "weekdays": weekdays,
        "trailing": args.trailing,
        "params": {
            "w": args.w,
            "z_entry": args.z_entry,
            "z_stop": args.z_stop,
            "max_holding": args.max_holding,
            "slippage": args.slippage,
        },
        "aggregate": _stats(all_trades, weekdays),
        "spreads_passing": passing,
        "spreads_passing_count": len(passing),
        "standard_met": len(passing) >= 4,
        "per_spread": per_spread,
    }
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(
        f"=== {report['strategy']} | {report['window']} {report['period']} "
        f"| trailing={args.trailing} | params={report['params']} ==="
    )
    for r in sorted(per_spread, key=lambda x: -(x["summary"].get("net_profit") or -9)):
        st = r["summary"]
        if not st.get("trades"):
            print(f"  {r['spread']:15} no trades")
            continue
        g = r["gates"]
        print(
            f"  {r['spread']:15} n={st['trades']:5} freq={st['trades_per_weekday']:.2f} "
            f"win={st['win_rate']:.1%} RR={st['reward_risk_realized']} "
            f"net={st['net_profit']:+.5f} exp={st['expectancy']:+.7f} PF={st['profit_factor']} "
            f"| {'PASS' if g['pass'] else 'fail: ' + ';'.join(g['reasons'])}"
        )
    print(
        f">>> spreads passing v2 gates: {len(passing)}/15 {passing} "
        f"| STANDARD MET (>=4): {report['standard_met']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
