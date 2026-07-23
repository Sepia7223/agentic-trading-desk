"""SEC EDGAR current-filings poller (live twin of the backtest 8-K ledger).

Polls the free getcurrent Atom feed for freshly-accepted 8-K filings, maps CIK
to ticker via the SEC company map, and reports which universe symbols have a
recent filing. The current feed does not carry item codes, so live tiering is
conservative: ANY fresh 8-K raises CAUTION for the symbol (the backtest ledger
retains item-level BLOCK/CAUTION fidelity; live item lookup is a documented
v2). Fetch failures return None so the caller can fail closed.
"""

from __future__ import annotations

import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

from trading_desk.newsfeed.models import FilingEvent

CURRENT_8K_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K"
    "&company=&dateb=&owner=include&count=100&output=atom"
)
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
# SEC requires a contact-bearing User-Agent on www.sec.gov endpoints
_UA = {"User-Agent": "agentic-trading-desk research ops@itsolutions.cw"}
_ATOM = "{http://www.w3.org/2005/Atom}"


def parse_current_atom(xml_bytes: bytes) -> list[FilingEvent]:
    """Extract filing events from the getcurrent Atom payload (pure)."""

    root = ET.fromstring(xml_bytes)
    events: list[FilingEvent] = []
    for entry in root.iter(f"{_ATOM}entry"):
        title = (entry.findtext(f"{_ATOM}title") or "").strip()
        updated = (entry.findtext(f"{_ATOM}updated") or "").strip()
        link_el = entry.find(f"{_ATOM}link")
        href = link_el.get("href", "") if link_el is not None else ""
        # title form: "8-K - Company Name (0001234567) (Filer)"
        form = title.split(" - ", 1)[0].strip() if " - " in title else title
        cik = 0
        if "(" in title:
            for chunk in title.split("("):
                digits = chunk.split(")", 1)[0].strip()
                if digits.isdigit() and len(digits) >= 6:
                    cik = int(digits)
                    break
        accepted: datetime | None = None
        if updated:
            try:
                accepted = datetime.fromisoformat(updated).astimezone(UTC)
            except ValueError:
                accepted = None
        accession = ""
        if "accession_number=" in href:
            accession = href.split("accession_number=", 1)[1].split("&", 1)[0]
        if cik and form.startswith("8-K"):
            events.append(
                FilingEvent(
                    cik=cik,
                    form=form,
                    title=title,
                    accepted=accepted,
                    accession=accession,
                )
            )
    return events


def fetch_current_8ks(timeout: float = 20.0) -> list[FilingEvent] | None:
    try:
        req = urllib.request.Request(CURRENT_8K_URL, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return parse_current_atom(resp.read())
    except Exception:  # noqa: BLE001 - fail closed at the caller
        return None


def fetch_cik_to_ticker(timeout: float = 30.0) -> dict[int, str] | None:
    """CIK -> primary ticker from the SEC company map (session-cached upstream)."""

    try:
        req = urllib.request.Request(TICKER_MAP_URL, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = json.loads(resp.read().decode())
        out: dict[int, str] = {}
        for row in raw.values():
            cik = int(row["cik_str"])
            out.setdefault(cik, str(row["ticker"]).upper())
        return out
    except Exception:  # noqa: BLE001 - fail closed at the caller
        return None


def symbols_with_fresh_8k(
    events: list[FilingEvent],
    cik_to_ticker: dict[int, str],
    *,
    now: datetime,
    window_hours: float = 72.0,
) -> set[str]:
    out: set[str] = set()
    for ev in events:
        ticker = cik_to_ticker.get(ev.cik)
        if ticker is None:
            continue
        if ev.accepted is None:
            out.add(ticker)  # unknown timing: conservative inclusion
            continue
        age = (now - ev.accepted).total_seconds() / 3600.0
        if 0 <= age <= window_hours:
            out.add(ticker)
    return out
