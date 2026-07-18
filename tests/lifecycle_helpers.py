from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trading_desk.ig.models import Direction, MarketStatus, OpenPosition, PositionMarketSnapshot
from trading_desk.lifecycle.config import LifecycleConfiguration
from trading_desk.lifecycle.fingerprints import fingerprint
from trading_desk.lifecycle.models import (
    BrokerCloseRequest,
    BrokerCloseSubmission,
    CloseBrokerConfirmation,
    CloseConfirmationStatus,
    CloseSide,
    DemoPositionSnapshot,
    LifecycleMarketStatus,
    LifecycleRiskState,
    PositionDirection,
    PositionStatus,
)

NOW = datetime(2026, 7, 16, 12, tzinfo=UTC)
FP = "a" * 64


def enabled_configuration(**updates: object) -> LifecycleConfiguration:
    return LifecycleConfiguration.model_validate(
        {"enabled": True, "automatic_exit_enabled": True, **updates}
    )


def snapshot(**updates: object) -> DemoPositionSnapshot:
    fields: dict[str, object] = {
        "position_id": "position-1",
        "deal_id": "deal-id-1",
        "deal_reference": "open-ref-1",
        "instrument": "EUR/USD",
        "epic": "CS.D.EURUSD.CFD.IP",
        "asset_class": "CURRENCY",
        "direction": PositionDirection.LONG,
        "quantity": Decimal("1"),
        "entry_timestamp": NOW - timedelta(hours=2),
        "entry_level": Decimal("100"),
        "current_bid": Decimal("99"),
        "current_ask": Decimal("99.1"),
        "current_mark": Decimal("99"),
        "stop_level": Decimal("95"),
        "target_level": Decimal("110"),
        "unrealized_pnl": Decimal("-1"),
        "accrued_costs": Decimal("0.1"),
        "current_exposure": Decimal("99"),
        "current_risk": Decimal("4"),
        "holding_duration": timedelta(hours=2),
        "market_status": LifecycleMarketStatus.TRADEABLE,
        "position_status": PositionStatus.OPEN,
        "account_snapshot_id": "account-1",
        "market_snapshot_id": "market-1",
        "source_execution_id": "execution-1",
        "strategy_id": "strategy-1",
        "strategy_version": "1",
        "strategy_configuration_fingerprint": FP,
        "risk_configuration_fingerprint": FP,
        "execution_configuration_fingerprint": FP,
        "snapshot_timestamp": NOW,
        "market_timestamp": NOW,
        "account_timestamp": NOW,
    }
    fields.update(updates)
    identity = fingerprint(fields)
    return DemoPositionSnapshot.model_validate(
        {**fields, "snapshot_id": identity, "snapshot_fingerprint": identity}
    )


def risk(**updates: object) -> LifecycleRiskState:
    fields: dict[str, object] = {
        "account_snapshot_id": "account-1",
        "timestamp": NOW,
        "state_complete": True,
    }
    fields.update(updates)
    return LifecycleRiskState.model_validate(fields)


def open_position(
    *,
    size: Decimal = Decimal("1"),
    direction: Direction = Direction.BUY,
    deal_id: str = "deal-id-1",
) -> OpenPosition:
    return OpenPosition(
        deal_id=deal_id,
        deal_reference="open-ref-1",
        direction=direction,
        size=size,
        opening_level=Decimal("100"),
        stop_level=Decimal("95"),
        limit_level=Decimal("110"),
        controlled_risk=False,
        currency="USD",
        created_at=NOW - timedelta(hours=2),
        market=PositionMarketSnapshot(
            epic="CS.D.EURUSD.CFD.IP",
            instrument_name="EUR/USD",
            bid=Decimal("99"),
            offer=Decimal("99.1"),
            market_status=MarketStatus.TRADEABLE,
            update_time_utc=NOW,
        ),
    )


class FakeCloseBroker:
    network_access = False

    def __init__(
        self,
        *,
        confirmations: tuple[CloseBrokerConfirmation, ...] | None = None,
        positions_after: tuple[OpenPosition, ...] = (),
        failure: Exception | None = None,
    ) -> None:
        self.submission_calls = 0
        self.confirmation_calls = 0
        self.last_request: BrokerCloseRequest | None = None
        self.failure = failure
        self.positions_after = positions_after
        self.confirmations = list(
            confirmations
            or (
                CloseBrokerConfirmation(
                    deal_reference="close-ref-1",
                    deal_id="close-deal-1",
                    status=CloseConfirmationStatus.ACCEPTED,
                    broker_status="CLOSED",
                    broker_reason="SUCCESS",
                    epic="CS.D.EURUSD.CFD.IP",
                    direction=CloseSide.SELL,
                    executed_level=Decimal("95"),
                    executed_size=Decimal("1"),
                    confirmed_at=NOW,
                ),
            )
        )

    async def submit_position_close(self, request: BrokerCloseRequest) -> BrokerCloseSubmission:
        self.submission_calls += 1
        self.last_request = request
        if self.failure:
            raise self.failure
        return BrokerCloseSubmission(deal_reference="close-ref-1", safe_request_id="safe-1")

    async def get_close_confirmation(self, deal_reference: str) -> CloseBrokerConfirmation:
        self.confirmation_calls += 1
        result = self.confirmations.pop(0) if len(self.confirmations) > 1 else self.confirmations[0]
        return result.model_copy(update={"deal_reference": deal_reference})

    async def get_open_positions(self) -> tuple[OpenPosition, ...]:
        return self.positions_after
