"""Pure mappings from validated lifecycle decisions to close contracts."""

from datetime import timedelta
from decimal import Decimal

from trading_desk.lifecycle.config import LifecycleConfiguration
from trading_desk.lifecycle.fingerprints import fingerprint
from trading_desk.lifecycle.models import (
    BrokerCloseRequest,
    CloseOrderType,
    CloseRequest,
    CloseSide,
    CloseTimeInForce,
    DemoPositionSnapshot,
    ExitDecision,
)


def create_close_request(
    decision: ExitDecision,
    snapshot: DemoPositionSnapshot,
    configuration: LifecycleConfiguration,
) -> CloseRequest:
    fields = {
        "exit_decision_id": decision.exit_decision_id,
        "position_id": snapshot.position_id,
        "deal_id": snapshot.deal_id,
        "instrument": snapshot.instrument,
        "epic": snapshot.epic,
        "direction": snapshot.direction,
        "requested_quantity": decision.requested_quantity,
        "close_side": CloseSide.SELL,
        "order_type": CloseOrderType.MARKET,
        "reference_price": decision.reference_price,
        "exit_reason": decision.primary_reason,
        "created_at": decision.evaluation_timestamp,
        "expires_at": decision.evaluation_timestamp
        + min(configuration.maximum_market_data_age, timedelta(minutes=2)),
        "position_snapshot_id": snapshot.snapshot_id,
        "account_snapshot_id": snapshot.account_snapshot_id,
        "market_snapshot_id": snapshot.market_snapshot_id,
        "strategy_fingerprint": decision.strategy_fingerprint,
        "risk_fingerprint": decision.risk_fingerprint,
        "execution_fingerprint": snapshot.execution_configuration_fingerprint,
        "lifecycle_configuration_fingerprint": configuration.configuration_fingerprint,
    }
    identity = fingerprint(fields)
    return CloseRequest.model_validate(
        {**fields, "close_request_id": identity, "request_fingerprint": identity}
    )


def map_broker_close(request: CloseRequest, quantity: Decimal) -> BrokerCloseRequest:
    return BrokerCloseRequest(
        deal_id=request.deal_id,
        direction=CloseSide.SELL,
        size=quantity,
        order_type=CloseOrderType.MARKET,
        time_in_force=CloseTimeInForce.FILL_OR_KILL,
    )
