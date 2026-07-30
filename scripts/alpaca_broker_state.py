#!/usr/bin/env python3
"""Print the broker-realistic Alpaca paper-account state (read-only, no orders)."""

from __future__ import annotations

import asyncio
import json

from trading_desk.brokers.alpaca_paper import AlpacaBroker


def main() -> int:
    state = asyncio.run(AlpacaBroker().get_portfolio_state())
    print(json.dumps(dict(state), indent=2, default=str))
    return 0 if state["is_known"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
