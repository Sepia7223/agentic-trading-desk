"""Multiplicity-honest validation: trial registry + Deflated Sharpe Ratio.

Every backtest configuration ever run is recorded in an append-only registry;
the Deflated Sharpe Ratio then asks whether a selected strategy's Sharpe clears
the maximum expected by pure luck across that many trials. A DSR quoted with an
understated trial count is worse than no DSR — the registry exists so N is a
recorded fact, not a memory.
"""

from trading_desk.trials.dsr import (
    deflated_sharpe_ratio,
    expected_max_sharpe,
    probabilistic_sharpe_ratio,
)
from trading_desk.trials.registry import TrialRecord, TrialRegistry

__all__ = [
    "TrialRecord",
    "TrialRegistry",
    "deflated_sharpe_ratio",
    "expected_max_sharpe",
    "probabilistic_sharpe_ratio",
]
