"""Alpaca paper-account broker adapter — read-only PortfolioState, no order authority.

Implements the provider-neutral ``ports.broker.Broker`` protocol against a real
Alpaca *paper* brokerage account (``GET /v2/account`` + ``GET /v2/positions``).
This gives the desk a BROKER-REALISTIC view of account state — real cash,
market value, and open-position count as a live brokerage engine reports them —
to run ALONGSIDE the internal simulated ``PaperBroker``.

It has NO order authority: the port exposes only reads, so nothing here can
place, modify, or cancel an order. When keys are absent or the API is
unreachable it returns an explicit unknown state (``is_known=False``) so callers
fail closed rather than trust absent data. Parsing is a pure function over the
JSON bodies (fixture-tested offline).
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.request
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from trading_desk.ports.broker import PortfolioState

ACCOUNT_URL = "https://paper-api.alpaca.markets/v2/account"
POSITIONS_URL = "https://paper-api.alpaca.markets/v2/positions"


def credentials_present() -> bool:
    return bool(os.environ.get("APCA_API_KEY_ID") and os.environ.get("APCA_API_SECRET_KEY"))


def unknown_state() -> PortfolioState:
    """Explicit fail-closed state: nothing is trusted, is_known is False."""

    return PortfolioState(
        account_id="",
        currency="USD",
        cash_available=Decimal("0"),
        market_value=Decimal("0"),
        open_position_count=0,
        is_known=False,
    )


def parse_portfolio_state(account: dict, positions: list) -> PortfolioState:
    """Pure parser mapping Alpaca account+positions JSON to a PortfolioState.

    Fails closed (unknown state) when the account body lacks the fields that
    make it trustworthy, so a malformed or restricted account is never read as
    healthy zero-balance data.
    """

    try:
        cash = Decimal(str(account["cash"]))
        market_value = Decimal(str(account.get("long_market_value") or "0"))
    except (KeyError, TypeError, InvalidOperation):
        return unknown_state()
    return PortfolioState(
        account_id=str(account.get("account_number") or account.get("id") or ""),
        currency=str(account.get("currency") or "USD"),
        cash_available=cash,
        market_value=market_value,
        open_position_count=len(positions),
        is_known=True,
    )


class AlpacaBroker:
    """Read-only view of an Alpaca (paper) brokerage account.

    Conforms to the ``Broker`` port. Reads only — no order authority.
    """

    def __init__(
        self,
        *,
        account_url: str = ACCOUNT_URL,
        positions_url: str = POSITIONS_URL,
        timeout: float = 15.0,
    ) -> None:
        self._account_url = account_url
        self._positions_url = positions_url
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": os.environ.get("APCA_API_KEY_ID", ""),
            "APCA-API-SECRET-KEY": os.environ.get("APCA_API_SECRET_KEY", ""),
        }

    def _get_json(self, url: str) -> object | None:
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                payload: object = json.loads(resp.read().decode())
                return payload
        except Exception:  # noqa: BLE001 - fail closed at the caller
            return None

    async def get_portfolio_state(self) -> PortfolioState:
        """Return known Alpaca paper-account state, or an explicit unknown state."""

        if not credentials_present():
            return unknown_state()
        account = await asyncio.to_thread(self._get_json, self._account_url)
        if not isinstance(account, dict):
            return unknown_state()
        positions = await asyncio.to_thread(self._get_json, self._positions_url)
        if not isinstance(positions, list):
            positions = []
        return parse_portfolio_state(account, positions)


if TYPE_CHECKING:
    from trading_desk.ports.broker import Broker

    # Compile-time guarantee that the adapter satisfies the read-only port.
    _conforms: Broker = AlpacaBroker()
