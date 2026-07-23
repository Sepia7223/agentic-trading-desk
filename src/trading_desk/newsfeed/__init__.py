"""Multi-source live news for the pre-trade gate (blueprint Phase 0).

Sources, per the information-edge blueprint: Nasdaq Trader halt feed (a
"news pending" halt is the cleanest hard-BLOCK that exists), SEC EDGAR current
8-K filings (acceptance-time keyed, same discipline as the backtest ledger),
and the Benzinga wire via the Alpaca News API (adapter-wrapped; dormant until
API keys are configured). Yahoo RSS is demoted to fallback. All sources feed
the existing pretrade news gate; total source failure yields UNAVAILABLE,
which the pipeline treats as a rejection — never trade unread.
"""

from trading_desk.newsfeed.combined import CombinedNewsReader
from trading_desk.newsfeed.models import FilingEvent, HaltNotice, NewsItem

__all__ = ["CombinedNewsReader", "FilingEvent", "HaltNotice", "NewsItem"]
