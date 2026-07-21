"""Fetch daily equity bars from the Yahoo Finance chart API.

Pivot for the v3 consistency mandate + the user's real markets (stocks/forex): a
diversified, market-neutral equity strategy across many low-correlation names is the
classic route to smooth, low-drawdown, compounding returns. This fetches daily OHLC
(adjusted close) for a sector-diversified universe and writes one CSV per symbol.

RESEARCH tooling. Adjusted close is used for returns (splits/dividends handled).

Usage:
    python scripts/fetch_stocks.py --start 2022-01-01 --end 2026-06-30 --out data/stocks
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

# Sector-diversified liquid US large caps (real diversification, unlike crypto).
UNIVERSE = [
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "META",
    "NVDA",
    "TSLA",
    "AVGO",
    "ORCL",
    "CRM",
    "JPM",
    "BAC",
    "GS",
    "WFC",
    "MS",
    "C",
    "AXP",
    "BLK",
    "JNJ",
    "PFE",
    "UNH",
    "MRK",
    "ABBV",
    "LLY",
    "TMO",
    "XOM",
    "CVX",
    "COP",
    "SLB",
    "PG",
    "KO",
    "PEP",
    "WMT",
    "COST",
    "MDLZ",
    "HD",
    "MCD",
    "NKE",
    "LOW",
    "SBUX",
    "CAT",
    "BA",
    "HON",
    "GE",
    "UPS",
    "DE",
    "DIS",
    "VZ",
    "T",
    "CMCSA",
    "NFLX",
    "LIN",
    "NEE",
    "DUK",
]


def _ts(d: str) -> int:
    return int(datetime.fromisoformat(d).replace(tzinfo=UTC).timestamp())


def fetch(symbol: str, p1: int, p2: int) -> list[tuple]:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?period1={p1}&period2={p2}&interval=1d"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode())
            break
        except Exception:  # noqa: BLE001
            if attempt == 4:
                raise
            time.sleep(2 * (attempt + 1))
    res = data["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"]["adjclose"][0]["adjclose"]
    rows = []
    for i in range(len(ts)):
        if None in (q["open"][i], q["high"][i], q["low"][i], q["close"][i], adj[i]):
            continue
        d = datetime.fromtimestamp(ts[i], tz=UTC).date().isoformat()
        rows.append(
            (d, q["open"][i], q["high"][i], q["low"][i], q["close"][i], adj[i], q["volume"][i])
        )
    return rows


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2022-01-01")
    p.add_argument("--end", default="2026-06-30")
    p.add_argument("--out", default="data/stocks")
    p.add_argument("--symbols", default=",".join(UNIVERSE))
    args = p.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    p1, p2 = _ts(args.start), _ts(args.end)
    ok = 0
    for sym in [s.strip() for s in args.symbols.split(",") if s.strip()]:
        try:
            rows = fetch(sym, p1, p2)
        except Exception as exc:  # noqa: BLE001
            print(f"{sym}: FAILED {exc}")
            continue
        lines = ["date,open,high,low,close,adjclose,volume\n"]
        for r in rows:
            lines.append(f"{r[0]},{r[1]:.4f},{r[2]:.4f},{r[3]:.4f},{r[4]:.4f},{r[5]:.6f},{r[6]}\n")
        (out / f"{sym}.csv").write_text("".join(lines), encoding="utf-8")
        ok += 1
        first = rows[0][0] if rows else "-"
        last = rows[-1][0] if rows else "-"
        print(f"{sym}: {len(rows)} days {first}..{last}")
        time.sleep(0.2)
    print(f"--- {ok} symbols saved to {out} ---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
