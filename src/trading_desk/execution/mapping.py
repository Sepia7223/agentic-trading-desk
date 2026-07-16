"""Strict mapping from approved deterministic intent to IG order payload."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from trading_desk.execution.config import ExecutionConfiguration
from trading_desk.execution.fingerprints import fingerprint
from trading_desk.execution.models import (
    BrokerOrderRequest,
    ExecutionDirection,
    ExecutionOrderType,
    ExecutionRequest,
)
from trading_desk.risk.models import RiskDecision, TradeCandidate, TradeDirection


def create_execution_request(
    decision: RiskDecision,
    candidate: TradeCandidate,
    *,
    requested_quantity: Decimal,
    currency: str,
    evaluation_timestamp: datetime,
    configuration: ExecutionConfiguration,
    operator_confirmation_id: str | None = None,
    expiry: str = "-",
) -> ExecutionRequest:
    intent = decision.approved_intent
    if intent is None:
        raise ValueError("approved intent is required")
    direction = ExecutionDirection.BUY if intent.direction is TradeDirection.LONG else None
    if direction is None:
        raise ValueError("only long approved intents can be mapped")
    approved_spread = candidate.spread_bps
    if approved_spread is None:
        raise ValueError("approved spread is required")
    intent_id = fingerprint(intent)
    fields = {
        "approved_intent_id": intent_id,
        "risk_decision_id": decision.decision_id,
        "candidate_id": candidate.candidate_id,
        "signal_id": candidate.signal_id,
        "instrument": intent.instrument,
        "epic": intent.epic,
        "direction": direction,
        "order_type": ExecutionOrderType.MARKET,
        "approved_quantity": intent.approved_quantity,
        "requested_quantity": requested_quantity,
        "entry_reference": intent.entry_reference,
        "stop_reference": intent.stop_reference,
        "target_reference": intent.target_reference,
        "approved_spread_bps": approved_spread,
        "currency": currency,
        "expiry": expiry,
        "force_open": configuration.force_open,
        "guaranteed_stop": configuration.guaranteed_stop,
        "approval_timestamp": intent.approval_timestamp,
        "approval_expiry": intent.expiry_timestamp,
        "evaluation_timestamp": evaluation_timestamp,
        "strategy_configuration_fingerprint": intent.strategy_configuration_fingerprint,
        "risk_configuration_fingerprint": intent.risk_configuration_fingerprint,
        "execution_configuration_fingerprint": configuration.fingerprint,
        "account_snapshot_id": intent.account_snapshot_id,
        "market_snapshot_id": intent.market_snapshot_id,
        "decision_fingerprint": decision.decision_fingerprint,
    }
    request_fingerprint = fingerprint(fields)
    return ExecutionRequest.model_validate(
        {
            **fields,
            "execution_request_id": request_fingerprint,
            "request_fingerprint": request_fingerprint,
            "operator_confirmation_id": operator_confirmation_id,
        }
    )


def map_market_order(request: ExecutionRequest, validated_quantity: Decimal) -> BrokerOrderRequest:
    return BrokerOrderRequest(
        deal_reference=f"exec-{request.execution_request_id[:24]}",
        epic=request.epic,
        direction=request.direction,
        size=validated_quantity,
        order_type=request.order_type,
        currency_code=request.currency,
        expiry=request.expiry,
        force_open=request.force_open,
        guaranteed_stop=request.guaranteed_stop,
        stop_level=request.stop_reference,
        limit_level=request.target_reference,
    )
