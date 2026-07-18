from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from tests.execution_helpers import NOW, open_position

from trading_desk.ig.models import (
    Account,
    AccountBalance,
    AccountType,
    InstrumentType,
    MarketDetails,
    MarketStatus,
)
from trading_desk.opportunity.ledger import DemoTradeLedger, DemoTradeStatus
from trading_desk.opportunity.lifecycle import OperationalLifecycleContextProvider


class LifecycleBroker:
    def __init__(self, positions):  # type: ignore[no-untyped-def]
        self.positions = positions

    async def get_accounts(self) -> tuple[Account, ...]:
        return (
            Account(
                account_id="demo-account",
                account_name="Demo",
                account_type=AccountType.CFD,
                preferred=True,
                currency="USD",
                balance=AccountBalance(
                    balance=Decimal("20000"),
                    deposit=Decimal("0"),
                    profit_loss=Decimal("0"),
                    available_funds=Decimal("20000"),
                ),
            ),
        )

    async def get_open_positions(self):  # type: ignore[no-untyped-def]
        return self.positions

    async def get_market_details(self, epic: str) -> MarketDetails:
        return MarketDetails(
            epic=epic,
            instrument_name="Test market",
            instrument_type=InstrumentType.CURRENCIES,
            market_status=MarketStatus.TRADEABLE,
            bid=Decimal("101"),
            offer=Decimal("101.1"),
            currency_code="USD",
        )


def _confirmed_ledger(path: Path) -> DemoTradeLedger:
    ledger = DemoTradeLedger(path)
    ledger.append(
        ledger.create_record(
            occurred_at=NOW,
            status=DemoTradeStatus.CONFIRMED,
            strategy="trend-regime-v1",
            instrument="Test market",
            timeframe="MINUTE_5",
            regime="BULL_LOW_VOL",
            session="DEMO",
            candidate_id="candidate-1",
            execution_id="execution-1",
        )
    )
    return ledger


def test_restart_rediscovers_only_ledger_backed_reconciled_position(tmp_path: Path) -> None:
    position = open_position()
    ledger = _confirmed_ledger(tmp_path / "ledger.json")
    observed_at = NOW + timedelta(minutes=1)

    first = asyncio.run(
        OperationalLifecycleContextProvider(LifecycleBroker((position,)), ledger=ledger).snapshots(
            observed_at
        )
    )
    restarted = asyncio.run(
        OperationalLifecycleContextProvider(
            LifecycleBroker((position,)), ledger=DemoTradeLedger(ledger.path)
        ).snapshots(observed_at)
    )

    assert len(first) == 1
    assert first == restarted
    assert first[0].source_execution_id == "execution-1"


def test_untracked_or_ambiguous_positions_are_not_automatically_managed(tmp_path: Path) -> None:
    position = open_position()
    empty = DemoTradeLedger(tmp_path / "empty.json")
    assert (
        asyncio.run(
            OperationalLifecycleContextProvider(
                LifecycleBroker((position,)), ledger=empty
            ).snapshots(NOW + timedelta(minutes=1))
        )
        == ()
    )

    ledger = _confirmed_ledger(tmp_path / "confirmed.json")
    duplicate = position.model_copy(update={"deal_id": "deal-id-2"})
    assert (
        asyncio.run(
            OperationalLifecycleContextProvider(
                LifecycleBroker((position, duplicate)), ledger=ledger
            ).snapshots(NOW + timedelta(minutes=1))
        )
        == ()
    )
