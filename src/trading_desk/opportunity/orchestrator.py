"""Authority-separated orchestration for ranked Demo opportunities."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from trading_desk.execution.models import ReconciliationStatus
from trading_desk.opportunity.campaign import DemoCampaignSnapshot, halt_campaign
from trading_desk.opportunity.exploration import authorize_for_risk
from trading_desk.opportunity.exposure import CurrentExposureSnapshot
from trading_desk.opportunity.journal import OpportunityJournal
from trading_desk.opportunity.ledger import DemoTradeLedger, DemoTradeStatus
from trading_desk.opportunity.models import OpportunityCandidate
from trading_desk.opportunity.preflight import exploration_preflight
from trading_desk.opportunity.risk import to_risk_candidate
from trading_desk.opportunity.scheduler import ScheduledOpportunityEvaluation
from trading_desk.opportunity.service import OpportunityCycleResult, OpportunityCycleService
from trading_desk.opportunity.state import update_state
from trading_desk.risk.models import ApprovedTradeIntent, RiskDecision, RiskDecisionStatus


class OpportunityRiskPort(Protocol):
    async def evaluate(self, candidate: object, evaluated_at: datetime) -> RiskDecision: ...


class ControlledDemoExecutionPort(Protocol):
    async def submit(self, intent: ApprovedTradeIntent) -> object: ...


class PositionLifecyclePort(Protocol):
    async def monitor(self, observed_at: datetime) -> object: ...


class OpportunityExposurePort(Protocol):
    async def snapshot(self, observed_at: datetime) -> CurrentExposureSnapshot: ...


class CampaignStatePort(Protocol):
    def load(self) -> DemoCampaignSnapshot: ...

    def save(self, snapshot: DemoCampaignSnapshot) -> None: ...

    async def refresh_runtime(self, observed_at: datetime) -> DemoCampaignSnapshot: ...


class OpportunityOrchestrationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    cycle: OpportunityCycleResult
    risk_decision_ids: tuple[str, ...]
    execution_submission_count: int
    lifecycle_ran: bool
    entry_halted: bool


class OpportunityOrchestrator:
    def __init__(
        self,
        cycle_service: OpportunityCycleService,
        risk: OpportunityRiskPort,
        execution: ControlledDemoExecutionPort,
        lifecycle: PositionLifecyclePort,
        exposure: OpportunityExposurePort | None = None,
        ledger: DemoTradeLedger | None = None,
        campaign: CampaignStatePort | None = None,
        journal: OpportunityJournal | None = None,
        maximum_total_submissions: int | None = None,
    ) -> None:
        if maximum_total_submissions is not None and maximum_total_submissions < 1:
            raise ValueError("total submission limit must be positive")
        self.cycle_service = cycle_service
        self.risk = risk
        self.execution = execution
        self.lifecycle = lifecycle
        self.exposure = exposure
        self.ledger = ledger
        self.campaign = campaign
        self.journal = journal
        self.maximum_total_submissions = maximum_total_submissions

    async def run(
        self,
        cycle_timestamp: datetime,
        *,
        explicit_demo_enable: bool,
        entry_halted: bool = False,
        unresolved_execution_ambiguity: bool = False,
        reconciliation_mismatch: bool = False,
        scheduled_evaluations: tuple[ScheduledOpportunityEvaluation, ...] | None = None,
    ) -> OpportunityOrchestrationResult:
        decisions: list[str] = []
        submissions = 0
        try:
            if self.campaign is not None:
                refresh = getattr(self.campaign, "refresh_runtime", None)
                if callable(refresh):
                    await refresh(cycle_timestamp)
                snapshot = self.campaign.load()
                halt_reason = None
                if unresolved_execution_ambiguity:
                    halt_reason = "UNRESOLVED_EXECUTION_AMBIGUITY"
                elif reconciliation_mismatch:
                    halt_reason = "RECONCILIATION_MISMATCH"
                if halt_reason and halt_reason not in snapshot.halt_reasons:
                    halted_campaign = halt_campaign(
                        snapshot,
                        cycle_timestamp,
                        halt_reason,
                        execution_incident=unresolved_execution_ambiguity,
                        reconciliation_incident=reconciliation_mismatch,
                    )
                    self.campaign.save(halted_campaign)
                    if self.journal is not None:
                        self.journal.append_campaign(halted_campaign)
            entry_halted = entry_halted or self._submission_limit_reached()
            exposure = (
                await self.exposure.snapshot(cycle_timestamp) if self.exposure is not None else None
            )
            if self.exposure is not None and exposure is None:
                raise ValueError("authoritative current exposure is unavailable")
            update_holdings = getattr(self.cycle_service.provider, "set_holding_epics", None)
            if exposure is not None and callable(update_holdings):
                update_holdings(exposure.existing_epics)
            cycle = await self.cycle_service.run_cycle(
                cycle_timestamp,
                existing_epics=exposure.existing_epics if exposure else (),
                occupied_correlation_groups=(
                    exposure.occupied_correlation_groups if exposure else ()
                ),
                recent_entries=exposure.recently_closed if exposure else (),
                current_position_count=exposure.current_position_count if exposure else 0,
                scheduled_evaluations=scheduled_evaluations,
            )
            selected = set(cycle.ranking.selected_candidate_ids)
            candidates = tuple(item for item in cycle.candidates if item.candidate_id in selected)
            for candidate in candidates:
                if self._submission_limit_reached():
                    break
                authorization = authorize_for_risk(
                    candidate,
                    self.cycle_service.engine.exploration,
                    explicit_enable=explicit_demo_enable,
                    entry_halted=entry_halted,
                )
                if not authorization.authorized_for_risk:
                    continue
                campaign = self.campaign.load() if self.campaign is not None else None
                if self.ledger is not None:
                    preflight = exploration_preflight(
                        candidate,
                        observed_at=cycle_timestamp,
                        engine=self.cycle_service.engine.configuration,
                        exploration=self.cycle_service.engine.exploration,
                        explicit_authorization=explicit_demo_enable,
                        exposure=exposure,
                        ledger=self.ledger,
                        campaign=campaign,
                        unresolved_execution_ambiguity=unresolved_execution_ambiguity,
                        reconciliation_mismatch=reconciliation_mismatch,
                    )
                    if not preflight.ready:
                        if self.journal is not None:
                            self.journal.append_preflight_rejection(
                                candidate.candidate_id, cycle_timestamp, preflight
                            )
                        continue
                decision = await self.risk.evaluate(to_risk_candidate(candidate), cycle_timestamp)
                decisions.append(decision.decision_id)
                if self.journal is not None:
                    self.journal.append_risk_decision(candidate.candidate_id, decision)
                if (
                    decision.status is RiskDecisionStatus.APPROVED
                    and decision.approved_intent is not None
                ):
                    outcome = await self.execution.submit(decision.approved_intent)
                    result = getattr(outcome, "result", None)
                    submitted_at = getattr(result, "submitted_at", None)
                    if submitted_at is not None:
                        submissions += 1
                        if self._submission_limit_reached():
                            self._latch_submission_limit()
                    status = getattr(result, "status", None)
                    reconciliation = getattr(outcome, "reconciliation", None)
                    reconciliation_status = getattr(reconciliation, "status", None)
                    execution_unresolved = (
                        submitted_at is not None and getattr(status, "value", "") != "ACCEPTED"
                    )
                    reconciliation_failed = submitted_at is not None and (
                        reconciliation_status is not ReconciliationStatus.RECONCILED
                    )
                    if execution_unresolved or reconciliation_failed:
                        halt_reason = (
                            "UNRESOLVED_EXECUTION_AMBIGUITY"
                            if execution_unresolved
                            else "RECONCILIATION_MISMATCH"
                        )
                        state = self.cycle_service.state_store.load()
                        self.cycle_service.state_store.save(
                            update_state(
                                state,
                                entries_halted=True,
                                halt_reasons=tuple(
                                    dict.fromkeys((*state.halt_reasons, halt_reason))
                                ),
                            )
                        )
                        if self.campaign is not None:
                            snapshot = self.campaign.load()
                            halted_campaign = halt_campaign(
                                snapshot,
                                cycle_timestamp,
                                halt_reason,
                                execution_incident=execution_unresolved,
                                reconciliation_incident=reconciliation_failed,
                            )
                            self.campaign.save(halted_campaign)
                            if self.journal is not None:
                                self.journal.append_campaign(halted_campaign)
                    if self._submission_limit_reached():
                        break
        finally:
            await self.lifecycle.monitor(cycle_timestamp)
        return OpportunityOrchestrationResult(
            cycle=cycle,
            risk_decision_ids=tuple(decisions),
            execution_submission_count=submissions,
            lifecycle_ran=True,
            entry_halted=entry_halted or self._submission_limit_reached(),
        )

    def _submission_limit_reached(self) -> bool:
        if self.maximum_total_submissions is None or self.ledger is None:
            return False
        submitted = sum(
            1 for item in self.ledger.load().records if item.status is DemoTradeStatus.SUBMITTED
        )
        return submitted >= self.maximum_total_submissions

    def _latch_submission_limit(self) -> None:
        state = self.cycle_service.state_store.load()
        self.cycle_service.state_store.save(
            update_state(
                state,
                entries_halted=True,
                halt_reasons=tuple(
                    dict.fromkeys((*state.halt_reasons, "TOTAL_SUBMISSION_LIMIT_REACHED"))
                ),
            )
        )


def selected_candidates(result: OpportunityCycleResult) -> tuple[OpportunityCandidate, ...]:
    selected = set(result.ranking.selected_candidate_ids)
    return tuple(item for item in result.candidates if item.candidate_id in selected)
