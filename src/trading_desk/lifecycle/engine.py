"""One-attempt IG Demo full-position close orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal

from trading_desk.execution.errors import ExecutionBrokerError
from trading_desk.ig.models import OpenPosition
from trading_desk.lifecycle.config import LifecycleConfiguration
from trading_desk.lifecycle.evaluator import evaluate_exit
from trading_desk.lifecycle.fingerprints import fingerprint
from trading_desk.lifecycle.idempotency import LifecycleIdempotencyStore
from trading_desk.lifecycle.journal import InMemoryLifecycleJournal, LifecycleJournal
from trading_desk.lifecycle.mapping import create_close_request, map_broker_close
from trading_desk.lifecycle.models import (
    CloseBrokerConfirmation,
    CloseConfirmationStatus,
    CloseExecutionResult,
    CloseExecutionStatus,
    CloseReconciliationStatus,
    DemoPositionSnapshot,
    ExitDecisionStatus,
    ExitPreflightStatus,
    LifecycleEventType,
    LifecycleOutcome,
    LifecycleRiskState,
    StrategyExitState,
)
from trading_desk.lifecycle.preflight import run_exit_preflight
from trading_desk.lifecycle.reconciliation import (
    pending_close_reconciliation,
    reconcile_close,
)
from trading_desk.lifecycle.review import create_post_trade_review
from trading_desk.ports.position_exit import PositionExitPort


class DemoPositionLifecycleEngine:
    def __init__(
        self,
        broker: PositionExitPort,
        *,
        configuration: LifecycleConfiguration | None = None,
        idempotency: LifecycleIdempotencyStore | None = None,
        journal: LifecycleJournal | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.broker = broker
        self.configuration = configuration or LifecycleConfiguration()
        self.idempotency = idempotency or LifecycleIdempotencyStore()
        self.journal = journal or InMemoryLifecycleJournal()
        self._sleep = sleep
        self._close_requests_this_cycle = 0

    async def evaluate_and_manage(
        self,
        *,
        snapshot: DemoPositionSnapshot,
        risk: LifecycleRiskState,
        strategy_exit: StrategyExitState,
        positions: tuple[OpenPosition, ...],
        evaluation_timestamp: datetime,
        close_requests_today: int = 0,
        broker_session_valid: bool = True,
        market_closure_required: bool = False,
        unresolved_previous_close: bool = False,
        reconciliation_mismatch: bool = False,
    ) -> LifecycleOutcome:
        self._journal(
            LifecycleEventType.POSITION_MONITORED,
            evaluation_timestamp,
            snapshot,
            snapshot.position_id,
            deal_id=snapshot.deal_id,
        )
        decision = evaluate_exit(
            snapshot,
            risk,
            strategy_exit,
            evaluation_timestamp,
            self.configuration,
            market_closure_required=market_closure_required,
        )
        self._journal(
            LifecycleEventType.EXIT_DECISION_CREATED,
            evaluation_timestamp,
            decision,
            snapshot.position_id,
            decision.exit_decision_id,
            deal_id=snapshot.deal_id,
        )
        if decision.status not in {
            ExitDecisionStatus.EXIT_REQUIRED,
            ExitDecisionStatus.EMERGENCY_EXIT_REQUIRED,
        }:
            return LifecycleOutcome(decision=decision)
        request = create_close_request(decision, snapshot, self.configuration)
        self._journal(
            LifecycleEventType.CLOSE_REQUEST_CREATED,
            evaluation_timestamp,
            request,
            snapshot.position_id,
            decision.exit_decision_id,
            request.close_request_id,
            snapshot.deal_id,
        )
        preflight = run_exit_preflight(
            decision=decision,
            request=request,
            snapshot=snapshot,
            risk=risk,
            positions=positions,
            now=evaluation_timestamp,
            configuration=self.configuration,
            idempotency=self.idempotency,
            broker_session_valid=broker_session_valid,
            close_requests_this_cycle=self._close_requests_this_cycle,
            close_requests_today=close_requests_today,
            unresolved_previous_close=unresolved_previous_close,
            reconciliation_mismatch=reconciliation_mismatch,
        )
        self._journal(
            LifecycleEventType.EXIT_PREFLIGHT_UPDATED,
            evaluation_timestamp,
            preflight,
            snapshot.position_id,
            decision.exit_decision_id,
            request.close_request_id,
            snapshot.deal_id,
        )
        if preflight.status is not ExitPreflightStatus.READY:
            self._journal(
                LifecycleEventType.POSITION_CLOSE_BLOCKED,
                evaluation_timestamp,
                preflight,
                snapshot.position_id,
                decision.exit_decision_id,
                request.close_request_id,
                snapshot.deal_id,
            )
            return LifecycleOutcome(decision=decision, request=request, preflight=preflight)
        if not self.idempotency.reserve(decision, request):
            result = _result(
                request,
                evaluation_timestamp,
                CloseExecutionStatus.NOT_SUBMITTED,
                safe_error_code="DUPLICATE_CLOSE_REQUEST",
            )
            return LifecycleOutcome(
                decision=decision, request=request, preflight=preflight, result=result
            )
        self._close_requests_this_cycle += 1
        broker_request = map_broker_close(request, request.requested_quantity)
        self._journal(
            LifecycleEventType.CLOSE_SUBMITTED,
            evaluation_timestamp,
            broker_request,
            snapshot.position_id,
            decision.exit_decision_id,
            request.close_request_id,
            snapshot.deal_id,
        )
        try:
            submission = await self.broker.submit_position_close(broker_request)
        except ExecutionBrokerError as error:
            ambiguous = error.ambiguous
            status = (
                CloseExecutionStatus.RECONCILIATION_REQUIRED
                if ambiguous
                else CloseExecutionStatus.REJECTED
            )
            result = _result(
                request,
                evaluation_timestamp,
                status,
                submitted_at=evaluation_timestamp,
                safe_error_code=error.error_code,
                safe_request_id=error.request_id,
            )
            if ambiguous:
                self._journal(
                    LifecycleEventType.POSITION_LIFECYCLE_HALTED,
                    evaluation_timestamp,
                    result,
                    snapshot.position_id,
                    decision.exit_decision_id,
                    request.close_request_id,
                    snapshot.deal_id,
                )
            return LifecycleOutcome(
                decision=decision,
                request=request,
                preflight=preflight,
                result=result,
                automatic_lifecycle_halted=ambiguous,
            )
        if not self.idempotency.record_deal_reference(submission.deal_reference):
            result = _result(
                request,
                evaluation_timestamp,
                CloseExecutionStatus.RECONCILIATION_REQUIRED,
                submitted_at=evaluation_timestamp,
                deal_reference=submission.deal_reference,
                safe_request_id=submission.safe_request_id,
            )
            return LifecycleOutcome(
                decision=decision,
                request=request,
                preflight=preflight,
                result=result,
                automatic_lifecycle_halted=True,
            )
        confirmation = await self._wait_for_confirmation(submission.deal_reference)
        self._journal(
            LifecycleEventType.CLOSE_CONFIRMATION_UPDATED,
            confirmation.confirmed_at,
            confirmation,
            snapshot.position_id,
            decision.exit_decision_id,
            request.close_request_id,
            snapshot.deal_id,
        )
        result = _confirmation_result(
            request,
            confirmation,
            evaluation_timestamp,
            submission.safe_request_id,
        )
        if result.status is not CloseExecutionStatus.ACCEPTED:
            ambiguous = result.status is CloseExecutionStatus.RECONCILIATION_REQUIRED
            return LifecycleOutcome(
                decision=decision,
                request=request,
                preflight=preflight,
                result=result,
                automatic_lifecycle_halted=ambiguous,
            )
        try:
            current_positions = await self.broker.get_open_positions()
        except Exception:
            reconciliation = pending_close_reconciliation(
                request, result, confirmation.confirmed_at
            )
        else:
            reconciliation = reconcile_close(
                request, result, current_positions, confirmation.confirmed_at
            )
        self._journal(
            LifecycleEventType.CLOSE_RECONCILIATION_UPDATED,
            reconciliation.checked_at,
            reconciliation,
            snapshot.position_id,
            decision.exit_decision_id,
            request.close_request_id,
            snapshot.deal_id,
        )
        closed = reconciliation.status is CloseReconciliationStatus.POSITION_CLOSED
        mismatch = not closed
        if closed:
            self._journal(
                LifecycleEventType.POSITION_CLOSED,
                reconciliation.checked_at,
                reconciliation,
                snapshot.position_id,
                decision.exit_decision_id,
                request.close_request_id,
                snapshot.deal_id,
            )
        elif mismatch:
            self._journal(
                LifecycleEventType.POSITION_LIFECYCLE_HALTED,
                reconciliation.checked_at,
                reconciliation,
                snapshot.position_id,
                decision.exit_decision_id,
                request.close_request_id,
                snapshot.deal_id,
            )
        final_result = result.model_copy(
            update={
                "status": (
                    CloseExecutionStatus.RECONCILED
                    if closed
                    else CloseExecutionStatus.RECONCILIATION_REQUIRED
                ),
                "reconciliation_status": reconciliation.status,
            }
        )
        final_fields = final_result.model_dump(
            mode="python", exclude={"close_result_id", "result_fingerprint"}
        )
        final_identity = fingerprint(final_fields)
        final_result = CloseExecutionResult.model_validate(
            {
                **final_fields,
                "close_result_id": final_identity,
                "result_fingerprint": final_identity,
            }
        )
        if closed:
            review = create_post_trade_review(snapshot, final_result, decision.primary_reason)
            self._journal(
                LifecycleEventType.POST_TRADE_REVIEW_CREATED,
                review.created_at,
                review,
                snapshot.position_id,
                decision.exit_decision_id,
                request.close_request_id,
                snapshot.deal_id,
            )
        return LifecycleOutcome(
            decision=decision,
            request=request,
            preflight=preflight,
            result=final_result,
            reconciliation=reconciliation,
            automatic_lifecycle_halted=mismatch,
        )

    async def _wait_for_confirmation(self, reference: str) -> CloseBrokerConfirmation:
        attempts = max(
            1,
            int(
                self.configuration.maximum_confirmation_wait_seconds
                / self.configuration.confirmation_poll_interval_seconds
            ),
        )
        latest: CloseBrokerConfirmation | None = None
        for attempt in range(attempts):
            try:
                latest = await self.broker.get_close_confirmation(reference)
            except ExecutionBrokerError:
                return CloseBrokerConfirmation(
                    deal_reference=reference,
                    status=CloseConfirmationStatus.UNKNOWN,
                    confirmed_at=datetime.now(UTC),
                )
            if latest.status is not CloseConfirmationStatus.PENDING:
                return latest
            if attempt + 1 < attempts:
                await self._sleep(float(self.configuration.confirmation_poll_interval_seconds))
        assert latest is not None
        return latest.model_copy(update={"status": CloseConfirmationStatus.UNKNOWN})

    def _journal(
        self,
        event: LifecycleEventType,
        timestamp: datetime,
        payload: object,
        position_id: str,
        exit_decision_id: str | None = None,
        close_request_id: str | None = None,
        deal_id: str | None = None,
    ) -> None:
        self.journal.append(
            event,
            timestamp,
            payload,
            position_id=position_id,
            exit_decision_id=exit_decision_id,
            close_request_id=close_request_id,
            deal_id=deal_id,
        )


def _confirmation_result(
    request: object,
    confirmation: CloseBrokerConfirmation,
    submitted_at: datetime,
    safe_request_id: str | None,
) -> CloseExecutionResult:
    from trading_desk.lifecycle.models import CloseRequest

    assert isinstance(request, CloseRequest)
    accepted = (
        confirmation.status is CloseConfirmationStatus.ACCEPTED
        and confirmation.direction is not None
        and confirmation.direction.value == "SELL"
        and confirmation.executed_size == request.requested_quantity
        and confirmation.executed_level is not None
        and (confirmation.epic is None or confirmation.epic == request.epic)
    )
    if accepted:
        status = CloseExecutionStatus.ACCEPTED
    elif confirmation.status is CloseConfirmationStatus.REJECTED:
        status = CloseExecutionStatus.REJECTED
    else:
        status = CloseExecutionStatus.RECONCILIATION_REQUIRED
    return _result(
        request,
        confirmation.confirmed_at,
        status,
        submitted_at=submitted_at,
        deal_reference=confirmation.deal_reference,
        broker_status=confirmation.broker_status,
        broker_reason=confirmation.broker_reason,
        confirmed_quantity=confirmation.executed_size if accepted else None,
        confirmed_exit_level=confirmation.executed_level,
        confirmation_status=confirmation.status,
        safe_request_id=safe_request_id,
    )


def _result(
    request: object,
    completed_at: datetime,
    status: CloseExecutionStatus,
    *,
    submitted_at: datetime | None = None,
    deal_reference: str | None = None,
    broker_status: str | None = None,
    broker_reason: str | None = None,
    confirmed_quantity: Decimal | None = None,
    confirmed_exit_level: Decimal | None = None,
    confirmation_status: CloseConfirmationStatus | None = None,
    reconciliation_status: CloseReconciliationStatus | None = None,
    safe_error_code: str | None = None,
    safe_request_id: str | None = None,
) -> CloseExecutionResult:
    from trading_desk.lifecycle.models import CloseRequest

    assert isinstance(request, CloseRequest)
    fields = {
        "close_request_id": request.close_request_id,
        "exit_decision_id": request.exit_decision_id,
        "position_id": request.position_id,
        "submitted_at": submitted_at,
        "completed_at": completed_at,
        "status": status,
        "deal_reference": deal_reference,
        "broker_status": broker_status,
        "broker_reason": broker_reason,
        "requested_quantity": request.requested_quantity,
        "confirmed_quantity": confirmed_quantity,
        "confirmed_exit_level": confirmed_exit_level,
        "confirmation_status": confirmation_status,
        "reconciliation_status": reconciliation_status,
        "safe_error_code": safe_error_code,
        "safe_request_id": safe_request_id,
        "request_fingerprint": request.request_fingerprint,
    }
    identity = fingerprint(fields)
    return CloseExecutionResult.model_validate(
        {**fields, "close_result_id": identity, "result_fingerprint": identity}
    )
