"""Pre-trade news gate: read recent headlines for a symbol before any order.

Implements the mandate that news is read before every trade/signal. Fetches the
symbol's latest headlines (Yahoo Finance RSS — keyless, broad coverage; source is
pluggable) and screens them with a two-tier keyword taxonomy:

    BLOCK   — halt/bankruptcy/merger/investigation-class events: the momentum
              signal is unreliable and squeeze/gap risk is extreme -> the
              pipeline REJECTS the trade (NEWS_OR_CORPORATE_EVENT).
    CAUTION — earnings/guidance/analyst/legal-class events: elevated event risk
              -> the pipeline rejects new SHORTS (configurable) and records a
              warning on longs.
    CLEAR   — no risk-tier headlines inside the recency window.
    UNAVAILABLE — the source could not be read. The pipeline treats an unread
              news state as a REJECTION (a trade may not proceed unread), which
              also fails closed on network errors.

HONEST LIMITATION: there is no free point-in-time news archive, so this gate
applies to LIVE/PAPER trading only. Backtests cannot include it, and therefore
slightly overstate tradable opportunities relative to live behaviour.

RESEARCH/OPERATIONS tooling: grants no execution authority by itself.
"""

from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

from trading_desk.pretrade.models import NewsAssessment, NewsStatus

RSS_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"

BLOCK_KEYWORDS: tuple[str, ...] = (
    "halt",
    "halted",
    "bankruptcy",
    "chapter 11",
    "delist",
    "delisting",
    "merger",
    "acquisition",
    "acquires",
    "to acquire",
    "buyout",
    "take-private",
    "going private",
    "tender offer",
    "fraud",
    "investigation",
    "probe",
    "restatement",
    "restates",
    "sec charges",
    "short squeeze",
    "receivership",
    "default",
    "insolvency",
    "trading suspended",
)
CAUTION_KEYWORDS: tuple[str, ...] = (
    "earnings",
    "guidance",
    "outlook cut",
    "downgrade",
    "upgrade",
    "offering",
    "dilution",
    "secondary",
    "dividend",
    "split",
    "fda",
    "recall",
    "resigns",
    "resignation",
    "steps down",
    "lawsuit",
    "settlement",
    "layoffs",
    "restructuring",
    "activist",
    "strike",
)


def _fetch_rss(symbol: str, timeout: float) -> list[tuple[str, datetime | None]]:
    url = RSS_URL.format(symbol=symbol)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        tree = ET.fromstring(resp.read())
    items: list[tuple[str, datetime | None]] = []
    for item in tree.iter("item"):
        title = (item.findtext("title") or "").strip()
        pub = item.findtext("pubDate")
        when: datetime | None = None
        if pub:
            try:
                when = parsedate_to_datetime(pub)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=UTC)
            except (TypeError, ValueError):
                when = None
        if title:
            items.append((title, when))
    return items


def assess_headlines(
    symbol: str,
    headlines: list[tuple[str, datetime | None]],
    *,
    now: datetime,
    recency_hours: float = 48.0,
) -> NewsAssessment:
    """Pure classification of already-fetched headlines (unit-testable)."""

    cutoff = now - timedelta(hours=recency_hours)
    recent: list[str] = []
    block_hits: list[str] = []
    caution_hits: list[str] = []
    for title, when in headlines:
        if when is not None and when < cutoff:
            continue
        recent.append(title)
        low = title.lower()
        for kw in BLOCK_KEYWORDS:
            if kw in low:
                block_hits.append(kw)
        for kw in CAUTION_KEYWORDS:
            if kw in low:
                caution_hits.append(kw)
    if block_hits:
        status = NewsStatus.BLOCK
        matched = tuple(dict.fromkeys(block_hits))
    elif caution_hits:
        status = NewsStatus.CAUTION
        matched = tuple(dict.fromkeys(caution_hits))
    else:
        status = NewsStatus.CLEAR
        matched = ()
    return NewsAssessment(
        symbol=symbol,
        status=status,
        headlines=tuple(recent[:20]),
        matched_keywords=matched,
        checked_at=now,
    )


def read_news(symbol: str, *, recency_hours: float = 48.0, timeout: float = 15.0) -> NewsAssessment:
    """Fetch + classify. Fails CLOSED: any fetch problem returns UNAVAILABLE,
    which the pipeline treats as a rejection (never trade unread)."""

    now = datetime.now(UTC)
    try:
        headlines = _fetch_rss(symbol, timeout)
    except Exception:  # noqa: BLE001 - any transport/parse failure fails closed
        return NewsAssessment(
            symbol=symbol,
            status=NewsStatus.UNAVAILABLE,
            checked_at=now,
        )
    return assess_headlines(symbol, headlines, now=now, recency_hours=recency_hours)
