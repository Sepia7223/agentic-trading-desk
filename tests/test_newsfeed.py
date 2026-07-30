"""Tests for the multi-source live news feed (fixtures; no network)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from trading_desk.newsfeed.alpaca_news import parse_news_payload
from trading_desk.newsfeed.combined import CombinedNewsReader
from trading_desk.newsfeed.edgar_live import parse_current_atom, symbols_with_fresh_8k
from trading_desk.newsfeed.halts import active_halt_symbols, parse_halt_feed
from trading_desk.pretrade.models import NewsStatus

NOW = datetime(2026, 7, 22, 15, 0, tzinfo=UTC)

HALT_RSS = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:ndaq="http://www.nasdaqtrader.com/">
  <channel>
    <title>Trading Halts</title>
    <item>
      <title>ACME halted</title>
      <ndaq:IssueSymbol>ACME</ndaq:IssueSymbol>
      <ndaq:ReasonCode>T1</ndaq:ReasonCode>
      <ndaq:HaltDate>07/22/2026</ndaq:HaltDate>
      <ndaq:ResumptionTradeTime></ndaq:ResumptionTradeTime>
    </item>
    <item>
      <title>OLDC resumed</title>
      <ndaq:IssueSymbol>OLDC</ndaq:IssueSymbol>
      <ndaq:ReasonCode>LUDP</ndaq:ReasonCode>
      <ndaq:HaltDate>07/22/2026</ndaq:HaltDate>
      <ndaq:ResumptionTradeTime>10:15:00</ndaq:ResumptionTradeTime>
    </item>
  </channel>
</rss>"""

EDGAR_ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Latest Filings</title>
  <entry>
    <title>8-K - Acme Corp (0001234567) (Filer)</title>
    <updated>2026-07-22T09:30:00-04:00</updated>
    <link href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&amp;accession_number=0001234567-26-000042"/>
  </entry>
  <entry>
    <title>10-Q - Other Corp (0007654321) (Filer)</title>
    <updated>2026-07-22T14:00:00-04:00</updated>
    <link href="https://example.com"/>
  </entry>
  <entry>
    <title>8-K - Stale Corp (0009999999) (Filer)</title>
    <updated>2026-07-10T09:00:00-04:00</updated>
    <link href="https://example.com"/>
  </entry>
</feed>"""

# Headline timestamps are RELATIVE to the real clock: the combined reader
# assesses recency against datetime.now(UTC), so fixed dates rot into
# staleness and flip BLOCK->CLEAR days later (that bug shipped once).
_RECENT = datetime.now(UTC) - timedelta(hours=2)
ALPACA_JSON = {
    "news": [
        {
            "id": 1,
            "headline": "Acme agrees to merger with MegaCorp",
            "created_at": _RECENT.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "symbols": ["ACME"],
            "url": "https://example.com/1",
        },
        {
            "id": 2,
            "headline": "Quiet product update from Acme",
            "created_at": (_RECENT - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "symbols": ["ACME"],
            "url": "https://example.com/2",
        },
    ]
}


# -------------------------------------------------------------------- parsers


def test_halt_feed_parsing_and_active_set():
    notices = parse_halt_feed(HALT_RSS)
    assert len(notices) == 2
    active = active_halt_symbols(notices)
    assert active == {"ACME"}  # OLDC has a resumption time
    t1 = next(n for n in notices if n.symbol == "ACME")
    assert t1.is_news_related and t1.halted_at is not None


def test_edgar_current_atom_parsing_and_freshness_window():
    events = parse_current_atom(EDGAR_ATOM)
    forms = {e.form for e in events}
    assert forms == {"8-K"}  # the 10-Q is excluded
    assert {e.cik for e in events} == {1234567, 9999999}
    fresh = symbols_with_fresh_8k(
        events,
        {1234567: "ACME", 9999999: "STAL"},
        now=NOW,
        window_hours=72,
    )
    assert fresh == {"ACME"}  # STAL's filing is 12 days old
    acme = next(e for e in events if e.cik == 1234567)
    assert acme.accession == "0001234567-26-000042"


def test_alpaca_payload_parsing():
    items = parse_news_payload(ALPACA_JSON)
    assert len(items) == 2
    assert items[0].symbols == ("ACME",)
    assert items[0].published_at is not None
    assert items[0].published_at.tzinfo is not None


# ------------------------------------------------------------ combined reader


def make_reader(
    halted: set[str] | None,
    fresh: set[str] | None,
) -> CombinedNewsReader:
    reader = CombinedNewsReader()
    reader._feeds_loaded = True  # noqa: SLF001 - test injects shared state
    reader._halted = halted  # noqa: SLF001
    reader._fresh_8k = fresh  # noqa: SLF001
    return reader


def test_combined_halt_wins_over_everything(monkeypatch):
    reader = make_reader({"ACME"}, set())
    result = reader.read("acme")
    assert result.status is NewsStatus.BLOCK
    assert "trading_halt" in result.matched_keywords


def test_combined_uses_alpaca_headlines_and_keyword_tiers(monkeypatch):
    from trading_desk.newsfeed import alpaca_news as mod

    monkeypatch.setattr(mod, "fetch_news", lambda s, **k: parse_news_payload(ALPACA_JSON))
    monkeypatch.setattr(
        "trading_desk.newsfeed.combined.alpaca_news.fetch_news",
        lambda s, **k: parse_news_payload(ALPACA_JSON),
    )
    reader = make_reader(set(), set())
    result = reader.read("ACME")
    assert result.status is NewsStatus.BLOCK  # "merger" is a BLOCK keyword
    assert "merger" in result.matched_keywords


def test_combined_fresh_8k_escalates_clear_to_caution(monkeypatch):
    quiet = {"news": [dict(ALPACA_JSON["news"][1])]}  # only the quiet headline
    monkeypatch.setattr(
        "trading_desk.newsfeed.combined.alpaca_news.fetch_news",
        lambda s, **k: parse_news_payload(quiet),
    )
    reader = make_reader(set(), {"ACME"})
    result = reader.read("ACME")
    assert result.status is NewsStatus.CAUTION
    assert "fresh_8k" in result.matched_keywords


def test_combined_total_failure_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        "trading_desk.newsfeed.combined.alpaca_news.fetch_news",
        lambda s, **k: None,
    )
    monkeypatch.setattr(
        "trading_desk.newsfeed.combined.read_news",
        lambda s, **k: __import__(
            "trading_desk.pretrade.models", fromlist=["NewsAssessment"]
        ).NewsAssessment(symbol=s, status=NewsStatus.UNAVAILABLE),
    )
    reader = make_reader(None, None)  # halt + EDGAR feeds down too
    result = reader.read("ACME")
    assert result.status is NewsStatus.UNAVAILABLE  # pipeline will reject


def test_combined_stale_8k_does_not_escalate(monkeypatch):
    monkeypatch.setattr(
        "trading_desk.newsfeed.combined.alpaca_news.fetch_news",
        lambda s, **k: parse_news_payload({"news": [dict(ALPACA_JSON["news"][1])]}),
    )
    reader = make_reader(set(), set())  # no fresh 8-K for ACME
    result = reader.read("ACME")
    assert result.status is NewsStatus.CLEAR
