"""Fetch Binance spot klines and write them in the harness bid/ask CSV format.

Market pivot for the acceptance search: FX has no exploitable intraday edge, so no
price-only strategy is net-positive at 3-8 trades/day. Crypto trades 24/7 with
genuine intraday trends, so trend/breakout can plausibly clear cost at that
frequency. This fetcher pulls OHLCV (trade prices), synthesises a conservative CFD
bid/ask via a modelled half-spread, and writes {SYMBOL}_{TF}.csv matching the
columns load_bars expects, so the existing harnesses run unchanged.

RESEARCH tooling. Costs are modelled (crypto CFD spread + slippage), documented.

Usage:
    python scripts/fetch_crypto.py --symbols BTCUSDT,ETHUSDT --interval 1h \
        --start 2022-01-01 --end 2026-06-30 --half-spread-bps 3 --out data/crypto/bars
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

BASE = "https://data-api.binance.vision/api/v3/klines"
TF_MS = {"1h": 3_600_000, "15m": 900_000, "5m": 300_000, "4h": 14_400_000}


def _ms(date_str: str) -> int:
    return int(datetime.fromisoformat(date_str).replace(tzinfo=UTC).timestamp() * 1000)


def fetch(symbol: str, interval: str, start_ms: int, end_ms: int) -> list[list]:
    rows: list[list] = []
    cur = start_ms
    step = TF_MS[interval]
    while cur < end_ms:
        url = f"{BASE}?symbol={symbol}&interval={interval}&startTime={cur}&limit=1000"
        for attempt in range(5):
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    batch = json.loads(r.read().decode())
                break
            except Exception as exc:  # noqa: BLE001 - retry any transport error
                if attempt == 4:
                    raise
                time.sleep(2 * (attempt + 1))
                _ = exc
        if not batch:
            break
        rows.extend(batch)
        cur = batch[-1][0] + step
        if len(batch) < 1000:
            break
        time.sleep(0.15)
    return [r for r in rows if r[0] < end_ms]


def write_csv(symbol: str, interval: str, klines: list[list], hs_bps: float, out: Path) -> int:
    hs = hs_bps / 10000.0
    out.mkdir(parents=True, exist_ok=True)
    tf_name = {"1h": "HOUR", "15m": "MINUTE_15", "5m": "MINUTE_5", "4h": "HOUR_4"}[interval]
    path = out / f"{symbol}_{tf_name}.csv"
    header = (
        "epic,timestamp,open_bid,open_ask,high_bid,high_ask,"
        "low_bid,low_ask,close_bid,close_ask,last_traded_volume\n"
    )
    lines = [header]
    for k in klines:
        ts = datetime.fromtimestamp(k[0] / 1000, tz=UTC).isoformat()
        o, h, low, c, vol = float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])
        row = [
            symbol,
            ts,
            f"{o * (1 - hs):.8g}",
            f"{o * (1 + hs):.8g}",
            f"{h * (1 - hs):.8g}",
            f"{h * (1 + hs):.8g}",
            f"{low * (1 - hs):.8g}",
            f"{low * (1 + hs):.8g}",
            f"{c * (1 - hs):.8g}",
            f"{c * (1 + hs):.8g}",
            f"{vol:.4f}",
        ]
        lines.append(",".join(row) + "\n")
    path.write_text("".join(lines), encoding="utf-8")
    return len(klines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--symbols",
        default="BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,ADAUSDT,LTCUSDT,DOGEUSDT",
    )
    p.add_argument("--interval", default="1h", choices=list(TF_MS))
    p.add_argument("--start", default="2022-01-01")
    p.add_argument("--end", default="2026-06-30")
    p.add_argument("--half-spread-bps", type=float, default=3.0)
    p.add_argument("--out", default="data/crypto/bars")
    args = p.parse_args(argv)
    start_ms, end_ms = _ms(args.start), _ms(args.end)
    out = Path(args.out)
    for sym in [s.strip() for s in args.symbols.split(",") if s.strip()]:
        kl = fetch(sym, args.interval, start_ms, end_ms)
        n = write_csv(sym, args.interval, kl, args.half_spread_bps, out)
        first = datetime.fromtimestamp(kl[0][0] / 1000, tz=UTC).date() if kl else "-"
        last = datetime.fromtimestamp(kl[-1][0] / 1000, tz=UTC).date() if kl else "-"
        print(f"{sym} {args.interval}: {n} bars {first}..{last}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
