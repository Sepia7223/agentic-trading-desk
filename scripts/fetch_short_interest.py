"""Fetch FINRA bi-monthly Equity Short Interest history (key-ready).

The strong short signal variant needs the real bi-monthly short-interest
records (positions, days-to-cover), not the daily short-volume proxy.
Anonymous access to this dataset stops at the 2022-09-15 partition; a free
registered FINRA API credential unlocks the full history.

Auth (per developer.finra.org): create an API credential (client id +
secret), then set BOTH env vars:
    FINRA_API_CLIENT_ID=...
    FINRA_API_CLIENT_SECRET=...
Token flow: client-credentials OAuth2 against ews.fip.finra.org, then
Bearer calls to api.finra.org. Without credentials the script still runs
anonymously and honestly reports the partition wall it hits.

Output: data/pit/shortinterest/{settlementDate}.jsonl (raw records,
append-never — each partition file is written once and skipped later).

Usage:
    python scripts/fetch_short_interest.py --list-partitions
    python scripts/fetch_short_interest.py --start 2019-01-01
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

TOKEN_URL = (
    "https://ews.fip.finra.org/fip/rest/ews/oauth2/access_token?grant_type=client_credentials"
)
DATA_URL = "https://api.finra.org/data/group/otcMarket/name/equityShortInterest"
PARTITIONS_URL = "https://api.finra.org/partitions/group/otcMarket/name/equityShortInterest"
PAGE_LIMIT = 5000
ANON_WALL_NOTE = (
    "anonymous access to this dataset historically ends around the "
    "2022-09-15 partition; set FINRA_API_CLIENT_ID/SECRET (free "
    "registration, see docs/strategy-research/UNBLOCK-ACTIONS.md) for full history"
)


def get_token(timeout: float = 30.0) -> str | None:
    """OAuth2 client-credentials token, or None when creds are absent."""

    client_id = os.environ.get("FINRA_API_CLIENT_ID", "")
    secret = os.environ.get("FINRA_API_CLIENT_SECRET", "")
    if not client_id or not secret:
        return None
    basic = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    req = urllib.request.Request(
        TOKEN_URL, method="POST", headers={"Authorization": f"Basic {basic}"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode())
    token = payload.get("access_token")
    return str(token) if token else None


def _headers(token: str | None) -> dict[str, str]:
    h = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def list_partitions(token: str | None, timeout: float = 60.0) -> list[str]:
    req = urllib.request.Request(PARTITIONS_URL, headers=_headers(token))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode())
    return sorted(extract_partition_dates(payload))


def extract_partition_dates(payload: object) -> list[str]:
    """Pull ISO settlement dates out of the partitions response (the shape
    has varied: list of dicts with 'partitions' or plain value lists)."""

    dates: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, str):
            if len(node) == 10 and node[4] == "-" and node[7] == "-":
                dates.add(node)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)

    walk(payload)
    return sorted(dates)


def fetch_partition(settlement_date: str, token: str | None, timeout: float = 120.0) -> list[dict]:
    """All records for one settlement date, offset-paged."""

    records: list[dict] = []
    offset = 0
    while True:
        body = json.dumps(
            {
                "limit": PAGE_LIMIT,
                "offset": offset,
                "compareFilters": [
                    {
                        "fieldName": "settlementDate",
                        "compareType": "EQUAL",
                        "fieldValue": settlement_date,
                    }
                ],
            }
        ).encode()
        req = urllib.request.Request(DATA_URL, data=body, method="POST", headers=_headers(token))
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            page = json.loads(resp.read().decode())
        if not isinstance(page, list) or not page:
            break
        records.extend(page)
        if len(page) < PAGE_LIMIT:
            break
        offset += PAGE_LIMIT
    return records


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", default="data/pit/shortinterest")
    p.add_argument("--start", default="2019-01-01")
    p.add_argument("--list-partitions", action="store_true")
    p.add_argument("--sleep", type=float, default=1.0)
    args = p.parse_args(argv)

    token = get_token()
    print(f"auth: {'registered credential' if token else 'ANONYMOUS (' + ANON_WALL_NOTE + ')'}")

    try:
        partitions = list_partitions(token)
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        print(f"partition listing failed: {exc}")
        return 1
    print(f"{len(partitions)} partitions; latest: {partitions[-1] if partitions else 'none'}")
    if args.list_partitions:
        for d in partitions:
            print(d)
        return 0

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    todo = [d for d in partitions if d >= args.start and not (out / f"{d}.jsonl").exists()]
    print(f"{len(todo)} partitions to fetch (>= {args.start}, missing locally)")
    fetched = 0
    for d in todo:
        try:
            records = fetch_partition(d, token)
        except urllib.error.HTTPError as exc:
            reason = "key required for this partition" if exc.code in (401, 403) else str(exc)
            print(f"{d}: HTTP {exc.code} - {reason}")
            if exc.code in (401, 403) and token is None:
                print(f"stopping at the anonymous wall; {ANON_WALL_NOTE}")
                break
            continue
        if not records:
            print(f"{d}: 0 records; skipped")
            continue
        path = out / f"{d}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")
        fetched += 1
        print(f"{d}: {len(records)} records")
        time.sleep(args.sleep)
    print(f"done: {fetched} partitions written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
