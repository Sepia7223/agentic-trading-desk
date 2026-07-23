"""Download SEC Form 3/4/5 structured insider-transaction datasets (quarterly).

The DERA insider datasets are the correct source for the insider-cluster
signal: complete (every filing), structured (TSV tables), free, and carrying
FILING_DATE per accession — the knowledge-time key the feature store requires.
One zip per quarter; resume-safe (existing files skipped).

Usage:
    python scripts/fetch_form345.py --start 2021q4 --end 2026q2
"""

from __future__ import annotations

import argparse
import time
import urllib.request
from pathlib import Path

BASE = (
    "https://www.sec.gov/files/structureddata/data/"
    "insider-transactions-data-sets/{quarter}_form345.zip"
)
_UA = {"User-Agent": "agentic-trading-desk research ops@itsolutions.cw"}


def quarter_range(start: str, end: str) -> list[str]:
    def parse(q: str) -> tuple[int, int]:
        year, qtr = q.lower().split("q")
        return int(year), int(qtr)

    y, q = parse(start)
    ye, qe = parse(end)
    out: list[str] = []
    while (y, q) <= (ye, qe):
        out.append(f"{y}q{q}")
        q += 1
        if q == 5:
            y, q = y + 1, 1
    return out


def fetch_quarter(quarter: str, out_dir: Path, timeout: float = 120.0) -> str:
    path = out_dir / f"{quarter}_form345.zip"
    if path.exists() and path.stat().st_size > 1_000_000:
        return "cached"
    req = urllib.request.Request(BASE.format(quarter=quarter), headers=_UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
    except Exception as exc:  # noqa: BLE001 - reported per quarter, not fatal
        return f"FAILED: {exc}"
    path.write_bytes(data)
    return f"{len(data) / 1e6:.1f}MB"


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2021q4")
    p.add_argument("--end", default="2026q2")
    p.add_argument("--out", default="data/pit/form345")
    args = p.parse_args(argv)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    failures = 0
    for quarter in quarter_range(args.start, args.end):
        status = fetch_quarter(quarter, out_dir)
        print(f"{quarter}: {status}")
        if status.startswith("FAILED"):
            failures += 1
        if status != "cached":
            time.sleep(1.0)
    print(f"done; failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
