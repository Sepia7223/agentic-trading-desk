"""Combined multi-source news reader for the pre-trade gate.

Per-symbol assessment order (strictest wins):
  1. ACTIVE TRADING HALT  -> BLOCK, unconditionally.
  2. Headlines (Alpaca/Benzinga when keyed, else Yahoo RSS fallback) -> the
     existing keyword-tier assessment (BLOCK/CAUTION/CLEAR).
  3. FRESH 8-K on EDGAR   -> escalates CLEAR to CAUTION (item codes are not in
     the live feed; conservative tiering, documented).
If every source fails, the result is UNAVAILABLE — and the pipeline already
treats unread news as a rejection, so total feed failure fails CLOSED.

Session-scoped: halt list, EDGAR current filings, and the CIK->ticker map are
fetched once per session and reused across symbols.
"""

from __future__ import annotations

from datetime import UTC, datetime

from trading_desk.newsfeed import alpaca_news
from trading_desk.newsfeed.edgar_live import (
    fetch_cik_to_ticker,
    fetch_current_8ks,
    symbols_with_fresh_8k,
)
from trading_desk.newsfeed.halts import active_halt_symbols, fetch_halts
from trading_desk.pretrade.models import NewsAssessment, NewsStatus
from trading_desk.pretrade.news_gate import assess_headlines, read_news


class CombinedNewsReader:
    """One instance per session; fetches shared feeds once, lazily."""

    def __init__(self, *, recency_hours: float = 48.0) -> None:
        self.recency_hours = recency_hours
        self._halted: set[str] | None = None
        self._fresh_8k: set[str] | None = None
        self._feeds_loaded = False
        self.sources_up: dict[str, bool] = {}

    # ------------------------------------------------------------ shared feeds

    def _load_shared(self) -> None:
        if self._feeds_loaded:
            return
        self._feeds_loaded = True
        halts = fetch_halts()
        self.sources_up["halts"] = halts is not None
        self._halted = active_halt_symbols(halts) if halts is not None else None

        events = fetch_current_8ks()
        cik_map = fetch_cik_to_ticker() if events else None
        self.sources_up["edgar_current"] = events is not None and cik_map is not None
        if events is not None and cik_map is not None:
            self._fresh_8k = symbols_with_fresh_8k(events, cik_map, now=datetime.now(UTC))
        else:
            self._fresh_8k = None

    # ---------------------------------------------------------------- per-name

    def read(self, symbol: str) -> NewsAssessment:
        self._load_shared()
        now = datetime.now(UTC)
        symbol = symbol.upper()

        # 1) active halt: unconditional BLOCK
        if self._halted is not None and symbol in self._halted:
            return NewsAssessment(
                symbol=symbol,
                status=NewsStatus.BLOCK,
                matched_keywords=("trading_halt",),
                checked_at=now,
            )

        # 2) headlines: Alpaca wire when keyed, else Yahoo fallback
        assessment: NewsAssessment
        items = alpaca_news.fetch_news(symbol)
        if items is not None:
            self.sources_up["alpaca"] = True
            headlines = [(i.headline, i.published_at) for i in items]
            assessment = assess_headlines(
                symbol, headlines, now=now, recency_hours=self.recency_hours
            )
        else:
            self.sources_up.setdefault("alpaca", False)
            assessment = read_news(symbol, recency_hours=self.recency_hours)

        # if headlines AND the halt feed both failed, we are flying blind
        if (
            assessment.status is NewsStatus.UNAVAILABLE
            and self._halted is None
            and self._fresh_8k is None
        ):
            return assessment  # UNAVAILABLE -> pipeline rejects (fail closed)

        # 3) fresh 8-K escalates CLEAR -> CAUTION (conservative live tiering)
        if (
            self._fresh_8k is not None
            and symbol in self._fresh_8k
            and assessment.status in (NewsStatus.CLEAR, NewsStatus.UNAVAILABLE)
        ):
            return NewsAssessment(
                symbol=symbol,
                status=NewsStatus.CAUTION,
                headlines=assessment.headlines,
                matched_keywords=(*assessment.matched_keywords, "fresh_8k"),
                checked_at=now,
            )
        return assessment
