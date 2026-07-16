from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path

from ai_helpers import NOW, analyst
from portfolio_helpers import approval, configured_portfolio, later
from risk_helpers import NOW as RISK_NOW
from test_signal_pipeline import _candidate as strategy_candidate
from trading_desk.ai.adapters import (
    closed_trade_context,
    portfolio_state_context,
    risk_decision_context,
    strategy_signal_context,
)
from trading_desk.ai.models import AnalysisMode, AnalysisStatus


def test_strategy_signal_to_append_only_advisory_record() -> None:
    candidate = strategy_candidate()
    before = candidate.model_dump(mode="python")
    service, _ = analyst()
    result = asyncio.run(
        service.analyze_context(
            mode=AnalysisMode.SIGNAL_EXPLANATION,
            created_at=candidate.evaluation_timestamp,
            source_record_ids=(candidate.configuration_fingerprint,),
            raw_context=strategy_signal_context(candidate),
            strategy_configuration_fingerprint=candidate.configuration_fingerprint,
        )
    )
    assert result.status is AnalysisStatus.COMPLETED
    assert len(service.journal.records()) == 1
    assert candidate.model_dump(mode="python") == before


def test_risk_decision_to_advisory_record_without_mutation() -> None:
    portfolio = configured_portfolio()
    decision, candidate, _ = approval(portfolio)
    before = decision.model_dump(mode="python")
    service, _ = analyst()
    result = asyncio.run(
        service.analyze_context(
            mode=AnalysisMode.RISK_DECISION_EXPLANATION,
            created_at=NOW,
            source_record_ids=(decision.decision_id,),
            raw_context=risk_decision_context(decision, candidate.instrument),
            strategy_configuration_fingerprint=decision.strategy_configuration_fingerprint,
            risk_configuration_fingerprint=decision.risk_configuration_fingerprint,
        )
    )
    assert result.status is AnalysisStatus.COMPLETED
    assert decision.model_dump(mode="python") == before


def test_closed_trade_review_and_portfolio_daily_review_are_read_only() -> None:
    portfolio = configured_portfolio()
    decision, candidate, quote = approval(portfolio)
    opened = portfolio.open_position(decision, candidate, quote, RISK_NOW)
    assert opened.position is not None
    closed = portfolio.close_position(
        opened.position.position_id,
        quote.model_copy(update={"timestamp": later(), "bid": quote.bid, "ask": quote.ask}),
        later(),
    )
    state_before = deepcopy(portfolio.state)
    service, _ = analyst()
    trade_result = asyncio.run(
        service.analyze_context(
            mode=AnalysisMode.TRADE_REVIEW,
            created_at=later(),
            source_record_ids=(closed.trade.trade_id,),
            raw_context=closed_trade_context(closed.trade),
            strategy_configuration_fingerprint=closed.trade.strategy_configuration_fingerprint,
            risk_configuration_fingerprint=closed.trade.risk_configuration_fingerprint,
            portfolio_configuration_fingerprint=(closed.trade.portfolio_configuration_fingerprint),
        )
    )
    daily_result = asyncio.run(
        service.analyze_context(
            mode=AnalysisMode.DAILY_REVIEW,
            created_at=later(),
            source_record_ids=(portfolio.state.snapshot_id,),
            raw_context=portfolio_state_context(portfolio.state),
            portfolio_configuration_fingerprint=portfolio.state.configuration_fingerprint,
        )
    )
    assert trade_result.status is AnalysisStatus.COMPLETED
    assert daily_result.status is AnalysisStatus.COMPLETED
    assert portfolio.state == state_before


def test_ai_package_has_no_broker_network_execution_or_mutation_dependencies() -> None:
    root = Path("src/trading_desk/ai")
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    forbidden = (
        "trading_desk.ig",
        "httpx",
        "openai",
        "trading_desk.portfolio.engine",
        "trading_desk.risk.engine",
        "place_order",
        "execute_order",
        "/positions/otc",
        "OPENAI_API_KEY",
        "IG_API_KEY",
        "X-SECURITY-TOKEN",
    )
    assert all(item not in source for item in forbidden)
