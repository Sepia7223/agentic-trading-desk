from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading_desk.portfolio.config import PaperPortfolioConfiguration
from trading_desk.portfolio.models import MarketQuote


def test_safe_configuration_defaults_and_stable_fingerprint() -> None:
    first = PaperPortfolioConfiguration()
    second = PaperPortfolioConfiguration()
    assert first.allow_partial_fills is False
    assert first.allow_pyramiding is False
    assert first.allow_multiple_positions_per_instrument is False
    assert first.approval_expiry_enforced is True
    assert first.fingerprint == second.fingerprint
    assert len(first.fingerprint) == 64


@pytest.mark.parametrize(
    "updates",
    [
        {"initial_cash": Decimal("0")},
        {"initial_cash": Decimal("NaN")},
        {"price_precision": -1},
        {"maximum_open_positions": 0},
        {"maximum_open_positions": 1, "maximum_positions_per_instrument": 2},
        {"slippage_bps": -Decimal("1")},
        {"initial_cash": 100.0},
        {"state_persistence_enabled": True},
    ],
)
def test_invalid_configuration_fails_closed(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PaperPortfolioConfiguration.model_validate(updates)


def test_models_are_immutable_and_require_utc() -> None:
    with pytest.raises(ValidationError):
        MarketQuote(
            snapshot_id="m",
            timestamp=datetime(2026, 1, 1),
            epic="EPIC",
            bid=Decimal("1"),
            ask=Decimal("2"),
            market_status="TRADEABLE",
        )
    quote = MarketQuote(
        snapshot_id="m",
        timestamp=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
        epic="EPIC",
        bid=Decimal("1"),
        ask=Decimal("2"),
        market_status="TRADEABLE",
    )
    with pytest.raises(ValidationError):
        quote.bid = Decimal("2")  # type: ignore[misc]
