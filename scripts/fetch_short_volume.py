"""Download FINRA daily consolidated short-sale volume files (CNMS).

Free, keyless, current. Feeds the short-volume-ratio signal (ShortVolume /
TotalVolume per symbol per day). HONEST GRADING UP FRONT: the research rates
public daily short-volume as a WEAK signal (dominated by market-maker liquidity
provision; the strong Boehmer-Jones-Zhang results used proprietary order data),
and bi-monthly short INTEREST — the strong variant — requires a free registered
FINRA API key (anonymous access ends 2022-09). The gauntlet decides.

Usage:
    python scripts/fetch_short_volume.py --start 2021-12-01 --end 2026-06-30
"""

from __future__ import annotations

import argparse
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{stamp}.txt"
_UA = {"User-Agent": "agentic-trading-desk research ops@itsolutions.cw"}


def fetch_day(d: date, out_dir: Path, timeout: float = 30.0) -> str:
    path = out_dir / f"{d.isoformat()}.txt"
    if path.exists() and path.stat().st_size > 1000:
        return "cached"
    req = urllib.request.Request(
        URL.format(stamp=d.strftime("%Y%m%d")), headers=_UA
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
    except Exception:  # noqa: BLE001 - holidays/weekends 404; skip quietly
        return "missing"
    path.write_bytes(data)
    return f"{len(data) // 1024}KB"


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2021-12-01")
    p.add_argument("--end", default="2026-06-30")
    p.add_argument("--out", default="data/pit/shortvol")
    p.add_argument("--sleep", type=float, default=0.15)
    args = p.parse_args(argv)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    d = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    fetched = missing = cached = 0
    while d <= end:
        if d.weekday() < 5:  # weekdays only
            status = fetch_day(d, out_dir)
            if status == "cached":
                cached += 1
            elif status == "missing":
                missing += 1
            else:
                fetched += 1
                time.sleep(args.sleep)
            if (fetched + cached) % 100 == 0 and (fetched + cached) > 0:
                print(f"  through {d}: fetched={fetched} cached={cached} missing={missing}")
        d += timedelta(days=1)
    print(f"done: fetched={fetched} cached={cached} missing(holidays)={missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
