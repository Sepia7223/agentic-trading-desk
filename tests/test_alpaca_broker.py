"""Tests for the Alpaca paper-account broker adapter (no network)."""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from trading_desk.brokers.alpaca_paper import (
    AlpacaBroker,
    credentials_present,
    parse_portfolio_state,
)

ACCOUNT = {
    "account_number": "PA3XYZ",
    "currency": "USD",
    "cash": "949.6638",
    "long_market_value": "125.50",
}
POSITIONS = [{"symbol": "AAPL"}, {"symbol": "NVDA"}, {"symbol": "COIN"}]


def test_parse_known_state() -> None:
    st = parse_portfolio_state(ACCOUNT, POSITIONS)
    assert st["is_known"] is True
    assert st["account_id"] == "PA3XYZ"
    assert st["currency"] == "USD"
    assert st["cash_available"] == Decimal("949.6638")
    assert st["market_value"] == Decimal("125.50")
    assert st["open_position_count"] == 3


def test_parse_malformed_fails_closed() -> None:
    st = parse_portfolio_state({"currency": "USD"}, [])
    assert st["is_known"] is False
    assert st["cash_available"] == Decimal("0")
    assert st["open_position_count"] == 0


def test_parse_bad_number_fails_closed() -> None:
    st = parse_portfolio_state({"cash": "not-a-number"}, [])
    assert st["is_known"] is False


def test_credentials_present_toggle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    assert credentials_present() is False
    monkeypatch.setenv("APCA_API_KEY_ID", "PKTEST")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    assert credentials_present() is True


def test_no_credentials_returns_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    st = asyncio.run(AlpacaBroker().get_portfolio_state())
    assert st["is_known"] is False
