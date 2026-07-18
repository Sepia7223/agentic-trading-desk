import asyncio
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from opportunity_helpers import NOW, evidence
from trading_desk.execution.models import ExecutionStatus, ReconciliationStatus
from trading_desk.opportunity.campaign import campaign_snapshot
from trading_desk.opportunity.config import (
    DemoCampaignConfiguration,
    DemoExplorationConfiguration,
    OpportunityEngineConfiguration,
)
from trading_desk.opportunity.engine import OpportunityEngine
from trading_desk.opportunity.errors import OpportunityStateError
from trading_desk.opportunity.exposure import CurrentExposureSnapshot
from trading_desk.opportunity.fingerprints import fingerprint
from trading_desk.opportunity.ledger import DemoTradeLedger, DemoTradeStatus
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


def test_cycle_capacity_uses_persisted_fair_rotation(tmp_path: Path) -> None:
    service = OpportunityCycleService(
        OpportunityEngine(
            OpportunityEngineConfiguration(
                enabled=True,
                maximum_evaluations_per_cycle=1,
            )
        ),
        EvidenceProvider(),
        OpportunityStateStore(tmp_path / "fair-state.json"),
    )
    first = asyncio.run(service.run_cycle(NOW))
    second = asyncio.run(service.run_cycle(NOW + timedelta(minutes=5)))
    assert not first.cycle_complete
    assert not second.cycle_complete
    assert first.evaluations[0].instrument_id != second.evaluations[0].instrument_id or (
        first.evaluations[0].timeframe != second.evaluations[0].timeframe
    )
    assert first.skipped_evaluation_ids
    assert service.state_store.load().missed_evaluation_count > 0


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


def test_total_submission_limit_survives_restart_and_blocks_risk(tmp_path: Path) -> None:
    state_store = OpportunityStateStore(tmp_path / "certification-state.json")
    cycle = OpportunityCycleService(
        OpportunityEngine(
            OpportunityEngineConfiguration(enabled=True),
            DemoExplorationConfiguration(enabled=True),
        ),
        EvidenceProvider(),
        state_store,
    )
    ledger = DemoTradeLedger(tmp_path / "certification-ledger.json")
    ledger.append(
        ledger.create_record(
            occurred_at=NOW - timedelta(minutes=5),
            status=DemoTradeStatus.SUBMITTED,
            strategy="trend-regime-v1",
            instrument="EUR/USD",
            timeframe="MINUTE_5",
            regime="BULL_LOW_VOL",
            session="DEMO",
            candidate_id="prior-candidate",
            execution_id="prior-execution",
        )
    )
    risk = RejectingRisk()
    execution = NoExecution()
    lifecycle = LifecycleMonitor()
    result = asyncio.run(
        OpportunityOrchestrator(
            cycle,
            risk,
            execution,
            lifecycle,
            ledger=ledger,
            maximum_total_submissions=1,
        ).run(NOW, explicit_demo_enable=True)
    )
    assert result.entry_halted
    assert risk.calls == 0
    assert execution.calls == 0
    assert lifecycle.calls == 1


def test_reconciliation_mismatch_latches_halt_after_single_submission(tmp_path: Path) -> None:
    state_store = OpportunityStateStore(tmp_path / "mismatch-state.json")
    ledger = DemoTradeLedger(tmp_path / "mismatch-ledger.json")
    cycle = OpportunityCycleService(
        OpportunityEngine(
            OpportunityEngineConfiguration(enabled=True),
            DemoExplorationConfiguration(enabled=True),
        ),
        EvidenceProvider(),
        state_store,
    )
    exposure_fields = {"observed_at": NOW, "positions": (), "recently_closed": ()}
    exposure = CurrentExposureSnapshot(
        **exposure_fields,
        snapshot_fingerprint=fingerprint(exposure_fields),
    )
    campaign = campaign_snapshot(
        campaign_id="campaign",
        campaign_name="Certification",
        started_at=NOW - timedelta(days=1),
        observed_at=NOW,
        current_balance=Decimal("20000"),
        current_equity=Decimal("20000"),
        maximum_equity=Decimal("20000"),
        daily_pnl=Decimal("0"),
        weekly_drawdown_percent=Decimal("0"),
        consecutive_losses=0,
        configuration=DemoCampaignConfiguration(enabled=True),
        starting_balance=Decimal("20000"),
    )

    class Exposure:
        async def snapshot(self, observed_at):  # type: ignore[no-untyped-def]
            del observed_at
            return exposure

    class Campaign:
        def load(self):  # type: ignore[no-untyped-def]
            return campaign

        def save(self, snapshot):  # type: ignore[no-untyped-def]
            del snapshot

    class ApprovedRisk:
        async def evaluate(self, candidate, evaluated_at):  # type: ignore[no-untyped-def]
            del candidate, evaluated_at
            return SimpleNamespace(
                decision_id="approved-risk",
                status=RiskDecisionStatus.APPROVED,
                approved_intent=object(),
            )

    class MismatchedExecution:
        async def submit(self, intent):  # type: ignore[no-untyped-def]
            del intent
            ledger.append(
                ledger.create_record(
                    occurred_at=NOW,
                    status=DemoTradeStatus.SUBMITTED,
                    strategy="trend-regime-v1",
                    instrument="EUR/USD",
                    timeframe="MINUTE_5",
                    regime="BULL_LOW_VOL",
                    session="DEMO",
                    candidate_id="candidate",
                    execution_id="execution",
                )
            )
            return SimpleNamespace(
                result=SimpleNamespace(
                    submitted_at=NOW,
                    status=ExecutionStatus.ACCEPTED,
                ),
                reconciliation=SimpleNamespace(status=ReconciliationStatus.RECONCILIATION_MISMATCH),
            )

    result = asyncio.run(
        OpportunityOrchestrator(
            cycle,
            ApprovedRisk(),
            MismatchedExecution(),
            LifecycleMonitor(),
            exposure=Exposure(),
            ledger=ledger,
            campaign=Campaign(),
            maximum_total_submissions=1,
        ).run(NOW, explicit_demo_enable=True)
    )

    assert result.execution_submission_count == 1
    assert result.entry_halted
    assert "RECONCILIATION_MISMATCH" in state_store.load().halt_reasons
    assert "TOTAL_SUBMISSION_LIMIT_REACHED" in state_store.load().halt_reasons
