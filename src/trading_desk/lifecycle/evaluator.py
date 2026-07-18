"""Deterministic exit evaluation with explicit protective precedence."""

from datetime import datetime

from trading_desk.lifecycle.config import LifecycleConfiguration
from trading_desk.lifecycle.fingerprints import fingerprint
from trading_desk.lifecycle.models import (
    CloseSide,
    DemoPositionSnapshot,
    ExitDecision,
    ExitDecisionStatus,
    ExitReason,
    LifecycleMarketStatus,
    LifecycleRiskState,
    PositionStatus,
    StrategyExitState,
)


def evaluate_exit(
    snapshot: DemoPositionSnapshot,
    risk: LifecycleRiskState,
    strategy_exit: StrategyExitState,
    evaluation_timestamp: datetime,
    configuration: LifecycleConfiguration,
    *,
    market_closure_required: bool = False,
) -> ExitDecision:
    passed: list[str] = []
    failed: list[str] = []
    reasons: list[ExitReason] = []
    status = ExitDecisionStatus.HOLD

    def gate(name: str, condition: bool) -> bool:
        (passed if condition else failed).append(name)
        return condition

    integrity = gate(
        "INPUT_INTEGRITY",
        snapshot.position_status is PositionStatus.OPEN
        and snapshot.direction.value == "LONG"
        and snapshot.quantity > 0,
    )
    demo = gate("DEMO_ENVIRONMENT", configuration.broker_environment.value == "DEMO")
    market_fresh = gate(
        "MARKET_DATA_FRESH",
        evaluation_timestamp - snapshot.market_timestamp <= configuration.maximum_market_data_age,
    )
    account_fresh = gate(
        "ACCOUNT_STATE_FRESH",
        evaluation_timestamp - risk.timestamp <= configuration.maximum_account_state_age,
    )
    account_known = gate("ACCOUNT_STATE_COMPLETE", risk.state_complete)
    position_exact = gate(
        "POSITION_IDENTITY_EXACT", snapshot.account_snapshot_id == risk.account_snapshot_id
    )
    halt_clear = gate("LIFECYCLE_HALT_CLEAR", not risk.lifecycle_halted)

    if not integrity or not demo or not position_exact:
        status = ExitDecisionStatus.INVALID_STATE
        reasons.append(ExitReason.BROKER_STATE_MISMATCH)
    elif not market_fresh or not account_fresh or not account_known:
        status = ExitDecisionStatus.INVALID_STATE
        reasons.append(
            ExitReason.DATA_STALE if not market_fresh or not account_fresh else ExitReason.UNKNOWN
        )
    elif not halt_clear:
        status = ExitDecisionStatus.EXIT_BLOCKED
        reasons.append(ExitReason.RECONCILIATION_FAILURE)
    else:
        if risk.kill_switch_active:
            reasons.append(ExitReason.KILL_SWITCH)
        if risk.emergency_exit_required:
            reasons.append(ExitReason.EMERGENCY_OPERATOR_POLICY)
        if risk.daily_loss_limit_reached:
            reasons.append(ExitReason.DAILY_LOSS_LIMIT)
        if risk.drawdown_limit_reached:
            reasons.append(ExitReason.DRAWDOWN_LIMIT)
        if risk.risk_limit_breached:
            reasons.append(ExitReason.RISK_LIMIT_BREACH)
        stop_crossed = (
            configuration.allow_stop_exit
            and snapshot.stop_level is not None
            and snapshot.current_bid <= snapshot.stop_level
        )
        target_crossed = (
            configuration.allow_target_exit
            and snapshot.target_level is not None
            and snapshot.current_bid >= snapshot.target_level
        )
        if stop_crossed:
            reasons.append(ExitReason.PROTECTIVE_STOP)
        if market_closure_required:
            reasons.append(ExitReason.MARKET_CLOSURE_POLICY)
        if target_crossed:
            reasons.append(ExitReason.PROFIT_TARGET)
        if configuration.allow_strategy_exit and strategy_exit is StrategyExitState.EXIT:
            reasons.append(ExitReason.STRATEGY_INVALIDATED)
        if (
            configuration.allow_max_holding_exit
            and snapshot.holding_duration >= configuration.maximum_position_age
        ):
            reasons.append(ExitReason.MAXIMUM_HOLDING_PERIOD)
        reasons = _ordered_unique(reasons)
        if reasons:
            emergency = reasons[0] in {
                ExitReason.KILL_SWITCH,
                ExitReason.EMERGENCY_OPERATOR_POLICY,
                ExitReason.DAILY_LOSS_LIMIT,
                ExitReason.DRAWDOWN_LIMIT,
                ExitReason.RISK_LIMIT_BREACH,
            }
            status = (
                ExitDecisionStatus.EMERGENCY_EXIT_REQUIRED
                if emergency
                else ExitDecisionStatus.EXIT_REQUIRED
            )
            if snapshot.market_status not in {
                LifecycleMarketStatus.TRADEABLE,
                LifecycleMarketStatus.CLOSINGS_ONLY,
            }:
                failed.append("MARKET_CLOSE_SUBMISSION_AVAILABLE")
                status = ExitDecisionStatus.EXIT_BLOCKED
        else:
            passed.append("NO_EXIT_TRIGGER")

    primary = reasons[0] if reasons else ExitReason.UNKNOWN
    fields = {
        "position_id": snapshot.position_id,
        "deal_id": snapshot.deal_id,
        "evaluation_timestamp": evaluation_timestamp,
        "status": status,
        "primary_reason": primary,
        "secondary_reasons": tuple(reasons[1:]),
        "requested_quantity": snapshot.quantity,
        "expected_close_side": CloseSide.SELL,
        "reference_price": snapshot.current_bid,
        "stop_level": snapshot.stop_level,
        "target_level": snapshot.target_level,
        "holding_duration": snapshot.holding_duration,
        "current_unrealized_pnl": snapshot.unrealized_pnl,
        "current_risk": snapshot.current_risk,
        "passed_gates": tuple(passed),
        "failed_gates": tuple(failed),
        "reason_codes": tuple(reason.value for reason in reasons),
        "strategy_fingerprint": snapshot.strategy_configuration_fingerprint,
        "risk_fingerprint": snapshot.risk_configuration_fingerprint,
        "lifecycle_configuration_fingerprint": configuration.configuration_fingerprint,
        "position_snapshot_id": snapshot.snapshot_id,
        "market_snapshot_id": snapshot.market_snapshot_id,
        "account_snapshot_id": snapshot.account_snapshot_id,
    }
    identity = fingerprint(fields)
    return ExitDecision.model_validate(
        {**fields, "exit_decision_id": identity, "decision_fingerprint": identity}
    )


def _ordered_unique(reasons: list[ExitReason]) -> list[ExitReason]:
    precedence = (
        ExitReason.KILL_SWITCH,
        ExitReason.EMERGENCY_OPERATOR_POLICY,
        ExitReason.DAILY_LOSS_LIMIT,
        ExitReason.DRAWDOWN_LIMIT,
        ExitReason.RISK_LIMIT_BREACH,
        ExitReason.PROTECTIVE_STOP,
        ExitReason.MARKET_CLOSURE_POLICY,
        ExitReason.PROFIT_TARGET,
        ExitReason.STRATEGY_INVALIDATED,
        ExitReason.MAXIMUM_HOLDING_PERIOD,
    )
    return [reason for reason in precedence if reason in reasons]
