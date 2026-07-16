"""Deterministic fail-closed execution preflight and risk revalidation."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from trading_desk.execution.config import ExecutionConfiguration
from trading_desk.execution.confirmations import confirmation_matches
from trading_desk.execution.fingerprints import fingerprint
from trading_desk.execution.idempotency import ExecutionIdempotencyStore
from trading_desk.execution.models import (
    ExecutionDirection,
    ExecutionOrderType,
    ExecutionPreflightResult,
    ExecutionReasonCode,
    ExecutionRequest,
    OperatorConfirmation,
    PreflightStatus,
)
from trading_desk.ig.models import OpenPosition
from trading_desk.risk.engine import RiskEngine
from trading_desk.risk.models import (
    AccountRiskState,
    MarketRiskState,
    RiskDecision,
    RiskDecisionStatus,
    RiskMarketStatus,
    TradeCandidate,
)
from trading_desk.risk.sizing import round_quantity_down

TEN_THOUSAND = Decimal("10000")


def run_preflight(
    *,
    request: ExecutionRequest,
    decision: RiskDecision,
    candidate: TradeCandidate,
    account: AccountRiskState,
    market: MarketRiskState,
    positions: tuple[OpenPosition, ...],
    confirmation: OperatorConfirmation | None,
    evaluation_timestamp: datetime,
    configuration: ExecutionConfiguration,
    risk_engine: RiskEngine,
    idempotency: ExecutionIdempotencyStore,
    orders_this_run: int = 0,
    orders_today: int = 0,
    automatic: bool = False,
) -> ExecutionPreflightResult:
    passed: list[str] = []
    failed: list[str] = []
    reasons: list[ExecutionReasonCode] = []

    def gate(name: str, *gate_reasons: ExecutionReasonCode) -> None:
        if gate_reasons:
            failed.append(name)
            reasons.extend(gate_reasons)
        else:
            passed.append(name)

    gate(
        "EXECUTION_ENABLED",
        *(() if configuration.execution_enabled else (ExecutionReasonCode.EXECUTION_DISABLED,)),
    )
    gate(
        "AUTOMATIC_EXECUTION",
        *(
            (ExecutionReasonCode.AUTOMATIC_EXECUTION_DISABLED,)
            if automatic and not configuration.automatic_execution_enabled
            else ()
        ),
    )
    integrity = _integrity_reasons(request, decision, candidate, configuration)
    gate("APPROVAL_INTEGRITY", *integrity)

    expiry_reasons: list[ExecutionReasonCode] = []
    if (
        not decision.approved_intent
        or not decision.approved_intent.is_valid_at(evaluation_timestamp)
        or evaluation_timestamp - request.approval_timestamp > configuration.maximum_intent_age
    ):
        expiry_reasons.append(ExecutionReasonCode.APPROVAL_EXPIRED)
    gate("APPROVAL_FRESHNESS", *expiry_reasons)

    confirmation_reasons = (
        ()
        if confirmation_matches(request, confirmation, evaluation_timestamp, configuration)
        else (ExecutionReasonCode.OPERATOR_CONFIRMATION_REQUIRED,)
    )
    gate("OPERATOR_CONFIRMATION", *confirmation_reasons)

    duplicate_reasons: list[ExecutionReasonCode] = []
    if idempotency.is_duplicate(request):
        duplicate_reasons.append(ExecutionReasonCode.DUPLICATE_EXECUTION_REQUEST)
    if idempotency.intent_consumed(request.approved_intent_id):
        duplicate_reasons.append(ExecutionReasonCode.INTENT_ALREADY_CONSUMED)
    gate("IDEMPOTENCY", *duplicate_reasons)

    count_reasons: list[ExecutionReasonCode] = []
    if orders_this_run >= configuration.maximum_orders_per_run:
        count_reasons.append(ExecutionReasonCode.MAX_ORDERS_PER_RUN_REACHED)
    if orders_today >= configuration.maximum_orders_per_day:
        count_reasons.append(ExecutionReasonCode.MAX_ORDERS_PER_DAY_REACHED)
    gate("ORDER_COUNTS", *count_reasons)

    account_reasons: list[ExecutionReasonCode] = []
    if evaluation_timestamp - account.timestamp > configuration.maximum_account_snapshot_age:
        account_reasons.append(ExecutionReasonCode.ACCOUNT_DATA_STALE)
    if not account.state_complete:
        account_reasons.append(ExecutionReasonCode.ACCOUNT_STATE_CHANGED)
    if account.kill_switch_active:
        account_reasons.append(ExecutionReasonCode.KILL_SWITCH_ACTIVE)
    gate("ACCOUNT_STATE", *account_reasons)

    market_reasons: list[ExecutionReasonCode] = []
    if evaluation_timestamp - market.timestamp > configuration.maximum_market_snapshot_age:
        market_reasons.append(ExecutionReasonCode.MARKET_DATA_STALE)
    if not market.state_complete or market.epic != request.epic:
        market_reasons.append(ExecutionReasonCode.MARKET_STATE_CHANGED)
    if market.market_status is not RiskMarketStatus.TRADEABLE:
        market_reasons.append(ExecutionReasonCode.MARKET_CLOSED)
    if market.bid is None or market.ask is None or market.bid <= 0 or market.ask <= market.bid:
        market_reasons.append(ExecutionReasonCode.INVALID_BID_ASK)
    gate("MARKET_STATE", *market_reasons)

    if any(position.market.epic == request.epic for position in positions):
        gate("POSITION_STATE", ExecutionReasonCode.POSITION_ALREADY_EXISTS)
    else:
        gate("POSITION_STATE")

    drift_reasons: list[ExecutionReasonCode] = []
    if market.ask is not None and request.entry_reference > 0:
        price_drift = (
            TEN_THOUSAND * (market.ask - request.entry_reference) / request.entry_reference
        )
        if price_drift > configuration.reject_on_price_drift_bps:
            drift_reasons.append(ExecutionReasonCode.PRICE_DRIFT_EXCEEDED)
    if market.spread_bps is None:
        drift_reasons.append(ExecutionReasonCode.INVALID_BID_ASK)
    elif market.spread_bps - request.approved_spread_bps > (
        configuration.reject_on_spread_change_bps
    ):
        drift_reasons.append(ExecutionReasonCode.SPREAD_CHANGED)
    gate("PRICE_AND_SPREAD_DRIFT", *drift_reasons)

    validated_quantity: Decimal | None = None
    revalidation_reasons: list[ExecutionReasonCode] = []
    if not market_reasons and not account_reasons:
        current_candidate = candidate.model_copy(
            update={
                "entry_reference": market.ask,
                "bid": market.bid,
                "ask": market.ask,
                "spread_bps": market.spread_bps,
                "market_status": market.market_status,
                "holding_state": False,
            }
        )
        current_decision = risk_engine.evaluate(
            current_candidate, account, market, evaluation_timestamp
        )
        if current_decision.status is not RiskDecisionStatus.APPROVED:
            revalidation_reasons.append(ExecutionReasonCode.APPROVAL_NOT_APPROVED)
        else:
            assert current_decision.approved_quantity is not None
            assert market.quantity_increment is not None
            validated_quantity = round_quantity_down(
                min(
                    request.requested_quantity,
                    request.approved_quantity,
                    current_decision.approved_quantity,
                    configuration.maximum_order_quantity,
                ),
                market.quantity_increment,
            )
            minimum = market.minimum_deal_size
            if minimum is None or validated_quantity < minimum:
                revalidation_reasons.append(ExecutionReasonCode.QUANTITY_BELOW_MINIMUM)
            if market.ask is None or market.value_per_price_unit is None:
                revalidation_reasons.append(ExecutionReasonCode.INVALID_INPUT)
            elif (
                validated_quantity * market.ask * market.value_per_price_unit
                > configuration.maximum_order_notional
            ):
                revalidation_reasons.append(ExecutionReasonCode.NOTIONAL_EXCEEDS_EXECUTION_LIMIT)
    else:
        revalidation_reasons.append(ExecutionReasonCode.APPROVAL_NOT_APPROVED)
    gate("RISK_REVALIDATION", *revalidation_reasons)

    unique_reasons = tuple(dict.fromkeys(reasons))
    status = _status(unique_reasons)
    fields = {
        "execution_request_id": request.execution_request_id,
        "status": status,
        "passed_gates": tuple(passed),
        "failed_gates": tuple(failed),
        "reason_codes": unique_reasons,
        "validated_quantity": validated_quantity if not unique_reasons else None,
        "validated_entry_reference": market.ask if not unique_reasons else None,
        "validated_stop_reference": request.stop_reference if not unique_reasons else None,
        "validated_target_reference": request.target_reference if not unique_reasons else None,
        "account_snapshot_id": account.snapshot_id,
        "market_snapshot_id": market.snapshot_id,
        "execution_configuration_fingerprint": configuration.fingerprint,
    }
    preflight_fingerprint = fingerprint(fields)
    return ExecutionPreflightResult.model_validate(
        {
            **fields,
            "preflight_id": preflight_fingerprint,
            "preflight_fingerprint": preflight_fingerprint,
        }
    )


def _integrity_reasons(
    request: ExecutionRequest,
    decision: RiskDecision,
    candidate: TradeCandidate,
    configuration: ExecutionConfiguration,
) -> tuple[ExecutionReasonCode, ...]:
    reasons: list[ExecutionReasonCode] = []
    intent = decision.approved_intent
    request_fields = request.model_dump(
        mode="python",
        exclude={"execution_request_id", "request_fingerprint", "operator_confirmation_id"},
    )
    expected_request_fingerprint = fingerprint(request_fields)
    if (
        request.execution_request_id != expected_request_fingerprint
        or request.request_fingerprint != expected_request_fingerprint
    ):
        reasons.append(ExecutionReasonCode.EXECUTION_FINGERPRINT_MISMATCH)
    decision_fields = decision.model_dump(mode="python", exclude={"decision_fingerprint"})
    if decision.status is not RiskDecisionStatus.APPROVED or intent is None:
        reasons.append(ExecutionReasonCode.APPROVAL_NOT_APPROVED)
        return tuple(reasons)
    if fingerprint(decision_fields) != decision.decision_fingerprint:
        reasons.append(ExecutionReasonCode.APPROVAL_FINGERPRINT_MISMATCH)
    if request.decision_fingerprint != decision.decision_fingerprint:
        reasons.append(ExecutionReasonCode.APPROVAL_FINGERPRINT_MISMATCH)
    if request.approved_intent_id != fingerprint(intent):
        reasons.append(ExecutionReasonCode.APPROVAL_FINGERPRINT_MISMATCH)
    if request.strategy_configuration_fingerprint != candidate.strategy_configuration_fingerprint:
        reasons.append(ExecutionReasonCode.STRATEGY_FINGERPRINT_MISMATCH)
    if request.risk_configuration_fingerprint != decision.risk_configuration_fingerprint:
        reasons.append(ExecutionReasonCode.RISK_FINGERPRINT_MISMATCH)
    if request.execution_configuration_fingerprint != configuration.fingerprint:
        reasons.append(ExecutionReasonCode.EXECUTION_FINGERPRINT_MISMATCH)
    if request.account_snapshot_id != decision.account_snapshot_id:
        reasons.append(ExecutionReasonCode.ACCOUNT_STATE_CHANGED)
    if request.market_snapshot_id != decision.market_snapshot_id:
        reasons.append(ExecutionReasonCode.MARKET_STATE_CHANGED)
    if request.direction is not ExecutionDirection.BUY:
        reasons.append(ExecutionReasonCode.UNSUPPORTED_DIRECTION)
    if request.order_type is not ExecutionOrderType.MARKET:
        reasons.append(ExecutionReasonCode.UNSUPPORTED_ORDER_TYPE)
    if request.requested_quantity > request.approved_quantity:
        reasons.append(ExecutionReasonCode.QUANTITY_EXCEEDS_APPROVAL)
    if request.requested_quantity > configuration.maximum_order_quantity:
        reasons.append(ExecutionReasonCode.QUANTITY_EXCEEDS_EXECUTION_LIMIT)
    if request.stop_reference >= request.entry_reference:
        reasons.append(ExecutionReasonCode.INVALID_INPUT)
    if request.target_reference is not None and request.target_reference <= request.entry_reference:
        reasons.append(ExecutionReasonCode.INVALID_INPUT)
    intent_matches = (
        request.risk_decision_id == intent.risk_decision_id
        and request.candidate_id == intent.candidate_id == candidate.candidate_id
        and request.instrument == intent.instrument
        and request.epic == intent.epic == candidate.epic
        and request.approved_quantity == intent.approved_quantity
        and request.entry_reference == intent.entry_reference
        and request.stop_reference == intent.stop_reference
        and request.target_reference == intent.target_reference
        and request.approval_timestamp == intent.approval_timestamp
        and request.approval_expiry == intent.expiry_timestamp
    )
    if not intent_matches:
        reasons.append(ExecutionReasonCode.APPROVAL_FINGERPRINT_MISMATCH)
    return tuple(dict.fromkeys(reasons))


def _status(reasons: tuple[ExecutionReasonCode, ...]) -> PreflightStatus:
    if not reasons:
        return PreflightStatus.READY
    if ExecutionReasonCode.EXECUTION_DISABLED in reasons:
        return PreflightStatus.DISABLED
    if ExecutionReasonCode.APPROVAL_EXPIRED in reasons:
        return PreflightStatus.EXPIRED
    if ExecutionReasonCode.KILL_SWITCH_ACTIVE in reasons:
        return PreflightStatus.KILL_SWITCHED
    if ExecutionReasonCode.OPERATOR_CONFIRMATION_REQUIRED in reasons:
        return PreflightStatus.CONFIRMATION_REQUIRED
    if ExecutionReasonCode.INVALID_INPUT in reasons:
        return PreflightStatus.INVALID_INPUT
    return PreflightStatus.REJECTED
