"""Loss forensics for the open paper book: WHY is each loser down?

For every losing open position, decompose the damage since entry:
- worst single day and whether it was an overnight GAP (open vs prior
  close) or intraday drift. A dominant gap on a big down day is the
  signature of an EVENT (earnings, guidance, filing) hitting a held
  position - something the entry-time news gate structurally cannot see.
- book-level attribution: long-book vs short-book P&L, so factor
  pullback (all longs bleeding together) is distinguishable from
  name-specific accidents.

Also prints the realized stop-out(s) from the journal. Output feeds the
improvement decision; it changes nothing by itself.

Usage (mini PC):
    PYTHONPATH="src:scripts" python scripts/review_losers.py
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date
from pathlib import Path

EVENT_DAY_THRESHOLD = -0.035  # a worst day at least this bad, and
GAP_SHARE_THRESHOLD = 0.6  # >=60% of it overnight => event signature


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--paper-dir", default="data/paper")
    p.add_argument("--sleep", type=float, default=0.1)
    args = p.parse_args(argv)
    root = Path(args.paper_dir)

    from fetch_stocks import fetch as fetch_yahoo  # noqa: PLC0415

    state = json.loads((root / "paper_state.json").read_text(encoding="utf-8"))
    positions = state["positions"]

    # entry dates from the fill journal (first entry fill per symbol)
    entry_date: dict[str, str] = {}
    stop_outs = []
    for line in (root / "journal.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("type") != "fill":
            continue
        sym = row.get("symbol")
        direction = row.get("direction", "")
        if direction in ("BUY", "SELL_SHORT") and sym not in entry_date:
            entry_date[sym] = str(row.get("session", ""))
        if "stop" in str(row.get("order_id", "")) or row.get("is_stop"):
            stop_outs.append(row)

    now = int(time.time())
    start = now - 30 * 86400
    long_pnl = short_pnl = 0.0
    events = []
    drifts = []
    for sym, pos in sorted(positions.items()):
        qty = float(pos["quantity"])
        entry = float(pos["entry_price"])
        try:
            bars = fetch_yahoo(sym, start, now)
        except Exception:  # noqa: BLE001 - symbol fetch failure -> skip
            continue
        time.sleep(args.sleep)
        closes = [(str(b[0]), float(b[1]), float(b[5])) for b in bars]  # date, open, adjclose
        px = closes[-1][2]
        pnl = (px - entry) * qty
        if qty > 0:
            long_pnl += pnl
        else:
            short_pnl += pnl
        side_return = (px / entry - 1) * (1 if qty > 0 else -1)
        if side_return >= 0:
            continue
        # decompose the position's days since (approximate) entry
        opened = entry_date.get(sym, "")
        since = [c for c in closes if c[0] >= opened] if opened else closes[-6:]
        worst = (0.0, "", 0.0)  # (day return, date, gap share)
        for i in range(1, len(since)):
            prev_close = since[i - 1][2]
            day_open, day_close = since[i][1], since[i][2]
            if prev_close <= 0 or day_open <= 0:
                continue
            day_ret = day_close / prev_close - 1
            if day_ret < worst[0]:
                gap = day_open / prev_close - 1
                share = gap / day_ret if day_ret != 0 else 0.0
                worst = (day_ret, since[i][0], max(0.0, min(1.5, share)))
        record = {
            "symbol": sym,
            "side": "LONG" if qty > 0 else "SHORT",
            "return": round(side_return, 4),
            "worst_day": worst[1],
            "worst_day_return": round(worst[0], 4),
            "gap_share": round(worst[2], 2),
            "opened": opened,
        }
        if worst[0] <= EVENT_DAY_THRESHOLD and worst[2] >= GAP_SHARE_THRESHOLD:
            events.append(record)
        else:
            drifts.append(record)

    print(f"book P&L attribution: LONG {long_pnl:+.2f} | SHORT {short_pnl:+.2f}")
    print(f"\nEVENT-SIGNATURE losers (big overnight gap while held): {len(events)}")
    for r in sorted(events, key=lambda x: x["return"]):
        print(
            f"  {r['symbol']:5s} {r['side']:5s} {r['return']:+7.1%} | worst "
            f"{r['worst_day']} {r['worst_day_return']:+.1%} (gap {r['gap_share']:.0%})"
        )
    print(f"\nDRIFT losers (gradual, factor-style): {len(drifts)}")
    for r in sorted(drifts, key=lambda x: x["return"])[:12]:
        print(
            f"  {r['symbol']:5s} {r['side']:5s} {r['return']:+7.1%} | worst "
            f"{r['worst_day']} {r['worst_day_return']:+.1%} (gap {r['gap_share']:.0%})"
        )
    print(f"\nrealized stop-outs so far: {len(stop_outs)}")
    for row in stop_outs:
        print(
            f"  {row.get('symbol')} {row.get('direction')} @ {row.get('price')} "
            f"on {row.get('session')}"
        )
    print(f"\ntoday: {date.today().isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
