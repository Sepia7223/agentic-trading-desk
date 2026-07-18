"""Deterministic post-trade review and analytical Paper/Demo comparison."""

from datetime import datetime, timedelta
from decimal import Decimal

from trading_desk.lifecycle.fingerprints import fingerprint
from trading_desk.lifecycle.models import (
    CloseExecutionResult,
    CloseReconciliationStatus,
    DemoPositionSnapshot,
    ExitReason,
    LifecyclePostTradeReview,
    PaperDemoExitComparison,
)


def create_post_trade_review(
    snapshot: DemoPositionSnapshot,
    result: CloseExecutionResult,
    exit_reason: ExitReason,
) -> LifecyclePostTradeReview:
    if (
        result.confirmed_exit_level is None
        or result.confirmed_quantity is None
        or result.reconciliation_status is not CloseReconciliationStatus.POSITION_CLOSED
    ):
        raise ValueError("post-trade review requires a reconciled confirmed close")
    gross = (result.confirmed_exit_level - snapshot.entry_level) * result.confirmed_quantity
    fields = {
        "position_id": snapshot.position_id,
        "close_request_id": result.close_request_id,
        "exit_reason": exit_reason,
        "entry_level": snapshot.entry_level,
        "confirmed_exit_level": result.confirmed_exit_level,
        "confirmed_quantity": result.confirmed_quantity,
        "gross_pnl": gross,
        "accrued_costs": snapshot.accrued_costs,
        "net_pnl": gross - snapshot.accrued_costs,
        "holding_duration": snapshot.holding_duration,
        "reconciliation_status": result.reconciliation_status,
        "process_classification": "VALID_PROCESS",
        "created_at": result.completed_at,
    }
    identity = fingerprint(fields)
    return LifecyclePostTradeReview.model_validate(
        {**fields, "review_id": identity, "review_fingerprint": identity}
    )


def compare_paper_demo_exit(
    *,
    position_id: str,
    paper_exit_timestamp: datetime,
    demo_exit_timestamp: datetime,
    paper_exit_price: Decimal,
    demo_exit_price: Decimal,
    paper_costs: Decimal,
    demo_costs: Decimal,
    paper_pnl: Decimal,
    demo_pnl: Decimal,
    paper_holding_duration: timedelta,
    demo_holding_duration: timedelta,
    paper_exit_reason: ExitReason,
    demo_exit_reason: ExitReason,
) -> PaperDemoExitComparison:
    fields = {
        "position_id": position_id,
        "paper_exit_timestamp": paper_exit_timestamp,
        "demo_exit_timestamp": demo_exit_timestamp,
        "paper_exit_price": paper_exit_price,
        "demo_exit_price": demo_exit_price,
        "exit_slippage_difference": demo_exit_price - paper_exit_price,
        "cost_difference": demo_costs - paper_costs,
        "pnl_difference": demo_pnl - paper_pnl,
        "holding_period_difference_seconds": Decimal(
            str((demo_holding_duration - paper_holding_duration).total_seconds())
        ),
        "exit_reason_difference": paper_exit_reason is not demo_exit_reason,
    }
    identity = fingerprint(fields)
    return PaperDemoExitComparison.model_validate(
        {**fields, "comparison_id": identity, "comparison_fingerprint": identity}
    )
