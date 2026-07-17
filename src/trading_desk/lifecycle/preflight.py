"""Exact current-state validation immediately before one close submission."""

from datetime import datetime

from trading_desk.ig.models import Direction, OpenPosition
from trading_desk.lifecycle.config import LifecycleConfiguration
from trading_desk.lifecycle.fingerprints import fingerprint
from trading_desk.lifecycle.idempotency import LifecycleIdempotencyStore
from trading_desk.lifecycle.models import (
    CloseRequest,
    DemoPositionSnapshot,
    ExitDecision,
    ExitDecisionStatus,
    ExitPreflightResult,
    ExitPreflightStatus,
    LifecycleMarketStatus,
    LifecycleRiskState,
)


def run_exit_preflight(
    *,
    decision: ExitDecision,
    request: CloseRequest,
    snapshot: DemoPositionSnapshot,
    risk: LifecycleRiskState,
    positions: tuple[OpenPosition, ...],
    now: datetime,
    configuration: LifecycleConfiguration,
    idempotency: LifecycleIdempotencyStore,
    broker_session_valid: bool,
    close_requests_this_cycle: int,
    close_requests_today: int,
    unresolved_previous_close: bool = False,
    reconciliation_mismatch: bool = False,
) -> ExitPreflightResult:
    checks: list[tuple[str, bool]] = [
        ("LIFECYCLE_ENABLED", configuration.enabled),
        ("AUTOMATIC_EXIT_ENABLED", configuration.automatic_exit_enabled),
        ("DEMO_ENVIRONMENT", configuration.broker_environment.value == "DEMO"),
        (
            "EXIT_REQUIRED",
            decision.status
            in {ExitDecisionStatus.EXIT_REQUIRED, ExitDecisionStatus.EMERGENCY_EXIT_REQUIRED},
        ),
        ("REQUEST_NOT_EXPIRED", now <= request.expires_at),
        ("POSITION_SNAPSHOT_MATCH", request.position_snapshot_id == snapshot.snapshot_id),
        ("ACCOUNT_SNAPSHOT_MATCH", request.account_snapshot_id == risk.account_snapshot_id),
        (
            "MARKET_DATA_FRESH",
            now - snapshot.market_timestamp <= configuration.maximum_market_data_age,
        ),
        (
            "ACCOUNT_DATA_FRESH",
            now - risk.timestamp <= configuration.maximum_account_state_age and risk.state_complete,
        ),
        (
            "MARKET_CLOSE_AVAILABLE",
            snapshot.market_status
            in {LifecycleMarketStatus.TRADEABLE, LifecycleMarketStatus.CLOSINGS_ONLY},
        ),
        ("BROKER_SESSION_VALID", broker_session_valid),
        (
            "FULL_CLOSE_ONLY",
            configuration.allow_full_close
            and not configuration.allow_partial_close
            and request.requested_quantity == snapshot.quantity,
        ),
        (
            "CYCLE_LIMIT_AVAILABLE",
            close_requests_this_cycle < configuration.maximum_close_requests_per_cycle,
        ),
        (
            "DAILY_LIMIT_AVAILABLE",
            close_requests_today < configuration.maximum_close_requests_per_day,
        ),
        ("NO_UNRESOLVED_CLOSE", not unresolved_previous_close),
        ("NO_RECONCILIATION_MISMATCH", not reconciliation_mismatch),
        ("LIFECYCLE_HALT_CLEAR", not risk.lifecycle_halted),
        ("REQUEST_UNCONSUMED", not idempotency.duplicate(decision, request)),
    ]
    broker_position = next((item for item in positions if item.deal_id == request.deal_id), None)
    exact = (
        broker_position is not None
        and broker_position.direction is Direction.BUY
        and broker_position.market.epic == request.epic
        and broker_position.size == request.requested_quantity
    )
    checks.append(("EXACT_BROKER_POSITION", exact))
    passed = tuple(name for name, condition in checks if condition)
    failed = tuple(name for name, condition in checks if not condition)
    if not configuration.enabled or not configuration.automatic_exit_enabled:
        status = ExitPreflightStatus.DISABLED
    elif failed:
        status = ExitPreflightStatus.BLOCKED
    else:
        status = ExitPreflightStatus.READY
    fields = {
        "close_request_id": request.close_request_id,
        "status": status,
        "passed_gates": passed,
        "failed_gates": failed,
        "reason_codes": failed,
        "validated_quantity": request.requested_quantity
        if status is ExitPreflightStatus.READY
        else None,
        "position_snapshot_id": snapshot.snapshot_id,
        "account_snapshot_id": snapshot.account_snapshot_id,
        "market_snapshot_id": snapshot.market_snapshot_id,
        "lifecycle_configuration_fingerprint": configuration.configuration_fingerprint,
    }
    identity = fingerprint(fields)
    return ExitPreflightResult.model_validate(
        {**fields, "preflight_id": identity, "preflight_fingerprint": identity}
    )
