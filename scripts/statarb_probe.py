"""Quick statistical-arbitrage feasibility probe (research, not full evidence).

Forms a rolling-hedge-ratio spread between two correlated FX pairs, trades its
z-score mean-reversion, and reports win rate / realized R:R / net after two-leg
costs. Purpose: decide whether cointegration relative-value is worth a full
acceptance-grade build, given single-pair directional strategies proved unable to
clear the 60%-win + R:R>1 bar.

RESEARCH ONLY. MINUTE_5, dev+validation window. Costs = half-spread + slippage on
BOTH legs, entry and exit (a spread round-trip crosses four half-spreads).

Usage:
    PYTHONPATH=src python scripts/statarb_probe.py --a EURUSD --b GBPUSD
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from math import log
from pathlib import Path

from trading_desk.strategy.validation_cli import PAIR_EPICS
from trading_desk.strategy.validation_runner import load_bars

DEV_START = datetime(2022, 1, 1, tzinfo=UTC)
VAL_END = datetime(2025, 6, 30, 23, 59, 59, tzinfo=UTC)


def _load_mid(pair: str, root: Path) -> dict:
    epic, _ = PAIR_EPICS[pair]
    out = {}
    for b in load_bars(root / f"{pair}_MINUTE_5.csv", epic=epic):
        if DEV_START <= b.timestamp <= VAL_END:
            out[b.timestamp] = (
                (b.close_bid + b.close_ask) / 2,
                (b.open_bid + b.open_ask) / 2,
                (b.open_ask - b.open_bid) / 2,  # half-spread
            )
    return out


def probe(a: str, b: str, root: Path, w: int, z_entry: float, z_stop: float, slippage: float):
    ma = _load_mid(a, root)
    mb = _load_mid(b, root)
    ts = sorted(set(ma) & set(mb))
    la = [log(ma[t][0]) for t in ts]
    lb = [log(mb[t][0]) for t in ts]
    n = len(ts)

    # rolling hedge ratio beta (cov/var) and spread z-score
    trades = []
    in_pos = 0
    entry_i = 0
    entry_spread = 0.0
    for i in range(w, n - 1):
        xa = la[i - w : i]
        xb = lb[i - w : i]
        mbar_a = sum(xa) / w
        mbar_b = sum(xb) / w
        cov = sum((xa[k] - mbar_a) * (xb[k] - mbar_b) for k in range(w)) / w
        var = sum((xb[k] - mbar_b) ** 2 for k in range(w)) / w
        beta = cov / var if var else 1.0
        spread = [la[i - w + k] - beta * lb[i - w + k] for k in range(w)]
        m = sum(spread) / w
        sd = (max(sum((x - m) ** 2 for x in spread) / w, 1e-18)) ** 0.5
        cur = la[i] - beta * lb[i]
        z = (cur - m) / sd

        if in_pos == 0:
            if z <= -z_entry:
                in_pos = 1  # long spread (long A, short B)
                entry_i = i
                entry_spread = cur
            elif z >= z_entry:
                in_pos = -1
                entry_i = i
                entry_spread = cur
        else:
            reverted = (in_pos == 1 and z >= 0) or (in_pos == -1 and z <= 0)
            stopped = abs(z) >= z_stop
            timeout = (i - entry_i) >= 96  # 8h cap
            if reverted or stopped or timeout:
                exit_spread = cur
                gross = in_pos * (exit_spread - entry_spread)  # log-spread pnl
                # two-leg cost: half-spread on A and B, entry and exit, + slippage each leg/side
                ha_in = ma[ts[entry_i]][2] / ma[ts[entry_i]][0]
                hb_in = mb[ts[entry_i]][2] / mb[ts[entry_i]][0]
                ha_out = ma[ts[i]][2] / ma[ts[i]][0]
                hb_out = mb[ts[i]][2] / mb[ts[i]][0]
                cost = ha_in + hb_in + ha_out + hb_out + 4 * slippage
                reason = "revert" if reverted else ("stop" if stopped else "time")
                trades.append((gross, cost, reason))
                in_pos = 0

    if not trades:
        return {"pair": f"{a}-{b}", "trades": 0}
    nets = [g - c for g, c, _ in trades]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x < 0]
    import datetime as dt

    days = (VAL_END.date() - DEV_START.date()).days + 1
    weekdays = sum(
        1 for k in range(days) if (DEV_START.date() + dt.timedelta(days=k)).weekday() < 5
    )
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = -sum(losses) / len(losses) if losses else 0.0
    return {
        "pair": f"{a}-{b}",
        "trades": len(trades),
        "per_weekday": round(len(trades) / weekdays, 2),
        "win_rate": round(len(wins) / len(trades), 4),
        "realized_rr": round(avg_win / avg_loss, 3) if avg_loss else None,
        "net": round(sum(nets), 6),
        "expectancy": round(sum(nets) / len(trades), 7),
        "revert_exits": sum(1 for _, _, r in trades if r == "revert"),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--a", default="EURUSD")
    p.add_argument("--b", default="GBPUSD")
    p.add_argument("--w", type=int, default=100)
    p.add_argument("--z-entry", type=float, default=2.0)
    p.add_argument("--z-stop", type=float, default=3.5)
    p.add_argument("--slippage", type=float, default=0.00005)
    p.add_argument("--bars-root", default="data/validation/bars")
    args = p.parse_args(argv)
    r = probe(
        args.a, args.b, Path(args.bars_root), args.w, args.z_entry, args.z_stop, args.slippage
    )
    print(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
