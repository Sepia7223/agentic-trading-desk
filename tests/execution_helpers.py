from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from tests.risk_helpers import NOW, account, candidate, market

from trading_desk.execution.config import ExecutionConfiguration
from trading_desk.execution.confirmations import create_operator_confirmation
from trading_desk.execution.mapping import create_execution_request
from trading_desk.execution.models import (
    BrokerConfirmation,
    BrokerConfirmationStatus,
    BrokerOrderRequest,
    BrokerSubmission,
    ExecutionRequest,
    OperatorConfirmation,
)
from trading_desk.ig.models import Direction, MarketStatus, OpenPosition, PositionMarketSnapshot
from trading_desk.risk.engine import RiskEngine
from trading_desk.risk.models import RiskDecision


def enabled_configuration(**updates: object) -> ExecutionConfiguration:
    return ExecutionConfiguration.model_validate({"execution_enabled": True, **updates})


def approved_decision() -> RiskDecision:
    return RiskEngine().evaluate(candidate(), account(), market(), NOW)


def request_and_confirmation(
    *,
    configuration: ExecutionConfiguration | None = None,
    quantity: Decimal = Decimal("1"),
) -> tuple[ExecutionRequest, OperatorConfirmation, RiskDecision]:
    config = configuration or enabled_configuration()
    decision = approved_decision()
    request = create_execution_request(
        decision,
        candidate(),
        requested_quantity=quantity,
        currency="USD",
        evaluation_timestamp=NOW,
        configuration=config,
    )
    confirmation = create_operator_confirmation(
        request,
        confirmed_at=NOW,
        configuration=config,
        validity=timedelta(minutes=1),
    )
    request = request.model_copy(update={"operator_confirmation_id": confirmation.confirmation_id})
    return request, confirmation, decision


def open_position(
    *,
    deal_reference: str = "deal-ref-1",
    deal_id: str = "deal-id-1",
    size: Decimal = Decimal("1"),
) -> OpenPosition:
    return OpenPosition(
        deal_id=deal_id,
        deal_reference=deal_reference,
        direction=Direction.BUY,
        size=size,
        opening_level=Decimal("100"),
        stop_level=Decimal("95"),
        limit_level=Decimal("110"),
        controlled_risk=False,
        currency="USD",
        created_at=NOW,
        market=PositionMarketSnapshot(
            epic="CS.D.TEST.CFD.IP",
            instrument_name="Test market",
            bid=Decimal("99.9"),
            offer=Decimal("100"),
            market_status=MarketStatus("TRADEABLE"),
            update_time_utc=NOW,
        ),
    )


class FakeExecutionBroker:
    network_access = False

    def __init__(
        self,
        *,
        confirmations: tuple[BrokerConfirmation, ...] | None = None,
        positions: tuple[OpenPosition, ...] | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.submission_calls = 0
        self.confirmation_calls = 0
        self.last_order: BrokerOrderRequest | None = None
        self.failure = failure
        self.confirmations = list(
            confirmations
            or (
                BrokerConfirmation(
                    deal_reference="deal-ref-1",
                    deal_id="deal-id-1",
                    status=BrokerConfirmationStatus.ACCEPTED,
                    broker_status="OPEN",
                    broker_reason="SUCCESS",
                    epic="CS.D.TEST.CFD.IP",
                    direction="BUY",
                    executed_level=Decimal("100"),
                    executed_size=Decimal("1"),
                    stop_level=Decimal("95"),
                    limit_level=Decimal("110"),
                    confirmed_at=NOW,
                ),
            )
        )
        self.positions = (open_position(),) if positions is None else positions

    async def submit_market_position(self, request: BrokerOrderRequest) -> BrokerSubmission:
        self.submission_calls += 1
        self.last_order = request
        if self.failure is not None:
            raise self.failure
        return BrokerSubmission(deal_reference="deal-ref-1", safe_request_id="safe-1")

    async def get_deal_confirmation(self, deal_reference: str) -> BrokerConfirmation:
        self.confirmation_calls += 1
        result = self.confirmations.pop(0) if len(self.confirmations) > 1 else self.confirmations[0]
        return result.model_copy(update={"deal_reference": deal_reference})

    async def get_open_positions(self) -> tuple[OpenPosition, ...]:
        return self.positions
