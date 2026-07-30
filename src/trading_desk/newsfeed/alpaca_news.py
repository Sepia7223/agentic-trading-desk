"""Alpaca News API adapter (Benzinga wire) — primary headline source when keyed.

Free-beta REST endpoint; requires APCA_API_KEY_ID / APCA_API_SECRET_KEY in the
environment. The adapter is deliberately thin and interface-shaped: if Alpaca's
beta pricing changes, the same NewsItem schema can be fed from Massive's
Benzinga add-on without touching the gate. Without keys, callers skip this
source (the combined reader then relies on halts + EDGAR + Yahoo fallback).
Parsing is a pure function over the JSON payload (fixture-tested offline).
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from trading_desk.newsfeed.models import NewsItem

NEWS_URL = "https://data.alpaca.markets/v1beta1/news"


def credentials_present() -> bool:
    return bool(os.environ.get("APCA_API_KEY_ID") and os.environ.get("APCA_API_SECRET_KEY"))


def parse_news_payload(payload: dict) -> list[NewsItem]:
    """Pure parser for the /v1beta1/news JSON body."""

    items: list[NewsItem] = []
    for row in payload.get("news", []):
        headline = str(row.get("headline", "")).strip()
        if not headline:
            continue
        published: datetime | None = None
        stamp = str(row.get("created_at", "")).strip()
        if stamp:
            try:
                published = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(UTC)
            except ValueError:
                published = None
        items.append(
            NewsItem(
                source="alpaca-benzinga",
                headline=headline,
                symbols=tuple(str(s).upper() for s in row.get("symbols", [])),
                published_at=published,
                url=str(row.get("url", "") or ""),
                item_id=str(row.get("id", "") or ""),
            )
        )
    return items


def fetch_news(
    symbol: str,
    *,
    limit: int = 25,
    timeout: float = 15.0,
) -> list[NewsItem] | None:
    """Latest headlines for one symbol; None on failure or missing keys."""

    if not credentials_present():
        return None
    query = urllib.parse.urlencode({"symbols": symbol, "limit": str(limit)})
    req = urllib.request.Request(
        f"{NEWS_URL}?{query}",
        headers={
            "APCA-API-KEY-ID": os.environ["APCA_API_KEY_ID"],
            "APCA-API-SECRET-KEY": os.environ["APCA_API_SECRET_KEY"],
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return parse_news_payload(json.loads(resp.read().decode()))
    except Exception:  # noqa: BLE001 - fail closed at the caller
        return None
