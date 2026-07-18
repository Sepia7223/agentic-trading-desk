from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from trading_desk.context.fingerprints import fingerprint
from trading_desk.journal.config import JournalConfiguration
from trading_desk.journal.models import JournalRecordType
from trading_desk.journal.sqlite import SQLiteJournalRepository
from trading_desk.journal.strategy import StrategyGovernanceJournal
from trading_desk.journal.writer import DurableJournalWriter
from trading_desk.strategy.artifacts import (
    REQUIRED_ARTIFACT_FILES,
    build_artifact_package,
    verify_artifact_package,
)
from trading_desk.strategy.circuit_breakers import (
    BreakerState,
    CircuitBreakerConfiguration,
    CircuitBreakerStore,
    clear_circuit_breaker,
    evaluate_circuit_breaker,
    initial_circuit_breaker,
)
from trading_desk.strategy.validation import (
    ValidationGates,
    ValidationTrade,
    calculate_metrics,
    cost_stress,
    evaluate_gates,
)
from trading_desk.strategy.validation_state import (
    PromotionDecisionType,
    StrategyLifecycleState,
    promotion_decision,
)

NOW = datetime(2026, 7, 18, 12, tzinfo=UTC)


def trade(index: int, pnl: str) -> ValidationTrade:
    return ValidationTrade(
        trade_id=str(index),
        strategy_id="research",
        instrument_id="EUR/USD",
        timeframe="HOUR",
        regime="RANGE",
        entry_at=NOW + timedelta(hours=index * 2),
        exit_at=NOW + timedelta(hours=index * 2 + 1),
        gross_pnl=Decimal(pnl),
        spread_cost=Decimal("0.05"),
        slippage_cost=Decimal("0.02"),
        commission_cost=Decimal("0"),
        funding_cost=Decimal("0"),
        turnover=Decimal("100"),
    )


def test_validation_metrics_and_cost_stress_are_deterministic() -> None:
    trades = tuple(trade(index, value) for index, value in enumerate(("2", "-1", "3", "-1")))
    first = calculate_metrics(trades, candidate_count=8)
    assert first == calculate_metrics(trades, candidate_count=8)
    assert first.closed_trade_count == 4
    assert first.candidate_to_trade_conversion == Decimal("0.5")
    scenarios = cost_stress(trades, "research")
    assert tuple(item.cost_multiplier for item in scenarios) == (
        Decimal("1"),
        Decimal("1.25"),
        Decimal("1.50"),
        Decimal("2.00"),
    )
    assert evaluate_gates(first, ValidationGates()) == (
        "MINIMUM_CLOSED_TRADES",
        "MAXIMUM_DRAWDOWN",
    )


def test_promotion_requires_valid_transition_and_no_failed_gates() -> None:
    fields = dict(
        strategy_id="research",
        strategy_version="1.0.0",
        decision=PromotionDecisionType.PROMOTE_TO_BACKTEST_VALIDATED,
        previous_state=StrategyLifecycleState.RESEARCH_ONLY,
        new_state=StrategyLifecycleState.BACKTEST_VALIDATED,
        created_at=NOW,
        validation_report_id="report",
        validation_artifact_fingerprint="a" * 64,
        dataset_fingerprint="b" * 64,
        configuration_fingerprint="c" * 64,
        required_gates=("MINIMUM_CLOSED_TRADES",),
        observed_metrics=(("trades", "120"),),
        failed_gates=(),
        approver="human-review",
        notes="explicit",
    )
    assert promotion_decision(**fields).new_state is StrategyLifecycleState.BACKTEST_VALIDATED
    fields["failed_gates"] = ("MINIMUM_CLOSED_TRADES",)
    with pytest.raises(ValidationError, match="failed validation gates"):
        promotion_decision(**fields)


