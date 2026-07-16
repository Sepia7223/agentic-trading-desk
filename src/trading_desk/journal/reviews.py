"""Deterministic post-trade review calculations before AI interpretation."""

from __future__ import annotations

from decimal import Decimal

from trading_desk.journal.fingerprints import fingerprint
from trading_desk.journal.models import (
    FinancialOutcome,
    PaperDemoComparison,
    PaperDemoComparisonInput,
    PostTradeReview,
    PostTradeReviewInput,
    ProcessClassification,
)


def compare_paper_and_demo(source: PaperDemoComparisonInput) -> PaperDemoComparison:
    fields = {
        "comparison_id": source.comparison_id,
        "paper_trade_id": source.paper_trade_id,
        "demo_trade_id": source.demo_trade_id,
        "paper_entry_price": source.paper_entry_price,
        "demo_entry_price": source.demo_entry_price,
        "entry_slippage_difference": source.demo_entry_price - source.paper_entry_price,
        "paper_exit_price": source.paper_exit_price,
        "demo_exit_price": source.demo_exit_price,
        "exit_slippage_difference": _difference(source.demo_exit_price, source.paper_exit_price),
        "quantity_difference": source.demo_quantity - source.paper_quantity,
        "timing_difference_seconds": int(
            (source.demo_entry_timestamp - source.paper_entry_timestamp).total_seconds()
        ),
        "cost_difference": source.demo_costs - source.paper_costs,
        "pnl_difference": _difference(source.demo_pnl, source.paper_pnl),
        "stop_difference": _difference(source.demo_stop, source.paper_stop),
        "target_difference": _difference(source.demo_target, source.paper_target),
    }
    return PaperDemoComparison.model_validate(
        {**fields, "comparison_fingerprint": fingerprint(fields)}
    )


def generate_post_trade_review(source: PostTradeReviewInput) -> PostTradeReview:
    costs = source.commission + source.funding + source.spread_cost + source.slippage_cost
    net_pnl = source.gross_pnl - costs if source.gross_pnl is not None else None
    holding_seconds = (
        int((source.exit_timestamp - source.entry_timestamp).total_seconds())
        if source.exit_timestamp is not None
        else None
    )
    capital = source.entry_price * source.quantity
    return_fraction = net_pnl / capital if net_pnl is not None and capital > 0 else None
    risk_multiple = (
        net_pnl / source.initial_risk_amount
        if net_pnl is not None
        and source.initial_risk_amount is not None
        and source.initial_risk_amount > 0
        else None
    )
    classification = _classification(source)
    outcome = _outcome(net_pnl, source.unresolved, source.exit_timestamp is None)
    fields = {
        "trade_id": source.trade_id,
        "gross_pnl": source.gross_pnl,
        "net_pnl": net_pnl,
        "total_costs": costs,
        "spread_cost": source.spread_cost,
        "slippage_cost": source.slippage_cost,
        "commission": source.commission,
        "funding": source.funding,
        "holding_period_seconds": holding_seconds,
        "maximum_favorable_excursion": source.maximum_favorable_excursion,
        "maximum_adverse_excursion": source.maximum_adverse_excursion,
        "return_fraction": return_fraction,
        "risk_multiple": risk_multiple,
        "entry_regime": source.entry_regime,
        "exit_regime": source.exit_regime,
        "strategy_variant": source.strategy_variant,
        "risk_reason_context": source.risk_reason_context,
        "execution_quality": source.execution_quality,
        "process_classification": classification,
        "financial_outcome": outcome,
    }
    return PostTradeReview.model_validate({**fields, "review_fingerprint": fingerprint(fields)})


def _classification(source: PostTradeReviewInput) -> ProcessClassification:
    if source.unresolved:
        return ProcessClassification.UNRESOLVED
    if source.reconciliation_error:
        return ProcessClassification.RECONCILIATION_ERROR
    if source.execution_error:
        return ProcessClassification.EXECUTION_ERROR
    if source.risk_error:
        return ProcessClassification.RISK_ERROR
    if source.data_error:
        return ProcessClassification.DATA_ERROR
    if source.rule_violation:
        return ProcessClassification.RULE_VIOLATION
    if source.exit_timestamp is None:
        return ProcessClassification.UNKNOWN
    return ProcessClassification.VALID_PROCESS


def _outcome(net_pnl: Decimal | None, unresolved: bool, open_trade: bool) -> FinancialOutcome:
    if unresolved or open_trade:
        return FinancialOutcome.UNREALIZED
    if net_pnl is None:
        return FinancialOutcome.UNKNOWN
    if net_pnl > 0:
        return FinancialOutcome.WIN
    if net_pnl < 0:
        return FinancialOutcome.LOSS
    return FinancialOutcome.BREAKEVEN


def _difference(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    return left - right if left is not None and right is not None else None
