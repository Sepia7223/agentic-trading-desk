"""Nightly forward shadow log for the DTC-CFD challenge sleeve (mini PC).

The days-to-cover sleeve passed its full-universe pre-registered gauntlet
(DSR 0.9868, CPCV 15/15); its CFD-universe port measured Sharpe 0.906 at
14.7% natural vol BUT deflates to DSR 0.66 across the whole
challenge-venue search — promising, not proven. This logger accrues the
forward evidence that can settle it: each trading night it marks the
CURRENT DTC book on the legacy CFD universe with the day's returns and
appends one row. No fee decision happens without this record.

Construction mirrors the registered trial exactly: latest consolidated
short-interest publication that is >= 9 business days past settlement,
6 names per side (20% of ~30), long low days-to-cover / short high,
turnover costed 4 bps/side at each publication switch, CFD financing
2.5%/yr on gross deducted daily.

Cron (after the paper session and shortvol shadow):
    45 19 * * 1-5 .../scripts/run_shadow_dtc.sh
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

FORMATION_FRACTION = 0.2
MIN_SIDE = 5
COST_PER_SIDE = 4e-4
CFD_SPREAD_ANNUAL = 0.025
PUBLICATION_LAG_BDAYS = 9


def add_business_days(d: date, n: int) -> date:
    cur = d
    added = 0
    while added < n:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            added += 1
    return cur


def latest_knowable_partition(si_dir: Path, today: date) -> date | None:
    """Most recent settlement date whose publication lag has elapsed."""

    best: date | None = None
    for path in sorted(si_dir.glob("*.jsonl")):
        sd = date.fromisoformat(path.stem)
        if add_business_days(sd, PUBLICATION_LAG_BDAYS) < today and (best is None or sd > best):
            best = sd
    return best


def dtc_buckets(records: list[dict], universe: set[str]) -> tuple[list[str], list[str]]:
    """(low_dtc_longs, high_dtc_shorts) on the given universe."""

    scored = sorted(
        (float(rec["daysToCoverQuantity"]), str(rec["symbolCode"]))
        for rec in records
        if rec.get("symbolCode") in universe
        and rec.get("daysToCoverQuantity") is not None
        and 0 < float(rec["daysToCoverQuantity"]) < 999.0
    )
    if len(scored) < 2 * MIN_SIDE:
        return [], []
    k = max(int(len(scored) * FORMATION_FRACTION), MIN_SIDE)
    return sorted(s for _, s in scored[:k]), sorted(s for _, s in scored[-k:])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pit-dir", default="data/pit")
    p.add_argument("--shadow-dir", default="data/shadow")
    p.add_argument("--sleep", type=float, default=0.35)
    args = p.parse_args(argv)

    from fetch_short_interest import fetch_partition, list_partitions  # noqa: PLC0415
    from paper_trade import fetch_recent_bars  # noqa: PLC0415
    from validate_challenge_cfd_variant import LEGACY_UNIVERSE  # noqa: PLC0415

    # keep the consolidated cache current (new partitions appear bi-monthly)
    si_dir = Path(args.pit_dir) / "consolidated_short_interest"
    si_dir.mkdir(parents=True, exist_ok=True)
    try:
        for sd in list_partitions(None)[-3:]:
            path = si_dir / f"{sd}.jsonl"
            if not path.exists():
                records = fetch_partition(sd, None)
                if records:
                    with path.open("w", encoding="utf-8") as fh:
                        for rec in records:
                            fh.write(json.dumps(rec) + "\n")
                    print(f"cached new partition {sd}: {len(records)} records")
    except Exception as exc:  # noqa: BLE001 - network hiccup -> use cache
        print(f"partition refresh skipped: {exc}")

    shadow = Path(args.shadow_dir)
    shadow.mkdir(parents=True, exist_ok=True)
    log_path = shadow / "dtc_cfd_forward.jsonl"
    rows = (
        [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line]
        if log_path.exists()
        else []
    )
    logged = {r["date"] for r in rows}
    prev_partition = rows[-1]["partition"] if rows else None
    prev_longs = set(rows[-1]["longs"]) if rows else set()
    prev_shorts = set(rows[-1]["shorts"]) if rows else set()

    today = date.today()
    partition = latest_knowable_partition(si_dir, today)
    if partition is None:
        print("no knowable partition cached; nothing to log")
        return 0
    records = [
        json.loads(line)
        for line in (si_dir / f"{partition.isoformat()}.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    longs, shorts = dtc_buckets(records, set(LEGACY_UNIVERSE))
    if not longs:
        print("bucket construction failed (thin cross-section); nothing to log")
        return 0

    bars = fetch_recent_bars(sorted(set(longs) | set(shorts)), args.sleep)
    day_closes: dict[date, dict[str, float]] = {}
    for sym, series in bars.items():
        for row in series[-10:]:
            day_closes.setdefault(row[0], {})[sym] = float(row[4])
    days = sorted(day_closes)
    if len(days) < 2:
        print("insufficient bar coverage; nothing to log")
        return 0
    d_prev, d_now = days[-2], days[-1]
    if d_now.isoformat() in logged:
        print(f"{d_now}: already logged")
        return 0

    def leg_return(names: list[str]) -> float | None:
        rets = [
            day_closes[d_now][s] / day_closes[d_prev][s] - 1
            for s in names
            if s in day_closes[d_now] and s in day_closes[d_prev]
        ]
        return sum(rets) / len(rets) if rets else None

    long_r, short_r = leg_return(longs), leg_return(shorts)
    if long_r is None or short_r is None:
        print("missing leg prices; nothing to log")
        return 0
    gross = (long_r - short_r) / 2
    turnover = 0.0
    if prev_partition != partition.isoformat() and prev_longs:
        turnover = (
            len(set(longs) ^ prev_longs) / (2 * len(longs))
            + len(set(shorts) ^ prev_shorts) / (2 * len(shorts))
        ) / 2
    net = gross - turnover * 2 * COST_PER_SIDE - CFD_SPREAD_ANNUAL / 252

    entry = {
        "date": d_now.isoformat(),
        "partition": partition.isoformat(),
        "gross": round(gross, 8),
        "net": round(net, 8),
        "turnover": round(turnover, 6),
        "longs": longs,
        "shorts": shorts,
    }
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    print(f"{d_now}: net {net:+.5f} (partition {partition}, turnover {turnover:.2f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
