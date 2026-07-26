"""Refresh latest price marks for the open paper book -> data/paper/marks.json.

The dashboard shows per-position P&L; fetching 50+ Yahoo quotes inside a
web request would be slow and abusive, so a cron refreshes a marks cache
(every 30 minutes on weekdays + after sessions) and the API serves it.

Usage (mini PC):
    PYTHONPATH="src:scripts" python scripts/refresh_marks.py
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--paper-dir", default="data/paper")
    p.add_argument("--sleep", type=float, default=0.15)
    args = p.parse_args(argv)
    root = Path(args.paper_dir)

    from fetch_stocks import fetch as fetch_yahoo  # noqa: PLC0415

    state_path = root / "paper_state.json"
    if not state_path.exists():
        print("no paper state; nothing to mark")
        return 0
    positions = json.loads(state_path.read_text(encoding="utf-8"))["positions"]
    now = int(time.time())
    start = now - 10 * 86400
    marks: dict[str, dict] = {}
    for sym in sorted(positions):
        try:
            bars = fetch_yahoo(sym, start, now)
            marks[sym] = {"price": float(bars[-1][5]), "bar_date": str(bars[-1][0])}
        except Exception:  # noqa: BLE001 - missing quote -> position shows entry
            continue
        time.sleep(args.sleep)
    payload = {
        "refreshed_at": datetime.now(UTC).isoformat(),
        "marks": marks,
    }
    (root / "marks.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"marked {len(marks)}/{len(positions)} positions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
