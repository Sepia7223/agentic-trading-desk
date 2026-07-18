"""Authority-separated orchestration for ranked Demo opportunities."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from trading_desk.opportunity.exploration import authorize_for_risk
from trading_desk.opportunity.models import OpportunityCandidate
from trading_desk.opportunity.risk import to_risk_candidate
from trading_desk.opportunity.service import OpportunityCycleResult, OpportunityCycleService
from trading_desk.risk.models import ApprovedTradeIntent, RiskDecision, RiskDecisionStatus


class OpportunityRiskPort(Protocol):
    async def evaluate(self, candidate: object, evaluated_at: datetime) -> RiskDecision: ...


class ControlledDemoExecutionPort(Protocol):
    async def submit(self, intent: ApprovedTradeIntent) -> object: ...


class PositionLifecyclePort(Protocol):
    async def monitor(self, observed_at: datetime) -> object: ...


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
    ) -> None:
        self.cycle_service = cycle_service
        self.risk = risk
        self.execution = execution
        self.lifecycle = lifecycle

    async def run(
        self,
        cycle_timestamp: datetime,
        *,
        explicit_demo_enable: bool,
        entry_halted: bool = False,
    ) -> OpportunityOrchestrationResult:
        decisions: list[str] = []
        submissions = 0
        try:
            cycle = await self.cycle_service.run_cycle(cycle_timestamp)
            selected = set(cycle.ranking.selected_candidate_ids)
            candidates = tuple(item for item in cycle.candidates if item.candidate_id in selected)
            for candidate in candidates:
                authorization = authorize_for_risk(
                    candidate,
                    self.cycle_service.engine.exploration,
                    explicit_enable=explicit_demo_enable,
                    entry_halted=entry_halted,
                )
                if not authorization.authorized_for_risk:
                    continue
                decision = await self.risk.evaluate(to_risk_candidate(candidate), cycle_timestamp)
                decisions.append(decision.decision_id)
                if (
                    decision.status is RiskDecisionStatus.APPROVED
                    and decision.approved_intent is not None
                ):
                    await self.execution.submit(decision.approved_intent)
                    submissions += 1
        finally:
            await self.lifecycle.monitor(cycle_timestamp)
        return OpportunityOrchestrationResult(
            cycle=cycle,
            risk_decision_ids=tuple(decisions),
            execution_submission_count=submissions,
            lifecycle_ran=True,
            entry_halted=entry_halted,
        )


def selected_candidates(result: OpportunityCycleResult) -> tuple[OpportunityCandidate, ...]:
    selected = set(result.ranking.selected_candidate_ids)
    return tuple(item for item in result.candidates if item.candidate_id in selected)
