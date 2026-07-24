"""PRE-REGISTERED gauntlet for the bi-monthly short-interest signal.

Committed BEFORE the data exists (it needs the FINRA credential the user is
obtaining — see fetch_short_interest.py). This file IS the pre-registration:
the variant grid below is frozen by this commit, and any later change to it
must be treated as new trials in the registry. No peeking, no widening.

Pre-registered trial plan (exactly two variants, literature-motivated):
  A. days-to-cover: currentShortPositionQuantity / averageDailyVolumeQuantity.
     Long the lowest quintile, short the highest (crowded shorts underperform
     on average but squeeze; DTC is the classic crowding measure).
  B. short-interest CHANGE: current vs previous position quantity (per
     symbol). Long biggest decreases, short biggest increases.

Construction (both variants): S&P-universe intersection, quintile buckets
(min 5 per side), rebalance at each PUBLICATION (not settlement!), hold to
next publication, turnover costed 4 bps/side.

Point-in-time discipline: FINRA disseminates bi-monthly short interest
~8 business days after settlement. knowledge_time = settlement + 9 business
days (one extra day of conservatism); positions may first form on the NEXT
trading day after knowledge_time.

Gates: DSR vs the registry's honest trial count, CPCV 6-choose-2 with
purge/embargo. SPA vs momentum only if a variant survives standalone.

Usage (after fetch_short_interest.py has populated data/pit/shortinterest):
    PYTHONPATH="src;scripts" python scripts/validate_short_interest_signal.py
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from trading_desk.trials import TrialRegistry, deflated_sharpe_ratio
from trading_desk.trials.cpcv import combinatorial_purged_splits

COST_PER_SIDE = 4e-4
BUCKET_FRACTION = 0.2
MIN_BUCKET = 5
MIN_CANDIDATES = 50
PUBLICATION_LAG_BDAYS = 9  # settlement -> knowable (8 bdays typical + 1)

DEV_START = date(2022, 1, 3)
VAL_END = date(2026, 6, 30)


def add_business_days(d: date, n: int) -> date:
    cur = d
    added = 0
    while added < n:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            added += 1
    return cur


def load_partitions(si_dir: Path) -> dict[date, list[dict]]:
    """settlementDate -> raw records (as fetched)."""

    out: dict[date, list[dict]] = {}
    for path in sorted(si_dir.glob("*.jsonl")):
        day = date.fromisoformat(path.stem)
        out[day] = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return out


DTC_SENTINEL = 999.0  # sentinel/no-volume guard; untradeable signal value


def variant_scores(records: list[dict], variant: str) -> dict[str, float]:
    """Symbol -> score (higher = more shorted/crowded = SHORT leg).

    Schema = otcMarket/consolidatedShortInterest (the LISTED-market
    dataset, verified live 2026-07-24): symbolCode, daysToCoverQuantity
    (provided directly by FINRA), currentShortPositionQuantity /
    previousShortPositionQuantity in the same record. The pre-registered
    HYPOTHESES and grid are unchanged by this dataset retarget — the
    earlier equityShortInterest target was the OTC slice and never
    contained the listed names the plan was written for.
    """

    def field(rec: dict, name: str) -> float | None:
        value = rec.get(name)
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    scores: dict[str, float] = {}
    if variant == "days-to-cover":
        for rec in records:
            sym = rec.get("symbolCode")
            dtc = field(rec, "daysToCoverQuantity")
            if isinstance(sym, str) and dtc is not None and 0 < dtc < DTC_SENTINEL:
                scores[sym] = dtc
    elif variant == "si-change":
        for rec in records:
            sym = rec.get("symbolCode")
            pos = field(rec, "currentShortPositionQuantity")
            prev_pos = field(rec, "previousShortPositionQuantity")
            if isinstance(sym, str) and pos is not None and prev_pos:
                scores[sym] = pos / prev_pos - 1.0
    else:
        raise ValueError(f"unknown variant: {variant}")
    return scores


def build_series(
    partitions: dict[date, list[dict]],
    membership: dict,
    rets: dict[str, dict[date, float]],
    trading_days: list[date],
    member_on,
    variant: str,
) -> dict[date, float]:
    """Daily net L/S returns: rebalance at publication, hold to next."""

    settle_days = sorted(partitions)
    schedule: list[tuple[date, date]] = []  # (first tradeable day, settlement)
    for sd in settle_days:
        knowable = add_business_days(sd, PUBLICATION_LAG_BDAYS)
        tradeable = next((t for t in trading_days if t > knowable), None)
        if tradeable is not None:
            schedule.append((tradeable, sd))

    out: dict[date, float] = {}
    low: set[str] = set()
    high: set[str] = set()
    prev_low: set[str] = set()
    prev_high: set[str] = set()
    pending_cost = 0.0
    sched_i = 0
    for d in trading_days:
        while sched_i < len(schedule) and schedule[sched_i][0] <= d:
            tradeable, sd = schedule[sched_i]
            scores = variant_scores(partitions[sd], variant)
            candidates = sorted(
                (score, sym)
                for sym, score in scores.items()
                if member_on(membership, sym, d) and d in rets.get(sym, {})
            )
            if len(candidates) >= MIN_CANDIDATES:
                k = max(int(len(candidates) * BUCKET_FRACTION), MIN_BUCKET)
                prev_low, prev_high = low, high
                low = {sym for _, sym in candidates[:k]}
                high = {sym for _, sym in candidates[-k:]}
                if prev_low:
                    churn = (
                        len(low ^ prev_low) / (2 * len(low))
                        + len(high ^ prev_high) / (2 * len(high))
                    ) / 2
                else:
                    churn = 1.0
                pending_cost = churn * 2 * COST_PER_SIDE
            sched_i += 1
        if not low or not high:
            continue
        in_low = [s for s in low if d in rets.get(s, {})]
        in_high = [s for s in high if d in rets.get(s, {})]
        if not in_low or not in_high:
            continue
        gross = (
            sum(rets[s][d] for s in in_low) / len(in_low)
            - sum(rets[s][d] for s in in_high) / len(in_high)
        ) / 2
        out[d] = gross - pending_cost
        pending_cost = 0.0
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pit-dir", default="data/pit")
    p.add_argument("--out", default="data/pit/short_interest_result.json")
    args = p.parse_args(argv)
    pit = Path(args.pit_dir)

    si_dir = pit / "consolidated_short_interest"
    partitions = load_partitions(si_dir)
    if len(partitions) < 24:  # ~1 year of bi-monthly data minimum
        raise SystemExit(
            f"only {len(partitions)} short-interest partitions in {si_dir} - "
            "run fetch_short_interest.py with FINRA credentials first "
            "(docs/strategy-research/UNBLOCK-ACTIONS.md, Action 1)"
        )

    from validate_insider_signal import (  # noqa: PLC0415 - scripts path
        daily_returns,
        load_membership,
        load_prices,
        member_on,
    )

    prices = load_prices(pit / "bars")
    membership = load_membership(pit)
    all_days = sorted({d for s in prices.values() for d in s})
    trading_days = [d for d in all_days if DEV_START <= d <= VAL_END]
    rets = daily_returns(prices, trading_days)

    registry = TrialRegistry(pit / "trial_registry.jsonl")
    results: dict[str, dict] = {}
    for variant in ("days-to-cover", "si-change"):
        series = build_series(partitions, membership, rets, trading_days, member_on, variant)
        daily = np.array([series[d] for d in sorted(series)])
        n = len(daily)
        if n < 200 or float(daily.std()) < 1e-9:
            print(f"[{variant}] degenerate series (n={n}); recorded as unusable")
            results[variant] = {"n_days": n, "verdict": "DEGENERATE"}
            continue
        sr_daily = float(daily.mean() / daily.std())
        registry.record(
            family="short-interest-bimonthly",
            params={
                "variant": variant,
                "bucket_fraction": BUCKET_FRACTION,
                "publication_lag_bdays": PUBLICATION_LAG_BDAYS,
            },
            sharpe=sr_daily,
            n_observations=n,
            window=f"{DEV_START.isoformat()}..{VAL_END.isoformat()}",
        )
        n_trials, sharpe_var = registry.dsr_inputs("short-interest-bimonthly")
        dsr = deflated_sharpe_ratio(
            observed_sharpe=sr_daily,
            n_trials=max(n_trials, 1),
            sharpe_variance=max(sharpe_var, 1e-8),
            n_observations=n,
            skewness=float(((daily - daily.mean()) ** 3).mean() / daily.std() ** 3),
            kurtosis=float(((daily - daily.mean()) ** 4).mean() / daily.std() ** 4),
        )
        splits = combinatorial_purged_splits(n, n_groups=6, test_groups=2, label_span=1, embargo=5)
        positive = sum(
            1
            for _, test_idx in splits
            if daily[test_idx].std() > 0 and daily[test_idx].mean() / daily[test_idx].std() > 0
        )
        ann = sr_daily * 252**0.5
        print(f"[{variant}] n={n} Sharpe {ann:.3f}/yr DSR {dsr:.4f} CPCV {positive}/{len(splits)}")
        results[variant] = {
            "n_days": n,
            "sharpe_annualized": round(ann, 4),
            "dsr": round(dsr, 4),
            "cpcv_positive_folds": f"{positive}/{len(splits)}",
        }

    Path(args.out).write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
