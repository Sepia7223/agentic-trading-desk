"""Deterministic Demo-only multi-instrument opportunity analysis."""

from trading_desk.opportunity.config import (
    DemoCampaignConfiguration,
    DemoExplorationConfiguration,
    MarketUniverse,
    OpportunityEngineConfiguration,
)
from trading_desk.opportunity.engine import OpportunityEngine

__all__ = [
    "DemoCampaignConfiguration",
    "DemoExplorationConfiguration",
    "MarketUniverse",
    "OpportunityEngine",
    "OpportunityEngineConfiguration",
]
