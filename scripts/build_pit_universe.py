"""Build a point-in-time (PIT) S&P 500 membership table from Wikipedia.

Reviewer gate #1 for the equity strategy: replace the survivor universe with
point-in-time constituents (including names later delisted/acquired). Wikipedia's
"List of S&P 500 companies" page carries (a) the current constituent table with
GICS sectors and (b) a dated changes table (additions/removals) going back years.
Walking the changes backwards from the current membership reconstructs who was in
the index on any historical date.

Outputs (data/pit/, gitignored):
    membership.json  — {"as_of": ..., "events": [{date, added:[], removed:[]}, ...],
                        "current": [...], "sectors": {ticker: sector}}
    universe_<start>_<end>.json — every ticker that was a member at any point in
                        [start, end], with its membership intervals.

Honest-coverage principle: the later fetch step reports which historical members
have no retrievable price data (delisted and unavailable), so residual
survivorship bias is MEASURED, not silent.

Usage:
    python scripts/build_pit_universe.py --start 2021-01-01 --end 2026-06-30
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from datetime import date, datetime
from pathlib import Path

from lxml import html as lhtml

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def fetch_page() -> bytes:
    req = urllib.request.Request(WIKI_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read()


def _clean(cell) -> str:
    return " ".join(cell.text_content().split()).strip()


def parse_current(tree) -> tuple[list[str], dict[str, str]]:
    table = tree.get_element_by_id("constituents")
    tickers: list[str] = []
    sectors: dict[str, str] = {}
    for row in table.xpath(".//tbody/tr")[1:]:
        cells = row.xpath("./td")
        if len(cells) < 3:
            continue
        sym = _clean(cells[0]).replace(".", "-")  # BRK.B -> BRK-B (Yahoo style)
        sector = _clean(cells[2])
        if sym:
            tickers.append(sym)
            sectors[sym] = sector
    return tickers, sectors


_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June",
         "July", "August", "September", "October", "November", "December"]
    )
}


def _parse_date(text: str) -> date | None:
    m = re.match(r"(\w+) (\d{1,2}), (\d{4})", text)
    if not m or m.group(1) not in _MONTHS:
        return None
    return date(int(m.group(3)), _MONTHS[m.group(1)], int(m.group(2)))


def parse_changes(tree) -> list[dict]:
    """Return [{date, added: [tickers], removed: [tickers]}] newest-first."""
    table = tree.get_element_by_id("changes")
    events: dict[str, dict] = {}
    current_date: date | None = None
    for row in table.xpath(".//tbody/tr"):
        cells = row.xpath("./td")
        if not cells:
            continue
        # The date cell has rowspan when several changes share a date; when absent,
        # the row belongs to the previous date.
        offset = 0
        maybe_date = _parse_date(_clean(cells[0]))
        if maybe_date is not None:
            current_date = maybe_date
            offset = 1
        if current_date is None:
            continue
        # After the optional date cell: added_ticker, added_name, removed_ticker,
        # removed_name, reason (some cells may be empty).
        def cell(i: int, cells=cells, offset=offset) -> str:
            return _clean(cells[offset + i]) if offset + i < len(cells) else ""

        added = cell(0).replace(".", "-")
        removed = cell(2).replace(".", "-")
        key = current_date.isoformat()
        ev = events.setdefault(key, {"date": key, "added": [], "removed": []})
        if added and re.fullmatch(r"[A-Z0-9-]{1,7}", added):
            ev["added"].append(added)
        if removed and re.fullmatch(r"[A-Z0-9-]{1,7}", removed):
            ev["removed"].append(removed)
    return sorted(events.values(), key=lambda e: e["date"], reverse=True)


def membership_over(
    current: list[str], events: list[dict], start: date, end: date
) -> dict[str, list[list[str]]]:
    """Roll membership backwards from today; return {ticker: [[from, to], ...]}
    intervals clipped to [start, end] for tickers with any overlap."""

    members = set(current)
    today = date.today()
    # walk events newest->oldest, recording state between event dates
    intervals: dict[str, list[list[date]]] = {}

    def open_interval(tk: str, upto: date):
        intervals.setdefault(tk, []).append([None, upto])  # from unknown yet

    def close_interval(tk: str, frm: date):
        for iv in intervals.get(tk, []):
            if iv[0] is None:
                iv[0] = frm
                return

    for tk in members:
        open_interval(tk, today)
    for ev in events:  # newest first
        d = date.fromisoformat(ev["date"])
        # inverse operations going backwards: an ADD on date d means before d the
        # ticker was NOT a member; a REMOVE on d means before d it WAS a member.
        for tk in ev["added"]:
            if tk in members:
                members.discard(tk)
                close_interval(tk, d)
        for tk in ev["removed"]:
            if tk not in members:
                members.add(tk)
                open_interval(tk, d)
        if d < start:
            break
    horizon = min(ev and date.fromisoformat(events[-1]["date"]) or start, start)
    for tk in members:  # still open at the oldest event -> member since horizon
        close_interval(tk, horizon)

    out: dict[str, list[list[str]]] = {}
    for tk, ivs in intervals.items():
        clipped = []
        for frm, to in ivs:
            frm = frm or horizon
            lo, hi = max(frm, start), min(to, end)
            if lo <= hi:
                clipped.append([lo.isoformat(), hi.isoformat()])
        if clipped:
            out[tk] = sorted(clipped)
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2021-01-01")
    p.add_argument("--end", default="2026-06-30")
    p.add_argument("--out", default="data/pit")
    args = p.parse_args(argv)
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    tree = lhtml.fromstring(fetch_page())
    current, sectors = parse_current(tree)
    events = parse_changes(tree)
    in_window = [e for e in events if e["date"] >= args.start]
    print(f"current members: {len(current)}")
    print(f"change events total: {len(events)} (oldest {events[-1]['date']}); "
          f"{len(in_window)} in window")

    member_intervals = membership_over(current, events, start, end)
    ever = sorted(member_intervals)
    delisted_or_removed = [t for t in ever if t not in set(current)]
    print(f"PIT universe {args.start}..{args.end}: {len(ever)} tickers ever members")
    print(f"  of which NOT current members (removed/delisted/acquired): "
          f"{len(delisted_or_removed)}")
    print(f"  sample removed: {delisted_or_removed[:15]}")

    (out / "membership.json").write_text(
        json.dumps(
            {
                "as_of": datetime.now().date().isoformat(),
                "source": WIKI_URL,
                "current": current,
                "sectors": sectors,
                "events": events,
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    (out / f"universe_{args.start}_{args.end}.json").write_text(
        json.dumps(
            {
                "start": args.start,
                "end": args.end,
                "intervals": member_intervals,
                "not_current": delisted_or_removed,
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"wrote {out}/membership.json and universe_{args.start}_{args.end}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
