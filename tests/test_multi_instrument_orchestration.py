import asyncio
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from opportunity_helpers import NOW, evidence
from trading_desk.opportunity.config import (
    DemoExplorationConfiguration,
    OpportunityEngineConfiguration,
)
from trading_desk.opportunity.engine import OpportunityEngine
from trading_desk.opportunity.errors import OpportunityStateError
from trading_desk.opportunity.orchestrator import OpportunityOrchestrator
from trading_desk.opportunity.scheduler import plan_completed_bars
from trading_desk.opportunity.service import OpportunityCycleService
from trading_desk.opportunity.state import OpportunityStateStore
from trading_desk.risk.models import RiskDecisionStatus


class EvidenceProvider:
    async def evaluate(self, market, timeframe, cycle_timestamp):  # type: ignore[no-untyped-def]
        return (
            evidence(
                created_at=cycle_timestamp,
                instrument_id=market.instrument_id,
                epic=market.epic,
                timeframe=timeframe,
                completed_bar_timestamp=cycle_timestamp - timedelta(seconds=timeframe.seconds),
                current_bid=evidence().current_bid,
                current_ask=evidence().current_ask,
                spread_observed_at=cycle_timestamp,
                correlation_groups=market.correlation_groups,
                evidence_ids=(f"{market.instrument_id}:{timeframe.value}",),
            ),
        )


def test_cycle_scans_every_market_timeframe_and_persists_idempotency(tmp_path: Path) -> None:
    service = OpportunityCycleService(
        OpportunityEngine(OpportunityEngineConfiguration(enabled=True)),
        EvidenceProvider(),
        OpportunityStateStore(tmp_path / "state.json"),
    )
    result = asyncio.run(service.run_cycle(NOW))
    assert result.diagnostic.counters.markets_scanned == 6
    assert result.diagnostic.counters.instrument_timeframes_evaluated == 18
    with pytest.raises(OpportunityStateError):
        asyncio.run(service.run_cycle(NOW))


def test_completed_bar_schedule_is_bounded_and_deterministic() -> None:
    service = OpportunityEngine(OpportunityEngineConfiguration(enabled=True))
    first = plan_completed_bars(service.universe, NOW, maximum_catch_up_bars=2)
    second = plan_completed_bars(service.universe, NOW, maximum_catch_up_bars=2)
    assert first == second
    assert len(first) == 18
    assert all(item.completed_bar_timestamp < NOW for item in first)


class RejectingRisk:
    calls = 0

    async def evaluate(self, candidate, evaluated_at):  # type: ignore[no-untyped-def]
        del candidate, evaluated_at
        self.calls += 1
        return SimpleNamespace(
            decision_id="risk-rejected",
            status=RiskDecisionStatus.REJECTED,
            approved_intent=None,
        )


class NoExecution:
    calls = 0

    async def submit(self, intent):  # type: ignore[no-untyped-def]
        del intent
        self.calls += 1


class LifecycleMonitor:
    calls = 0

    async def monitor(self, observed_at):  # type: ignore[no-untyped-def]
        del observed_at
        self.calls += 1


def test_risk_rejection_blocks_execution_and_lifecycle_is_independent(tmp_path: Path) -> None:
    cycle = OpportunityCycleService(
        OpportunityEngine(
            OpportunityEngineConfiguration(enabled=True),
            DemoExplorationConfiguration(enabled=True),
        ),
        EvidenceProvider(),
        OpportunityStateStore(tmp_path / "orchestrator.json"),
    )
    risk = RejectingRisk()
    execution = NoExecution()
    lifecycle = LifecycleMonitor()
    orchestrator = OpportunityOrchestrator(cycle, risk, execution, lifecycle)  # type: ignore[arg-type]
    result = asyncio.run(orchestrator.run(NOW, explicit_demo_enable=True))
    assert result.lifecycle_ran
    assert risk.calls > 0
    assert execution.calls == 0
    assert lifecycle.calls == 1
    with pytest.raises(OpportunityStateError):
        asyncio.run(orchestrator.run(NOW, explicit_demo_enable=True))
    assert lifecycle.calls == 2
