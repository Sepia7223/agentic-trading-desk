"""Milestone 14 analytics: currency-aware attribution over authoritative trades."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from trading_desk.analytics import (
    ClosedTradeSource,
    ConversionPolicy,
    ConversionRate,
    DimensionName,
    build_ledger_attribution,
)

START = datetime(2026, 2, 2, 8, 0, tzinfo=UTC)
USD_POLICY = ConversionPolicy(reporting_currency="USD")


def source(
    index: int,
    pnl: str | None,
    *,
    strategy: str = "trend-regime-v1",
    instrument: str = "CS.D.EURUSD.MINI.IP",
    currency: str = "USD",
    regime: str = "TREND_UP",
    exit_reason: str = "PROFIT_TARGET",
    observed_cost: str = "0.50",
    estimated_cost: str = "0.40",
    holding: str | None = "3600",
) -> ClosedTradeSource:
    return ClosedTradeSource(
        record_id=f"ledger-{index:03d}",
        source_record_ids=(f"exec-{index:03d}", f"close-{index:03d}"),
        strategy_id=strategy,
        instrument=instrument,
        timeframe="HOUR",
        regime=regime,
        exit_reason=exit_reason,
        currency=currency,
        occurred_at=START + timedelta(hours=index),
        holding_period_seconds=None if holding is None else Decimal(holding),
        realized_pnl=None if pnl is None else Decimal(pnl),
        estimated_cost=Decimal(estimated_cost),
        observed_cost=Decimal(observed_cost),
    )


SAMPLE = (
    source(0, "12.00"),
    source(1, "-6.00", strategy="range-mean-reversion", exit_reason="STOP_LOSS"),
    source(2, "4.50", instrument="CS.D.GBPUSD.MINI.IP", regime="RANGE_BOUND"),
    source(3, "8.00", strategy="range-mean-reversion", regime="RANGE_BOUND"),
)


def test_native_currency_totals_are_authoritative_and_reconcile() -> None:
    report = build_ledger_attribution(SAMPLE, USD_POLICY)
    assert report.reconciled is True
    assert len(report.native) == 1
    block = report.native[0]
    assert block.currency == "USD"
    assert block.gross_realized == Decimal("18.50")
    assert block.observed_cost == Decimal("2.00")
    assert block.net_realized == Decimal("16.50")
    assert block.implementation_shortfall == Decimal("2.00") - Decimal("1.60")
    for dimension in DimensionName:
        slices = [s for s in report.attribution if s.dimension is dimension]
        assert sum((s.gross_realized for s in slices), Decimal(0)) == block.gross_realized
        assert sum((s.net_realized for s in slices), Decimal(0)) == block.net_realized
        assert sum(s.trade_count for s in slices) == block.trade_count


def test_report_is_deterministic_and_order_independent() -> None:
    forward = build_ledger_attribution(SAMPLE, USD_POLICY)
    shuffled = build_ledger_attribution((SAMPLE[2], SAMPLE[0], SAMPLE[3], SAMPLE[1]), USD_POLICY)
    assert forward.report_id == shuffled.report_id


def test_completeness_declares_ledger_limits_instead_of_fabricating() -> None:
    report = build_ledger_attribution(SAMPLE, USD_POLICY)
    assert report.completeness.notional_normalized_returns.available is False
    assert report.completeness.notional_normalized_returns.reason == "NO_ENTRY_NOTIONAL_IN_LEDGER"
    assert report.completeness.cost_decomposition.available is False
    assert report.completeness.cost_decomposition.reason == "LEDGER_RECORDS_AGGREGATE_COST_ONLY"
    assert report.completeness.included == 4
    assert report.completeness.excluded == 0


def test_missing_pnl_and_currency_rows_are_excluded_not_zeroed() -> None:
    rows = SAMPLE + (
        source(8, None),
        source(9, "5.00", currency=""),
    )
    report = build_ledger_attribution(rows, USD_POLICY)
    assert report.trade_count == 4
    reasons = {item.reason for item in report.excluded}
    assert reasons == {"MISSING_REALIZED_PNL", "CURRENCY_EVIDENCE_UNAVAILABLE"}
    assert report.completeness.excluded == 2


def test_reporting_rollup_available_only_with_dated_conversion_evidence() -> None:
    mixed = SAMPLE + (source(10, "900.00", instrument="CS.D.USDJPY.MINI.IP", currency="JPY"),)
    without_rate = build_ledger_attribution(mixed, USD_POLICY)
    assert without_rate.reporting_net.available is False
    assert without_rate.reporting_net.reason.startswith("MISSING_CONVERSION_RATE")
    assert "JPY" in without_rate.reporting_net.reason
    assert len(without_rate.native) == 2

    policy = ConversionPolicy(
        reporting_currency="USD",
        rates=(
            ConversionRate(
                from_currency="JPY",
                to_currency="USD",
                rate=Decimal("0.0066"),
                as_of=START - timedelta(days=1),
                source_record_id="fx-jpy-usd-1",
            ),
        ),
    )
    with_rate = build_ledger_attribution(mixed, policy)
    assert with_rate.reporting_net.available is True
    assert with_rate.reporting_gross.available is True
    usd_block = next(b for b in with_rate.native if b.currency == "USD")
    jpy_block = next(b for b in with_rate.native if b.currency == "JPY")
    expected = usd_block.net_realized + jpy_block.net_realized * Decimal("0.0066")
    assert with_rate.reporting_net.value == expected.quantize(Decimal("0.00000001"))


def test_conversion_rate_must_predate_the_trade() -> None:
    mixed = SAMPLE + (source(10, "900.00", currency="JPY"),)
    stale_only_future = ConversionPolicy(
        reporting_currency="USD",
        rates=(
            ConversionRate(
                from_currency="JPY",
                to_currency="USD",
                rate=Decimal("0.0066"),
                as_of=START + timedelta(days=30),
                source_record_id="fx-future",
            ),
        ),
    )
    report = build_ledger_attribution(mixed, stale_only_future)
    assert report.reporting_gross.available is False
    assert report.reporting_gross.reason.startswith("MISSING_CONVERSION_RATE")


def test_conversion_policy_rejects_rates_not_targeting_reporting_currency() -> None:
    with pytest.raises(ValidationError):
        ConversionPolicy(
            reporting_currency="USD",
            rates=(
                ConversionRate(
                    from_currency="JPY",
                    to_currency="EUR",
                    rate=Decimal("0.0060"),
                    as_of=START,
                    source_record_id="fx-bad",
                ),
            ),
        )


def test_missing_holding_period_marks_exposure_unavailable() -> None:
    rows = tuple(s.model_copy(update={"holding_period_seconds": None}) for s in SAMPLE)
    report = build_ledger_attribution(rows, USD_POLICY)
    assert report.exposure_seconds.available is False
    assert report.exposure_seconds.reason == "NO_HOLDING_PERIOD_EVIDENCE"
    assert report.completeness.records_missing_holding_period == 4


def test_empty_population_is_reconciled_with_unavailable_rollup() -> None:
    report = build_ledger_attribution((), USD_POLICY)
    assert report.trade_count == 0
    assert report.reconciled is True
    assert report.reporting_gross.available is False
    assert report.reporting_gross.reason == "NO_CLOSED_TRADES"


def test_report_fingerprint_rejects_tampering() -> None:
    report = build_ledger_attribution(SAMPLE, USD_POLICY)
    payload = report.model_dump(mode="python")
    payload["trade_count"] = 99
    with pytest.raises(ValidationError):
        type(report).model_validate(payload)


def test_analytics_package_has_no_operational_or_mutation_dependencies() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "trading_desk" / "analytics"
    forbidden = re.compile(
        r"from trading_desk\.(ig|execution|lifecycle|api|operations|risk|portfolio|opportunity)"
        r"|import httpx|import requests"
    )
    for path in root.glob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                assert not forbidden.search(stripped), f"{path.name}: {stripped}"
