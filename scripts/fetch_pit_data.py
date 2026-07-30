"""Fetch daily bars for the FULL point-in-time universe, with a coverage report.

Companion to build_pit_universe.py. Fetches every ticker that was an S&P 500
member at any point in the window — including names later removed/delisted — and
writes an honest coverage report:

    full     — data spans the ticker's membership interval(s)
    partial  — data ends before the window end (usually a delisting: this is the
               DESIRED data — the name's history until it stopped trading)
    missing  — no retrievable data at all (residual survivorship bias; REPORTED,
               and listed by membership interval so its weight can be estimated)

Output: data/pit/bars/<TICKER>.csv (same schema as fetch_stocks.py) and
data/pit/coverage.json.

Usage:
    python scripts/fetch_pit_data.py --start 2021-01-01 --end 2026-06-30
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from fetch_stocks import fetch  # type: ignore[import-not-found]


def _ts(d: str) -> int:
    return int(datetime.fromisoformat(d).replace(tzinfo=UTC).timestamp())


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2021-01-01")
    p.add_argument("--end", default="2026-06-30")
    p.add_argument("--pit-dir", default="data/pit")
    p.add_argument("--sleep", type=float, default=0.25)
    args = p.parse_args(argv)
    pit = Path(args.pit_dir)
    universe = json.loads(
        (pit / f"universe_{args.start}_{args.end}.json").read_text(encoding="utf-8")
    )
    intervals: dict[str, list[list[str]]] = universe["intervals"]
    out = pit / "bars"
    out.mkdir(parents=True, exist_ok=True)
    p1, p2 = _ts(args.start), _ts(args.end)

    coverage: dict[str, dict] = {}
    n_full = n_partial = n_missing = 0
    tickers = sorted(intervals)
    for i, sym in enumerate(tickers, 1):
        csv_path = out / f"{sym}.csv"
        rows: list[tuple] = []
        if csv_path.exists():  # resume support
            lines = csv_path.read_text(encoding="utf-8").splitlines()[1:]
            rows = [tuple(line.split(",")) for line in lines if line]
        else:
            try:
                rows = fetch(sym, p1, p2)
            except Exception:
                rows = []
            if rows:
                lines = ["date,open,high,low,close,adjclose,volume\n"]
                for r in rows:
                    lines.append(
                        f"{r[0]},{r[1]:.4f},{r[2]:.4f},{r[3]:.4f},{r[4]:.4f},"
                        f"{r[5]:.6f},{r[6]}\n"
                    )
                csv_path.write_text("".join(lines), encoding="utf-8")
            time.sleep(args.sleep)
        if not rows:
            status = "missing"
            n_missing += 1
            first = last = None
        else:
            first, last = str(rows[0][0]), str(rows[-1][0])
            member_end = max(iv[1] for iv in intervals[sym])
            # full if data reaches (close to) the end of the last membership interval
            status = "full" if last >= min(member_end, args.end) else "partial"
            if status == "full":
                n_full += 1
            else:
                n_partial += 1
        coverage[sym] = {
            "status": status,
            "data_first": first,
            "data_last": last,
            "membership": intervals[sym],
        }
        if i % 100 == 0 or i == len(tickers):
            print(f"  {i}/{len(tickers)} fetched (full={n_full} partial={n_partial} "
                  f"missing={n_missing})")

    missing = sorted(s for s, c in coverage.items() if c["status"] == "missing")
    partial = sorted(s for s, c in coverage.items() if c["status"] == "partial")
    report = {
        "window": [args.start, args.end],
        "tickers_total": len(tickers),
        "full": n_full,
        "partial_ends_early": n_partial,
        "missing": n_missing,
        "missing_pct": round(100 * n_missing / len(tickers), 1),
        "missing_tickers": missing,
        "partial_tickers": partial,
        "note": (
            "partial = data ends before window end; for removed names this is the "
            "desired delisting history. missing = residual survivorship bias — "
            "these members cannot be simulated and their absence must be "
            "acknowledged in any result."
        ),
        "per_ticker": coverage,
    }
    (pit / "coverage.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\ncoverage: full={n_full} partial={n_partial} missing={n_missing} "
          f"({report['missing_pct']}% of PIT universe unfetchable)")
    print(f"missing sample: {missing[:20]}")
    print(f"wrote {pit}/coverage.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
