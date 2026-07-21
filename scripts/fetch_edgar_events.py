"""Fetch a point-in-time corporate-event ledger from SEC EDGAR 8-K filings.

Purpose: let the backtest simulate "read the news, then decide" causally. Every
US issuer must report material events on Form 8-K; EDGAR records the acceptance
timestamp to the second, keeps delisted companies forever (survivorship-free),
and is keyless. Simulated decisions may only use filings ACCEPTED before the
decision moment — the same discipline the live news gate enforces.

PRE-REGISTERED item -> tier mapping (changed only by written decision):
  BLOCK   1.03 bankruptcy/receivership · 3.01 delisting notice · 4.01 auditor
          change · 4.02 non-reliance on financials (restatement) · 5.01 change
          in control · 2.04 default/acceleration
  CAUTION 1.01 material agreement (incl. merger agreements) · 1.02 termination
          · 2.01 completed acquisition/disposition · 2.02 results (earnings) ·
          2.05 exit/restructuring · 2.06 impairment · 3.02 unregistered sales
          (dilution) · 5.02 officer/director changes
  INFO    anything else (7.01 Reg FD, 8.01 other, 5.07 votes, 9.01 exhibits...)

HONEST LIMITS (documented): 8-Ks are filings, not headlines — media stories can
precede the filing by hours (acceptance-time causality is therefore
conservative: the simulated trader learns some events later than a live reader
would). Coverage begins at the ticker->CIK mapping, which is current-registrant
based, so some acquired/dead tickers may not resolve; the unresolved list is
reported, never hidden.

Usage:
    python scripts/fetch_edgar_events.py --start 2021-01-01 --end 2026-06-30
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

UA = {"User-Agent": "agentic-trading-desk research (contact: ops@example.com)"}
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/{name}"

BLOCK_ITEMS = {"1.03", "3.01", "4.01", "4.02", "5.01", "2.04"}
CAUTION_ITEMS = {"1.01", "1.02", "2.01", "2.02", "2.05", "2.06", "3.02", "5.02"}


def _get_json(url: str, timeout: float = 30.0) -> dict:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def tier_for(items: list[str]) -> str:
    if any(i in BLOCK_ITEMS for i in items):
        return "BLOCK"
    if any(i in CAUTION_ITEMS for i in items):
        return "CAUTION"
    return "INFO"


def extract_events(sub: dict, ticker: str, start: str, end: str) -> list[dict]:
    """Pull 8-K/8-K/A rows in [start, end] from one submissions payload."""

    out: list[dict] = []

    def scan(recent: dict) -> None:
        forms = recent.get("form", [])
        n = len(forms)
        items_col = recent.get("items", [""] * n)
        for i in range(n):
            if forms[i] not in ("8-K", "8-K/A"):
                continue
            filed = recent["filingDate"][i]
            if not (start <= filed <= end):
                continue
            items = [x.strip() for x in (items_col[i] or "").split(",") if x.strip()]
            out.append(
                {
                    "ticker": ticker,
                    "filed": filed,
                    "accepted": recent["acceptanceDateTime"][i],
                    "form": forms[i],
                    "items": items,
                    "tier": tier_for(items),
                }
            )

    scan(sub["filings"]["recent"])
    # older filings live in extra pages; fetch only if the recent window does
    # not already reach back before our start date
    oldest = sub["filings"]["recent"]["filingDate"]
    if oldest and oldest[-1] > start:
        for extra in sub["filings"].get("files", []):
            try:
                page = _get_json(SUBMISSIONS_URL.format(name=extra["name"]))
            except Exception:  # noqa: BLE001 - page missing -> report less data
                continue
            scan(page)
            time.sleep(0.15)
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2021-01-01")
    p.add_argument("--end", default="2026-06-30")
    p.add_argument("--pit-dir", default="data/pit")
    p.add_argument("--sleep", type=float, default=0.22)
    args = p.parse_args(argv)
    pit = Path(args.pit_dir)
    universe = json.loads(
        (pit / f"universe_{args.start}_{args.end}.json").read_text(encoding="utf-8")
    )
    tickers = sorted(universe["intervals"])

    raw_map = _get_json(TICKER_MAP_URL)
    by_ticker = {v["ticker"].upper(): int(v["cik_str"]) for v in raw_map.values()}
    resolved = {t: by_ticker[t] for t in tickers if t in by_ticker}
    unresolved = [t for t in tickers if t not in by_ticker]
    print(f"CIK resolved: {len(resolved)}/{len(tickers)}; unresolved: {len(unresolved)}")

    events: list[dict] = []
    tally = {"BLOCK": 0, "CAUTION": 0, "INFO": 0}
    fetch_failures: list[str] = []
    for i, (ticker, cik) in enumerate(sorted(resolved.items()), 1):
        try:
            sub = _get_json(SUBMISSIONS_URL.format(name=f"CIK{cik:010d}.json"))
            evs = extract_events(sub, ticker, args.start, args.end)
        except Exception:  # noqa: BLE001 - record and continue; reported below
            fetch_failures.append(ticker)
            evs = []
        for e in evs:
            tally[e["tier"]] += 1
        events.extend(evs)
        if i % 100 == 0 or i == len(resolved):
            print(f"  {i}/{len(resolved)} companies; events={len(events)} {tally}")
        time.sleep(args.sleep)

    events.sort(key=lambda e: (e["accepted"], e["ticker"]))
    out_path = pit / "edgar_events.jsonl"
    with out_path.open("w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e, sort_keys=True) + "\n")
    summary = {
        "window": [args.start, args.end],
        "companies_resolved": len(resolved),
        "companies_unresolved": unresolved,
        "fetch_failures": fetch_failures,
        "events_total": len(events),
        "events_by_tier": tally,
        "mapping": {
            "BLOCK": sorted(BLOCK_ITEMS),
            "CAUTION": sorted(CAUTION_ITEMS),
        },
    }
    (pit / "edgar_events_summary.json").write_text(
        json.dumps(summary, indent=1), encoding="utf-8"
    )
    print(
        f"wrote {out_path} ({len(events)} events) | unresolved={len(unresolved)} "
        f"fetch_failures={len(fetch_failures)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
