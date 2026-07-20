"""Milestone 14 analytics: deterministic attribution with exact reconciliation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading_desk.analytics import (
    DimensionName,
    Measure,
    MeasureConvention,
    TradeEvidence,
    build_scorecard,
)

CONVENTION = MeasureConvention()
START = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


def make_trade(
    index: int,
    gross: str,
    *,
    strategy: str = "trend-regime-v1",
    instrument: str = "CS.D.EURUSD.MINI.IP",
    regime: str = "TREND_UP",
    exit_reason: str = "PROFIT_TARGET",
    currency: str = "USD",
    spread: str = "0.0002",
    slippage: str = "0.0001",
    commission: str = "0",
    funding: str = "0.0001",
) -> TradeEvidence:
    entry = START + timedelta(hours=index)
    return TradeEvidence(
        trade_id=f"trade-{index:03d}",
        source_record_ids=(f"journal-open-{index:03d}", f"journal-close-{index:03d}"),
        strategy_id=strategy,
        instrument=instrument,
        timeframe="HOUR",
        regime=regime,
        exit_reason=exit_reason,
        currency=currency,
        entry_at=entry,
        exit_at=entry + timedelta(minutes=45),
        gross_return=Decimal(gross),
        spread_cost=Decimal(spread),
        slippage_cost=Decimal(slippage),
        commission_cost=Decimal(commission),
        funding_cost=Decimal(funding),
        turnover=Decimal("1"),
    )


SAMPLE = (
    make_trade(0, "0.0120"),
    make_trade(1, "-0.0060", strategy="range-mean-reversion", exit_reason="STOP_LOSS"),
    make_trade(2, "0.0045", instrument="CS.D.GBPUSD.MINI.IP", regime="RANGE_BOUND"),
    make_trade(3, "-0.0020", strategy="volatility-breakout", exit_reason="INVALIDATION"),
    make_trade(4, "0.0080", strategy="range-mean-reversion", regime="RANGE_BOUND"),
)


def test_measure_coherence_is_enforced() -> None:
    with pytest.raises(ValidationError):
        Measure(available=True, value=None)
    with pytest.raises(ValidationError):
        Measure(available=False, value=Decimal("1"))
    with pytest.raises(ValidationError):
        Measure(available=False, reason="")


def test_trade_evidence_rejects_naive_timestamps_and_inverted_windows() -> None:
    with pytest.raises(ValidationError):
        TradeEvidence(
            **{
                **make_trade(0, "0.01").model_dump(),
                "entry_at": datetime(2026, 1, 5, 9, 0),
            }
        )
    with pytest.raises(ValidationError):
        TradeEvidence(
            **{
                **make_trade(0, "0.01").model_dump(),
                "exit_at": START - timedelta(hours=1),
            }
        )


def test_scorecard_reconciles_every_dimension_exactly() -> None:
    scorecard = build_scorecard(SAMPLE, CONVENTION)
    assert scorecard.reconciled is True
    assert scorecard.net_return.available and scorecard.net_return.value is not None
    net_total = scorecard.net_return.value
    gross_total = scorecard.gross_return.value
    assert gross_total is not None
    assert net_total == gross_total - scorecard.costs.total
    for dimension in DimensionName:
        slices = [item for item in scorecard.attribution if item.dimension is dimension]
        assert sum((item.net_return for item in slices), Decimal(0)) == net_total
        assert sum((item.gross_return for item in slices), Decimal(0)) == gross_total
        assert sum((item.total_cost for item in slices), Decimal(0)) == scorecard.costs.total
        assert sum(item.trade_count for item in slices) == len(SAMPLE)


def test_scorecard_is_deterministic_and_order_independent() -> None:
    forward = build_scorecard(SAMPLE, CONVENTION)
    reversed_input = build_scorecard(tuple(reversed(SAMPLE)), CONVENTION)
    assert forward.scorecard_id == reversed_input.scorecard_id
    assert forward.model_dump() == reversed_input.model_dump()


def test_scorecard_measures_match_hand_computation() -> None:
    scorecard = build_scorecard(SAMPLE, CONVENTION)
    assert scorecard.trade_count == 5
    assert scorecard.source_record_count == 10
    assert scorecard.win_rate.value == Decimal("0.60000000")
    assert scorecard.costs.total == Decimal("0.0020")
    assert scorecard.gross_return.value == Decimal("0.01650000")
    assert scorecard.net_return.value == Decimal("0.01450000")
    assert scorecard.expectancy.value == Decimal("0.00290000")
    assert scorecard.turnover.value == Decimal("5.00000000")
    assert scorecard.exposure_seconds.value == Decimal(5 * 45 * 60)
    assert scorecard.profit_factor.available
    assert scorecard.maximum_drawdown.available
    assert scorecard.input_start == START
    assert scorecard.input_end == START + timedelta(hours=4, minutes=45)


def test_empty_population_yields_unavailable_measures_not_zeroes() -> None:
    scorecard = build_scorecard((), CONVENTION)
    assert scorecard.trade_count == 0
    assert scorecard.reconciled is True
    for measure in (
        scorecard.gross_return,
        scorecard.net_return,
        scorecard.win_rate,
        scorecard.expectancy,
        scorecard.profit_factor,
        scorecard.sharpe_like,
    ):
        assert measure.available is False
        assert measure.reason == "NO_CLOSED_TRADES"
        assert measure.value is None


def test_foreign_currency_blocks_currency_measures_instead_of_fabricating() -> None:
    mixed = SAMPLE + (make_trade(9, "0.0100", currency="JPY"),)
    scorecard = build_scorecard(mixed, CONVENTION)
    assert scorecard.reconciled is False
    for measure in (
        scorecard.gross_return,
        scorecard.net_return,
        scorecard.expectancy,
        scorecard.cost_drag,
    ):
        assert measure.available is False
        assert measure.reason == "CURRENCY_CONVERSION_EVIDENCE_UNAVAILABLE"
    assert scorecard.win_rate.available is True


def test_drawdown_and_recovery_track_the_worst_underwater_run() -> None:
    trades = (
        make_trade(0, "0.0100"),
        make_trade(1, "-0.0060"),
        make_trade(2, "-0.0040"),
        make_trade(3, "0.0020"),
        make_trade(4, "0.0150"),
    )
    scorecard = build_scorecard(trades, CONVENTION)
    costs_each = Decimal("0.0004")
    losses = (Decimal("0.0060") + costs_each) + (Decimal("0.0040") + costs_each)
    partial_recovery = Decimal("0.0020") - costs_each
    assert scorecard.maximum_drawdown.value == (losses).quantize(Decimal("0.00000001"))
    assert scorecard.recovery_duration_trades.value == Decimal(3)
    assert partial_recovery > 0


def test_single_trade_risk_ratios_are_unavailable() -> None:
    scorecard = build_scorecard((make_trade(0, "0.0100"),), CONVENTION)
    assert scorecard.sharpe_like.available is False
    assert scorecard.sharpe_like.reason == "INSUFFICIENT_OBSERVATIONS"
    assert scorecard.sortino_like.available is False
    assert scorecard.sortino_like.reason == "NO_LOSSES"


def test_scorecard_fingerprint_rejects_tampering() -> None:
    scorecard = build_scorecard(SAMPLE, CONVENTION)
    payload = scorecard.model_dump(mode="python")
    payload["trade_count"] = 99
    with pytest.raises(ValidationError):
        type(scorecard).model_validate(payload)


def test_convention_travels_with_result_and_is_fingerprinted() -> None:
    scorecard = build_scorecard(SAMPLE, CONVENTION)
    assert scorecard.convention.reporting_currency == "USD"
    assert scorecard.convention.timezone == "UTC"
    assert len(scorecard.convention.fingerprint) == 64
