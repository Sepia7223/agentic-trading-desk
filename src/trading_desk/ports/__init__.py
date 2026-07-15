"""Abstract runtime ports for future integrations."""

from trading_desk.ports.ai import AIAnalysisProvider, AIAnalysisRequest, AIAnalysisResult
from trading_desk.ports.broker import Broker, PortfolioState
from trading_desk.ports.journal import JournalEntry, TradeJournal
from trading_desk.ports.market_data import MarketDataProvider, MarketSnapshot

__all__ = [
    "AIAnalysisProvider",
    "AIAnalysisRequest",
    "AIAnalysisResult",
    "Broker",
    "JournalEntry",
    "MarketDataProvider",
    "MarketSnapshot",
    "PortfolioState",
    "TradeJournal",
]
