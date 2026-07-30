"""Paper-trading stack: simulated broker + persistent state + health producers.

Runs the production pre-trade pipeline against real market data with simulated
execution, so the strategy accumulates the reviewer-required months of paper
evidence before any real order exists. DEMO/PAPER ONLY: this package contains
no live-broker connectivity and grants no live authority.
"""

from trading_desk.paper.broker import Fill, PaperBroker, PaperOrder, Position
from trading_desk.paper.health import build_account_state, build_system_health
from trading_desk.paper.state import PaperState, load_state, save_state

__all__ = [
    "Fill",
    "PaperBroker",
    "PaperOrder",
    "PaperState",
    "Position",
    "build_account_state",
    "build_system_health",
    "load_state",
    "save_state",
]
