"""Nasdaq Trader trading-halt feed: the cleanest hard-BLOCK signal available.

Parses the official halt RSS (nasdaqtrader.com). Reason codes beginning with T
(T1 "news pending", T2 "news released", T12 etc.) are news/regulatory halts;
LUDP-style volatility pauses are also surfaced. Parsing is namespace-tolerant
(matches element local names) so feed styling changes don't break the gate.
Fetch failures return None so the caller can fail CLOSED.
"""

from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

from trading_desk.newsfeed.models import HaltNotice

HALT_FEED_URL = "https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts"
_UA = {"User-Agent": "Mozilla/5.0 (agentic-trading-desk paper research)"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_halt_feed(xml_bytes: bytes) -> list[HaltNotice]:
    """Extract halt notices from the RSS payload (pure, unit-testable)."""

    root = ET.fromstring(xml_bytes)
    notices: list[HaltNotice] = []
    for item in root.iter():
        if _local(item.tag) != "item":
            continue
        fields: dict[str, str] = {}
        for child in item.iter():
            text = (child.text or "").strip()
            if text:
                fields[_local(child.tag)] = text
        symbol = fields.get("issuesymbol", "")
        reason = fields.get("reasoncode", "")
        if not symbol or not reason:
            continue
        halted_at: datetime | None = None
        stamp = fields.get("haltdate", "")
        if stamp:
            for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
                try:
                    halted_at = datetime.strptime(stamp, fmt).replace(tzinfo=UTC)
                    break
                except ValueError:
                    continue
        resumed = bool(fields.get("resumptiontradetime", ""))
        notices.append(
            HaltNotice(
                symbol=symbol.upper(),
                reason_code=reason.upper(),
                halted_at=halted_at,
                resumed=resumed,
            )
        )
    return notices


def fetch_halts(timeout: float = 15.0) -> list[HaltNotice] | None:
    """Fetch + parse the live feed; None on any failure (caller fails closed)."""

    try:
        req = urllib.request.Request(HALT_FEED_URL, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return parse_halt_feed(resp.read())
    except Exception:  # noqa: BLE001 - any transport/parse failure fails closed
        return None


def active_halt_symbols(notices: list[HaltNotice]) -> set[str]:
    """Symbols currently halted (no resumption trade time yet)."""

    return {n.symbol for n in notices if not n.resumed}
