"""Milestone 14 analytics: funnel, counterfactuals, windows, and comparison."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading_desk.analytics import (
    FunnelStage,
    FunnelTally,
    MeasureConvention,
    RejectionTally,
    TradeEvidence,
    WindowBoundary,
    build_funnel,
    build_scorecard,
    build_window_scorecards,
    compare_scorecards,
)

CONVENTION = MeasureConvention()
START = datetime(2026, 3, 2, 8, 0, tzinfo=UTC)


def trade(index: int, gross: str, *, strategy: str = "trend-regime-v1") -> TradeEvidence:
    entry = START + timedelta(days=index)
    return TradeEvidence(
        trade_id=f"trade-{index:03d}",
        source_record_ids=(f"open-{index:03d}", f"close-{index:03d}"),
        strategy_id=strategy,
        instrument="CS.D.EURUSD.MINI.IP",
        timeframe="HOUR",
        regime="TREND_UP",
        exit_reason="PROFIT_TARGET",
        currency="USD",
        entry_at=entry,
        exit_at=entry + timedelta(hours=2),
        gross_return=Decimal(gross),
        spread_cost=Decimal("0.0002"),
        slippage_cost=Decimal("0.0001"),
        commission_cost=Decimal("0"),
        funding_cost=Decimal("0.0001"),
        turnover=Decimal("1"),
    )


TALLY = FunnelTally(
    discovered=1000,
    evaluated=800,
    selected=120,
    execution_approved=60,
    executed=50,
    closed=48,
    rejections=(
        RejectionTally(reason="STRATEGY_NO_SIGNAL", count=680),
        RejectionTally(reason="RISK_REJECTED", count=60),
        RejectionTally(reason="CORRELATION", count=10),
    ),
    system_halts=2,
)


def test_funnel_stage_counts_and_conversions_are_deterministic() -> None:
    funnel = build_funnel(TALLY)
    assert tuple(s.stage for s in funnel.stages) == (
        FunnelStage.DISCOVERED,
        FunnelStage.EVALUATED,
        FunnelStage.SELECTED,
        FunnelStage.EXECUTION_APPROVED,
        FunnelStage.EXECUTED,
        FunnelStage.CLOSED,
    )
    first = funnel.conversions[0]
    assert first.from_stage is FunnelStage.DISCOVERED
    assert first.to_stage is FunnelStage.EVALUATED
    assert first.rate.value == Decimal("0.80000000")
    assert funnel.overall_conversion.value == (Decimal(48) / Decimal(1000)).quantize(
        Decimal("0.00000001")
    )
    assert funnel.system_halts == 2
    assert build_funnel(TALLY).funnel_id == funnel.funnel_id


def test_counterfactual_never_estimates_foregone_pnl() -> None:
    funnel = build_funnel(TALLY)
    assert funnel.counterfactual.accepted == 50
    assert funnel.counterfactual.rejected == 750
    assert funnel.counterfactual.foregone_outcome.available is False
    assert funnel.counterfactual.foregone_outcome.reason == "NO_HINDSIGHT_COUNTERFACTUAL"
    reasons = [item.reason for item in funnel.counterfactual.rejections]
    assert reasons == sorted(reasons)


def test_zero_upstream_stage_makes_conversion_unavailable() -> None:
    empty = FunnelTally(
        discovered=0, evaluated=0, selected=0, execution_approved=0, executed=0, closed=0
    )
    funnel = build_funnel(empty)
    assert all(conv.rate.available is False for conv in funnel.conversions)
    assert funnel.overall_conversion.available is False
    assert funnel.overall_conversion.reason == "NO_UPSTREAM_CANDIDATES"


def test_funnel_fingerprint_rejects_tampering() -> None:
    funnel = build_funnel(TALLY)
    payload = funnel.model_dump(mode="python")
    payload["system_halts"] = 99
    with pytest.raises(ValidationError):
        type(funnel).model_validate(payload)


def test_window_scorecards_partition_on_half_open_boundaries() -> None:
    trades = tuple(trade(i, "0.0100") for i in range(6))
    boundaries = (
        WindowBoundary(label="w1", start=START, end=START + timedelta(days=3)),
        WindowBoundary(label="w2", start=START + timedelta(days=3), end=START + timedelta(days=6)),
    )
    windows = build_window_scorecards(trades, CONVENTION, boundaries)
    assert [w.boundary.label for w in windows] == ["w1", "w2"]
    # exits land at day+2h; day 0,1,2 in w1 and day 3,4,5 in w2 → 3 trades each.
    assert windows[0].scorecard.trade_count == 3
    assert windows[1].scorecard.trade_count == 3
    total = windows[0].scorecard.trade_count + windows[1].scorecard.trade_count
    assert total == len(trades)


def test_window_scorecards_are_order_independent_by_boundary_start() -> None:
    trades = tuple(trade(i, "0.0100") for i in range(4))
    a = WindowBoundary(label="early", start=START, end=START + timedelta(days=2))
    b = WindowBoundary(label="late", start=START + timedelta(days=2), end=START + timedelta(days=4))
    forward = build_window_scorecards(trades, CONVENTION, (a, b))
    reversed_ = build_window_scorecards(trades, CONVENTION, (b, a))
    assert [w.boundary.label for w in forward] == [w.boundary.label for w in reversed_]
    assert forward[0].scorecard.scorecard_id == reversed_[0].scorecard.scorecard_id


def test_paper_vs_demo_comparison_computes_available_deltas() -> None:
    paper = build_scorecard(tuple(trade(i, "0.0100") for i in range(5)), CONVENTION)
    demo = build_scorecard(tuple(trade(i, "0.0060") for i in range(5)), CONVENTION)
    comparison = compare_scorecards(paper, demo)
    assert comparison.comparable is True
    assert comparison.baseline_id == paper.scorecard_id
    assert comparison.candidate_id == demo.scorecard_id
    net = next(d for d in comparison.deltas if d.name == "net_return")
    assert net.delta.available is True
    assert paper.net_return.value is not None and demo.net_return.value is not None
    assert net.delta.value == (demo.net_return.value - paper.net_return.value).quantize(
        Decimal("0.00000001")
    )
    count = next(d for d in comparison.deltas if d.name == "trade_count")
    assert count.delta.value == Decimal("0")


def test_comparison_blocks_value_deltas_on_convention_mismatch() -> None:
    paper = build_scorecard(tuple(trade(i, "0.0100") for i in range(3)), CONVENTION)
    demo = build_scorecard(
        tuple(trade(i, "0.0100") for i in range(3)),
        MeasureConvention(reporting_currency="EUR"),
    )
    comparison = compare_scorecards(paper, demo)
    assert comparison.comparable is False
    assert comparison.reason == "CONVENTION_MISMATCH"
    assert all(d.delta.available is False for d in comparison.deltas)
    assert all(d.delta.reason == "CONVENTION_MISMATCH" for d in comparison.deltas)


def test_comparison_propagates_unavailable_operands() -> None:
    populated = build_scorecard(tuple(trade(i, "0.0100") for i in range(4)), CONVENTION)
    empty = build_scorecard((), CONVENTION)
    comparison = compare_scorecards(populated, empty)
    assert comparison.comparable is True
    net = next(d for d in comparison.deltas if d.name == "net_return")
    assert net.delta.available is False
    assert net.delta.reason.startswith("CANDIDATE_")


def test_window_boundary_rejects_inverted_range() -> None:
    with pytest.raises(ValidationError):
        WindowBoundary(label="bad", start=START, end=START - timedelta(days=1))
