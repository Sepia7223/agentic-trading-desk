from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trading_desk.ai import AIAnalyst, AIAnalystConfiguration, AnalysisMode
from trading_desk.ai.models import HistoricalExample
from trading_desk.ai.provider import DeterministicFakeProvider

NOW = datetime(2026, 7, 15, 15, 0, tzinfo=UTC)


def enabled_configuration(**updates: object) -> AIAnalystConfiguration:
    values: dict[str, object] = {
        "provider_name": "deterministic-fake",
        "model_name": "fake-v1",
        "analysis_enabled": True,
    }
    values.update(updates)
    return AIAnalystConfiguration.model_validate(values)


def analyst(**configuration_updates: object) -> tuple[AIAnalyst, DeterministicFakeProvider]:
    provider = DeterministicFakeProvider()
    return AIAnalyst(enabled_configuration(**configuration_updates), provider), provider


def context_for(mode: AnalysisMode) -> dict[str, object]:
    common: dict[str, object] = {"instrument": "EUR/USD"}
    if mode is AnalysisMode.SIGNAL_EXPLANATION:
        return {**common, "signal_action": "NO_TRADE", "regime": "TRANSITIONAL"}
    if mode is AnalysisMode.RISK_DECISION_EXPLANATION:
        return {**common, "risk_status": "REJECTED", "risk_reason_codes": ("STALE",)}
    if mode is AnalysisMode.TRADE_REVIEW:
        return {**common, "net_pnl": Decimal("-10"), "financial_outcome": "LOSS"}
    if mode in {
        AnalysisMode.DAILY_REVIEW,
        AnalysisMode.WEEKLY_REVIEW,
        AnalysisMode.MONTHLY_REVIEW,
        AnalysisMode.PORTFOLIO_SUMMARY,
    }:
        return {"portfolio_equity": Decimal("100000"), "drawdown": Decimal("0.01")}
    return {**common, "historical_summary": "Structured evidence supplied."}


def historical(record_id: str = "history-1", *, days_ago: int = 1) -> HistoricalExample:
    return HistoricalExample(
        record_id=record_id,
        timestamp=NOW - timedelta(days=days_ago),
        instrument="EUR/USD",
        strategy_variant="BASELINE_KALMAN_HMM",
        regime="BULL_LOW_VOL",
        risk_status="APPROVED",
        reason_codes=(),
        financial_outcome="PROFIT",
        process_classification="GOOD_PROCESS",
        net_return=Decimal("0.01"),
        holding_period_seconds=Decimal("3600"),
        spread=Decimal("1.2"),
        volatility=Decimal("0.01"),
        drawdown=Decimal("0.005"),
    )
