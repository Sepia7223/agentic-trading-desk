"""One-attempt controlled execution orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal

from trading_desk.execution.config import ExecutionConfiguration
from trading_desk.execution.errors import ExecutionBrokerError
from trading_desk.execution.fingerprints import fingerprint
from trading_desk.execution.idempotency import ExecutionIdempotencyStore
from trading_desk.execution.journal import ExecutionJournal, InMemoryExecutionJournal
from trading_desk.execution.mapping import map_market_order
from trading_desk.execution.models import (
    BrokerConfirmation,
    BrokerConfirmationStatus,
    ExecutionEventType,
    ExecutionOutcome,
    ExecutionPreflightResult,
    ExecutionReasonCode,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    OperatorConfirmation,
    PreflightStatus,
)
from trading_desk.execution.preflight import run_preflight
from trading_desk.execution.reconciliation import pending_reconciliation, reconcile_position
from trading_desk.ig.models import OpenPosition
from trading_desk.ports.execution import BrokerExecutionPort
from trading_desk.risk.engine import RiskEngine
from trading_desk.risk.models import AccountRiskState, MarketRiskState, RiskDecision, TradeCandidate


class ExecutionEngine:
    def __init__(
        self,
        broker: BrokerExecutionPort,
        *,
        configuration: ExecutionConfiguration | None = None,
        risk_engine: RiskEngine | None = None,
        idempotency: ExecutionIdempotencyStore | None = None,
        journal: ExecutionJournal | None = None,
        before_submission: Callable[[], None] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.broker = broker
        self.configuration = configuration or ExecutionConfiguration()
        self.risk_engine = risk_engine or RiskEngine()
        self.idempotency = idempotency or ExecutionIdempotencyStore()
        self.journal = journal or InMemoryExecutionJournal()
        self.before_submission = before_submission
        self._sleep = sleep
        self._orders_this_run = 0

    async def execute(
        self,
        *,
        request: ExecutionRequest,
        decision: RiskDecision,
        candidate: TradeCandidate,
        account: AccountRiskState,
        market: MarketRiskState,
        positions: tuple[OpenPosition, ...],
        confirmation: OperatorConfirmation | None,
        evaluation_timestamp: datetime,
        orders_today: int = 0,
        automatic: bool = False,
    ) -> ExecutionOutcome:
        self._journal(ExecutionEventType.REQUEST_CREATED, evaluation_timestamp, request, request)
        preflight = run_preflight(
            request=request,
            decision=decision,
            candidate=candidate,
            account=account,
            market=market,
            positions=positions,
            confirmation=confirmation,
            evaluation_timestamp=evaluation_timestamp,
            configuration=self.configuration,
            risk_engine=self.risk_engine,
            idempotency=self.idempotency,
            orders_this_run=self._orders_this_run,
            orders_today=orders_today,
            automatic=automatic,
        )
        self._journal(
            ExecutionEventType.PREFLIGHT_COMPLETED,
            evaluation_timestamp,
            preflight,
            request,
        )
        if preflight.status is not PreflightStatus.READY:
            outcome = ExecutionOutcome(
                preflight=preflight,
                result=_result(
                    request,
                    preflight,
                    evaluation_timestamp,
                    ExecutionStatus.NOT_SUBMITTED,
                    preflight.reason_codes or (ExecutionReasonCode.INVALID_INPUT,),
                ),
            )
            self._journal(
                ExecutionEventType.EXECUTION_FAILED,
                evaluation_timestamp,
                outcome.result,
                request,
            )
            return outcome
        assert preflight.validated_quantity is not None
        if confirmation is not None:
            self._journal(
                ExecutionEventType.OPERATOR_CONFIRMED,
                evaluation_timestamp,
                confirmation,
                request,
            )
        if not self.idempotency.reserve_submission(request):
            result = _result(
                request,
                preflight,
                evaluation_timestamp,
                ExecutionStatus.NOT_SUBMITTED,
                (ExecutionReasonCode.DUPLICATE_EXECUTION_REQUEST,),
            )
            return ExecutionOutcome(preflight=preflight, result=result)
        self._orders_this_run += 1
        order = map_market_order(request, preflight.validated_quantity)
        self._journal(
            ExecutionEventType.SUBMISSION_ATTEMPTED,
            evaluation_timestamp,
            order,
            request,
        )
        if self.before_submission is not None:
            self.before_submission()
        try:
            submission = await self.broker.submit_market_position(order)
        except ExecutionBrokerError as error:
            status = (
                ExecutionStatus.RECONCILIATION_REQUIRED
                if error.ambiguous
                else ExecutionStatus.REJECTED
            )
            reason = (
                ExecutionReasonCode.RECONCILIATION_REQUIRED
                if error.ambiguous
                else ExecutionReasonCode.BROKER_REJECTED
            )
            result = _result(
                request,
                preflight,
                evaluation_timestamp,
                status,
                (reason,),
                submitted_at=evaluation_timestamp,
                safe_error_code=error.error_code,
                safe_request_id=error.request_id,
            )
            self._journal(
                ExecutionEventType.EXECUTION_FAILED,
                evaluation_timestamp,
                result,
                request,
            )
            return ExecutionOutcome(preflight=preflight, result=result)
        self._journal(
            ExecutionEventType.BROKER_RESPONDED,
            evaluation_timestamp,
            submission,
            request,
            deal_reference=submission.deal_reference,
        )
        if not self.idempotency.record_deal_reference(submission.deal_reference):
            result = _result(
                request,
                preflight,
                evaluation_timestamp,
                ExecutionStatus.RECONCILIATION_REQUIRED,
                (ExecutionReasonCode.RECONCILIATION_REQUIRED,),
                submitted_at=evaluation_timestamp,
                deal_reference=submission.deal_reference,
                safe_request_id=submission.safe_request_id,
            )
            return ExecutionOutcome(preflight=preflight, result=result)

        confirmed = await self._wait_for_confirmation(submission.deal_reference)
        self._journal(
            ExecutionEventType.CONFIRMATION_COMPLETED,
            confirmed.confirmed_at,
            confirmed,
            request,
            deal_reference=confirmed.deal_reference,
            deal_id=confirmed.deal_id,
        )
        result = _confirmation_result(
            request,
            preflight,
            submission.safe_request_id,
            confirmed,
            evaluation_timestamp,
        )
        if result.status is not ExecutionStatus.ACCEPTED:
            return ExecutionOutcome(preflight=preflight, result=result)
        try:
            current_positions = await self.broker.get_open_positions()
        except Exception:
            reconciliation = pending_reconciliation(result, confirmed.confirmed_at)
            self._journal(
                ExecutionEventType.RECONCILIATION_COMPLETED,
                confirmed.confirmed_at,
                reconciliation,
                request,
                deal_reference=result.deal_reference,
                deal_id=result.deal_id,
            )
            return ExecutionOutcome(
                preflight=preflight,
                result=result,
                reconciliation=reconciliation,
            )
        reconciliation, demo_position = reconcile_position(
            request, result, current_positions, confirmed.confirmed_at
        )
        self._journal(
            ExecutionEventType.RECONCILIATION_COMPLETED,
            confirmed.confirmed_at,
            reconciliation,
            request,
            deal_reference=result.deal_reference,
            deal_id=result.deal_id,
        )
        return ExecutionOutcome(
            preflight=preflight,
            result=result,
            reconciliation=reconciliation,
            demo_position=demo_position,
        )

    async def _wait_for_confirmation(self, deal_reference: str) -> BrokerConfirmation:
        interval = float(self.configuration.confirmation_poll_interval_seconds)
        attempts = max(
            1,
            int(
                self.configuration.maximum_confirmation_wait_seconds
                / self.configuration.confirmation_poll_interval_seconds
            ),
        )
        latest: BrokerConfirmation | None = None
        for attempt in range(attempts):
            try:
                latest = await self.broker.get_deal_confirmation(deal_reference)
            except ExecutionBrokerError:
                return BrokerConfirmation(
                    deal_reference=deal_reference,
                    status=BrokerConfirmationStatus.UNKNOWN,
                    confirmed_at=datetime.now(UTC),
                )
            if latest.status is not BrokerConfirmationStatus.PENDING:
                return latest
            if attempt + 1 < attempts:
                await self._sleep(interval)
        assert latest is not None
        return latest.model_copy(update={"status": BrokerConfirmationStatus.UNKNOWN})

    def _journal(
        self,
        event_type: ExecutionEventType,
        timestamp: datetime,
        payload: object,
        request: ExecutionRequest,
        *,
        deal_reference: str | None = None,
        deal_id: str | None = None,
    ) -> None:
        self.journal.append(
            event_type,
            timestamp,
            payload,
            signal_id=request.signal_id,
            candidate_id=request.candidate_id,
            risk_decision_id=request.risk_decision_id,
            approved_intent_id=request.approved_intent_id,
            execution_request_id=request.execution_request_id,
            deal_reference=deal_reference,
            deal_id=deal_id,
        )


def _confirmation_result(
    request: ExecutionRequest,
    preflight: ExecutionPreflightResult,
    safe_request_id: str | None,
    confirmation: BrokerConfirmation,
    submitted_at: datetime,
) -> ExecutionResult:
    mismatch = (
        confirmation.deal_reference == ""
        or confirmation.deal_id is None
        or confirmation.epic is None
        or confirmation.direction is None
        or confirmation.executed_level is None
        or confirmation.executed_size is None
        or confirmation.stop_level is None
        or (confirmation.epic is not None and confirmation.epic != request.epic)
        or (confirmation.direction is not None and confirmation.direction is not request.direction)
        or (
            confirmation.executed_size is not None
            and confirmation.executed_size != preflight.validated_quantity
        )
        or confirmation.stop_level != request.stop_reference
        or confirmation.limit_level != request.target_reference
    )
    if confirmation.status is BrokerConfirmationStatus.ACCEPTED and not mismatch:
        status = ExecutionStatus.ACCEPTED
        reasons: tuple[ExecutionReasonCode, ...] = ()
    elif confirmation.status is BrokerConfirmationStatus.REJECTED:
        status = ExecutionStatus.REJECTED
        reasons = (ExecutionReasonCode.BROKER_REJECTED,)
    else:
        status = ExecutionStatus.RECONCILIATION_REQUIRED
        reasons = (
            ExecutionReasonCode.BROKER_CONFIRMATION_UNKNOWN,
            ExecutionReasonCode.RECONCILIATION_REQUIRED,
        )
    return _result(
        request,
        preflight,
        confirmation.confirmed_at,
        status,
        reasons,
        submitted_at=submitted_at,
        deal_reference=confirmation.deal_reference,
        deal_id=confirmation.deal_id,
        broker_status=confirmation.broker_status,
        broker_reason=confirmation.broker_reason,
        accepted_quantity=(
            confirmation.executed_size if status is ExecutionStatus.ACCEPTED else None
        ),
        entry_level=confirmation.executed_level,
        stop_level=confirmation.stop_level,
        target_level=confirmation.limit_level,
        confirmation_status=confirmation.status,
        safe_request_id=safe_request_id,
    )


def _result(
    request: ExecutionRequest,
    preflight: ExecutionPreflightResult,
    completed_at: datetime,
    status: ExecutionStatus,
    reason_codes: tuple[ExecutionReasonCode, ...],
    *,
    submitted_at: datetime | None = None,
    deal_reference: str | None = None,
    deal_id: str | None = None,
    broker_status: str | None = None,
    broker_reason: str | None = None,
    accepted_quantity: Decimal | None = None,
    entry_level: Decimal | None = None,
    stop_level: Decimal | None = None,
    target_level: Decimal | None = None,
    confirmation_status: BrokerConfirmationStatus | None = None,
    safe_error_code: str | None = None,
    safe_request_id: str | None = None,
) -> ExecutionResult:
    fields = {
        "execution_request_id": request.execution_request_id,
        "preflight_id": preflight.preflight_id,
        "submitted_at": submitted_at,
        "completed_at": completed_at,
        "status": status,
        "reason_codes": reason_codes,
        "deal_reference": deal_reference,
        "deal_id": deal_id,
        "broker_status": broker_status,
        "broker_reason": broker_reason,
        "requested_quantity": request.requested_quantity,
        "accepted_quantity": accepted_quantity,
        "entry_level": entry_level,
        "stop_level": stop_level,
        "target_level": target_level,
        "confirmation_status": confirmation_status,
        "safe_error_code": safe_error_code,
        "safe_request_id": safe_request_id,
        "account_snapshot_id": preflight.account_snapshot_id,
        "market_snapshot_id": preflight.market_snapshot_id,
        "request_fingerprint": request.request_fingerprint,
    }
    result_fingerprint = fingerprint(fields)
    return ExecutionResult.model_validate(
        {
            **fields,
            "execution_result_id": result_fingerprint,
            "result_fingerprint": result_fingerprint,
        }
    )
