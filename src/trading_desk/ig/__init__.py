"""Strictly read-only IG demo adapter."""

from trading_desk.ig.client import IGDemoClient
from trading_desk.ig.models import PriceResolution

__all__ = ["IGDemoClient", "PriceResolution"]
