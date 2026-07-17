"""Lifecycle-owned construction of the dedicated IG Demo close adapter."""

from trading_desk.config import AppSettings
from trading_desk.ig.position_exit import IGDemoPositionExitAdapter


def create_demo_position_exit_adapter(settings: AppSettings) -> IGDemoPositionExitAdapter:
    """Build the only broker mutation adapter available to lifecycle orchestration."""
    return IGDemoPositionExitAdapter(settings)