def test_explicit_promotion_decision_is_journaled_without_execution(tmp_path: Path) -> None:
    decision = promotion_decision(
        strategy_id="research",
        strategy_version="1.0.0",
        decision=PromotionDecisionType.REMAIN_RESEARCH_ONLY,
        previous_state=StrategyLifecycleState.RESEARCH_ONLY,
        new_state=StrategyLifecycleState.RESEARCH_ONLY,
        created_at=NOW,
        validation_report_id="report",
        validation_artifact_fingerprint="a" * 64,
        dataset_fingerprint="b" * 64,
        configuration_fingerprint="c" * 64,
        required_gates=("MINIMUM_CLOSED_TRADES",),
        observed_metrics=(("trades", "0"),),
        failed_gates=("MINIMUM_CLOSED_TRADES",),
        approver="human-review",
    )
    with SQLiteJournalRepository(
        JournalConfiguration(database_path=tmp_path / "journal.sqlite3")
    ) as repository:
        record = StrategyGovernanceJournal(
            DurableJournalWriter(repository)
        ).append_promotion_decision(decision)
    assert record.record_type is JournalRecordType.STRATEGY_PROMOTION_DECISION_CREATED
    assert record.environment == "LOCAL"


def test_artifact_integrity_rejects_corruption(tmp_path: Path) -> None:
    documents = {
        name: ("# Research only" if name.endswith(".md") else {"status": "RESEARCH_ONLY"})
        for name in REQUIRED_ARTIFACT_FILES
        if name != "manifest.json"
    }
    directory = tmp_path / "artifact"
    manifest = build_artifact_package(
        directory,
        strategy_id="research",
        strategy_version="1.0.0",
        dataset_fingerprint="d" * 64,
        configuration_fingerprint="c" * 64,
        documents=documents,
        created_at=NOW,
    )
    assert verify_artifact_package(directory) == manifest
    (directory / "validation_results.json").write_text("corrupt", encoding="utf-8")
    with pytest.raises(ValueError, match="integrity"):
        verify_artifact_package(directory)


def test_repository_validation_artifacts_are_sealed_and_research_stays_unpromoted() -> None:
    root = Path("artifacts/strategy_validation")
    for strategy in (
        "trend-regime-v1-1.0.0",
        "trend-pullback-v1-1.0.0",
        "volatility-breakout-1.0.0",
        "range-mean-reversion-1.0.0",
    ):
        assert verify_artifact_package(root / strategy).complete
    for strategy in (
        "trend-pullback-v1-1.0.0",
        "volatility-breakout-1.0.0",
        "range-mean-reversion-1.0.0",
    ):
        decision = (root / strategy / "promotion_decision.json").read_text(encoding="utf-8")
        assert "REMAIN_RESEARCH_ONLY" in decision
        assert '"automatic_promotion": false' in decision


def test_strategy_breaker_persists_and_only_halts_entries(tmp_path: Path) -> None:
    state = initial_circuit_breaker("trend-pullback-v1", date(2026, 7, 18)).model_copy(
        update={"consecutive_losses": 5}
    )
    fields = state.model_dump(mode="python", exclude={"state_fingerprint"})
    state = type(state).model_validate({**fields, "state_fingerprint": fingerprint(fields)})
    triggered = evaluate_circuit_breaker(state, CircuitBreakerConfiguration(), NOW)
    assert triggered.state is BreakerState.TRIGGERED
    assert not triggered.entries_allowed
    assert (
        evaluate_circuit_breaker(triggered, CircuitBreakerConfiguration(), NOW + timedelta(hours=1))
        == triggered
    )
    with pytest.raises(ValueError, match="named authority"):
        clear_circuit_breaker(triggered, authority="", observed_at=NOW)
    assert clear_circuit_breaker(
        triggered, authority="operator-review", observed_at=NOW
    ).entries_allowed
    other = initial_circuit_breaker("volatility-breakout", date(2026, 7, 18))
    assert other.entries_allowed
    store = CircuitBreakerStore(tmp_path / "breakers.json")
    store.save((triggered, other))
    assert store.load() == (triggered, other)
