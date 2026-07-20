"""Milestone 14: operations analytics view reconciles to authoritative P&L."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trading_desk.operations.analytics_views import (
    build_portfolio_analytics,
    trade_evidence_from_record,
)
from trading_desk.operations.models import RecordProjection

BASE = datetime(2026, 4, 1, 9, 0, tzinfo=UTC)


def closed_trade(
    index: int,
    *,
    gross: str,
    net: str,
    commission: str = "0.10",
    slippage: str = "0.05",
    spread: str = "0.03",
    funding: str = "0.02",
    strategy: str = "trend-regime-v1",
    instrument: str = "CS.D.EURUSD.MINI.IP",
    regime: str = "TREND_UP",
    exit_reason: str = "PROFIT_TARGET",
    entry_price: str = "1.1000",
    quantity: str = "10000",
    **overrides: object,
) -> RecordProjection:
    entry = BASE + timedelta(hours=index)
    payload: dict[str, object] = {
        "trade_id": f"trade-{index:03d}",
        "strategy_variant": strategy,
        "instrument": instrument,
        "regime": regime,
        "timeframe": "HOUR",
        "exit_reason": exit_reason,
        "entry_timestamp": entry.isoformat(),
        "exit_timestamp": (entry + timedelta(minutes=30)).isoformat(),
        "entry_price": entry_price,
        "quantity": quantity,
        "gross_pnl": gross,
        "net_pnl": net,
        "entry_commission": commission,
        "exit_commission": "0",
        "slippage_cost": slippage,
        "spread_cost": spread,
        "funding": funding,
    }
    payload.update(overrides)
    return RecordProjection(
        journal_record_id=f"jr-{index:03d}",
        source_record_id=f"src-{index:03d}",
        source_parent_ids=(f"open-{index:03d}",),
        record_type="PAPER_CLOSED_TRADE",
        effective_at=entry + timedelta(minutes=30),
        instrument=instrument,
        strategy_variant=strategy,
        environment="DEMO",
        payload=payload,
        record_fingerprint="f" * 64,
    )


# gross - (0.10 + 0.05 + 0.03 + 0.02) = gross - 0.20 = net
CONSISTENT = (
    closed_trade(0, gross="5.20", net="5.00"),
    closed_trade(1, gross="-2.80", net="-3.00", strategy="range-mean-reversion"),
    closed_trade(2, gross="8.20", net="8.00", instrument="CS.D.GBPUSD.MINI.IP"),
)
FUNNEL_COUNTS = {
    "discovered": 500,
    "evaluated": 400,
    "selected": 40,
    "execution_approved": 12,
    "executed": 12,
    "closed": 3,
    "system_halts": 1,
}
REJECTIONS = {"STRATEGY_OR_REGIME": 360, "RISK_REJECTED": 28}


def test_scorecard_net_reconciles_to_authoritative_sum() -> None:
    result = build_portfolio_analytics(CONSISTENT, (), FUNNEL_COUNTS, REJECTIONS)
    reconciliation = result["reconciliation"]
    assert isinstance(reconciliation, dict)
    assert reconciliation["reconciled"] is True
    assert reconciliation["authoritative_net_pnl"] == "10.00"
    scorecard = result["scorecard"]
    assert isinstance(scorecard, dict)
    assert scorecard["net_return"]["value"] == "10.00000000"
    assert scorecard["trade_count"] == 3
    completeness = result["completeness"]
    assert isinstance(completeness, dict)
    assert completeness["closed_trades_included"] == 3
    assert completeness["closed_trades_excluded"] == 0


def test_inconsistent_decomposition_is_excluded_not_reconciled_away() -> None:
    poisoned = (*CONSISTENT, closed_trade(9, gross="99.00", net="1.00"))
    result = build_portfolio_analytics(poisoned, (), FUNNEL_COUNTS, REJECTIONS)
    completeness = result["completeness"]
    assert isinstance(completeness, dict)
    assert completeness["closed_trades_excluded"] == 1
    exclusions = completeness["exclusions"]
    assert isinstance(exclusions, tuple)
    assert exclusions[0]["reason"] == "PNL_DECOMPOSITION_INCONSISTENT"
    reconciliation = result["reconciliation"]
    assert isinstance(reconciliation, dict)
    # the three consistent trades still reconcile exactly among themselves.
    assert reconciliation["reconciled"] is True
    assert reconciliation["authoritative_net_pnl"] == "10.00"


def test_missing_net_pnl_and_inverted_window_are_reported() -> None:
    missing = closed_trade(20, gross="5.20", net="5.00")
    del missing.payload["net_pnl"]
    inverted = closed_trade(21, gross="5.20", net="5.00")
    inverted.payload["exit_timestamp"] = inverted.payload["entry_timestamp"]
    result = build_portfolio_analytics((missing, inverted), (), FUNNEL_COUNTS, REJECTIONS)
    completeness = result["completeness"]
    assert isinstance(completeness, dict)
    reasons = {item["reason"] for item in completeness["exclusions"]}
    assert reasons == {"MISSING_NET_PNL", "INVALID_TRADE_WINDOW"}
    assert completeness["closed_trades_included"] == 0


def test_derives_gross_when_absent_and_still_reconciles() -> None:
    record = closed_trade(0, gross="5.20", net="5.00")
    del record.payload["gross_pnl"]
    evidence, reason = trade_evidence_from_record(record)
    assert reason is None
    assert evidence is not None
    # derived gross = net + costs = 5.00 + 0.20; net_return recovers 5.00.
    assert evidence.net_return == Decimal("5.00")
    assert evidence.gross_return == Decimal("5.20")


def test_attribution_waterfall_and_funnel_are_present_and_ordered() -> None:
    result = build_portfolio_analytics(CONSISTENT, (), FUNNEL_COUNTS, REJECTIONS)
    waterfall = result["attribution_waterfall"]
    assert isinstance(waterfall, list)
    dimensions = [row["dimension"] for row in waterfall]
    # STRATEGY rows precede INSTRUMENT rows precede TIMEFRAME rows (enum order).
    assert dimensions.index("STRATEGY") < dimensions.index("INSTRUMENT")
    assert dimensions.index("INSTRUMENT") < dimensions.index("TIMEFRAME")
    funnel = result["opportunity_funnel"]
    assert isinstance(funnel, dict)
    assert funnel["stages"][0]["count"] == 500
    assert funnel["counterfactual"]["foregone_outcome"]["available"] is False


def test_view_is_marked_read_only_and_declares_convention() -> None:
    result = build_portfolio_analytics(CONSISTENT, (), FUNNEL_COUNTS, REJECTIONS)
    assert result["authority"] == "READ_ONLY"
    convention = result["convention"]
    assert isinstance(convention, dict)
    assert convention["returns_definition"] == "account_currency_realized_pnl"
    assert isinstance(result["convention_fingerprint"], str)
    assert len(result["convention_fingerprint"]) == 64


def test_empty_population_returns_unavailable_scorecard_without_error() -> None:
    result = build_portfolio_analytics((), (), FUNNEL_COUNTS, REJECTIONS)
    scorecard = result["scorecard"]
    assert isinstance(scorecard, dict)
    assert scorecard["net_return"]["available"] is False
    reconciliation = result["reconciliation"]
    assert isinstance(reconciliation, dict)
    assert reconciliation["authoritative_net_pnl"] == "0"
