#!/usr/bin/env python3
"""Backward-compatible wrapper for trading_desk.strategy.indicators."""

# ruff: noqa: E402,I001

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_desk.strategy.indicators import main

if __name__ == "__main__":
    raise SystemExit(main())
