"""Abstract runtime ports for future integrations."""

from trading_desk.ports.ai import AIAnalysisProvider, AIAnalysisRequest, AIAnalysisResult
from trading_desk.ports.broker import Broker, PortfolioState
from trading_desk.ports.execution import BrokerExecutionPort
from trading_desk.ports.journal import (
    JournalIntegrityVerifier,
    JournalReader,
    JournalWriter,
    TradeJournal,
)
from trading_desk.ports.market_data import MarketDataProvider, MarketSnapshot

__all__ = [
    "AIAnalysisProvider",
    "AIAnalysisRequest",
    "AIAnalysisResult",
    "Broker",
    "BrokerExecutionPort",
    "JournalIntegrityVerifier",
    "JournalReader",
    "JournalWriter",
    "MarketDataProvider",
    "MarketSnapshot",
    "PortfolioState",
    "TradeJournal",
]
