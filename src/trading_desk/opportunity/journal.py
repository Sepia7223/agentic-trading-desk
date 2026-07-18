"""Append-only journal mapping for Opportunity Engine evidence."""

from __future__ import annotations

from trading_desk.journal.models import JournalRecord, JournalRecordType
from trading_desk.journal.writer import DurableJournalWriter, JournalSource
from trading_desk.opportunity.campaign import DemoCampaignSnapshot
from trading_desk.opportunity.models import CandidateStatus
from trading_desk.opportunity.preflight import ExplorationPreflightDecision
from trading_desk.opportunity.service import OpportunityCycleResult
from trading_desk.risk.models import RiskDecision, RiskDecisionStatus


class OpportunityJournal:
    """Writes one atomic, replayable evidence group per completed cycle."""

    def __init__(self, writer: DurableJournalWriter) -> None:
        self.writer = writer

    def append_cycle(self, result: OpportunityCycleResult) -> tuple[JournalRecord, ...]:
        timestamp = result.cycle_timestamp
        sources: list[JournalSource] = [
            JournalSource(
                record_type=JournalRecordType.OPPORTUNITY_CYCLE_STARTED,
                source_record_id=f"{result.cycle_id}:started",
                payload={
                    "cycle_id": result.cycle_id,
                    "configuration_fingerprint": result.configuration_fingerprint,
                },
                created_at=timestamp,
                environment="DEMO",
            ),
            JournalSource(
                record_type=JournalRecordType.MARKET_UNIVERSE_LOADED,
                source_record_id=f"{result.cycle_id}:universe",
                source_parent_ids=(f"{result.cycle_id}:started",),
                payload={"universe_fingerprint": result.universe_fingerprint},
                created_at=timestamp,
                environment="DEMO",
            ),
        ]
        for evaluation in result.evaluations:
            instrument_id = f"{evaluation.evaluation_id}:instrument"
            sources.extend(
                (
                    JournalSource(
                        record_type=JournalRecordType.INSTRUMENT_EVALUATED,
                        source_record_id=instrument_id,
                        source_parent_ids=(f"{result.cycle_id}:universe",),
                        payload=evaluation,
                        created_at=timestamp,
                        instrument=evaluation.instrument_id,
                        epic=evaluation.epic,
                        environment="DEMO",
                    ),
                    JournalSource(
                        record_type=JournalRecordType.STRATEGY_EVALUATED,
                        source_record_id=f"{evaluation.evaluation_id}:strategies",
                        source_parent_ids=(instrument_id,),
                        payload={
                            "strategy_evaluations": evaluation.strategy_evaluations,
                            "research_only_evaluations": evaluation.research_only_evaluations,
                            "demo_executable_evaluations": (evaluation.demo_executable_evaluations),
                            "candidate_ids": evaluation.candidate_ids,
                            "rejection_codes": evaluation.rejection_codes,
                        },
                        created_at=timestamp,
                        instrument=evaluation.instrument_id,
                        epic=evaluation.epic,
                        environment="DEMO",
                    ),
                )
            )
        for candidate in result.candidates:
            strategy_id = next(
                (
                    f"{evaluation.evaluation_id}:strategies"
                    for evaluation in result.evaluations
                    if candidate.candidate_id in evaluation.candidate_ids
                ),
                f"{result.cycle_id}:universe",
            )
            cost_id = f"{candidate.candidate_id}:cost"
            sources.extend(
                (
                    JournalSource(
                        record_type=JournalRecordType.OPPORTUNITY_CANDIDATE_CREATED,
                        source_record_id=candidate.candidate_id,
                        source_parent_ids=(strategy_id,),
                        payload=candidate,
                        created_at=timestamp,
                        instrument=candidate.instrument_id,
                        epic=candidate.epic,
                        strategy_variant=candidate.strategy_id,
                        environment="DEMO",
                    ),
                    JournalSource(
                        record_type=JournalRecordType.OPPORTUNITY_COST_ESTIMATED,
                        source_record_id=cost_id,
                        source_parent_ids=(candidate.candidate_id,),
                        payload=candidate.costs,
                        created_at=timestamp,
                        instrument=candidate.instrument_id,
                        epic=candidate.epic,
                        strategy_variant=candidate.strategy_id,
                        environment="DEMO",
                    ),
                    JournalSource(
                        record_type=JournalRecordType.OPPORTUNITY_REJECTED
                        if candidate.status is not CandidateStatus.ELIGIBLE
                        else JournalRecordType.OPPORTUNITY_SCORED,
                        source_record_id=f"{candidate.candidate_id}:outcome",
                        source_parent_ids=(cost_id,),
                        payload={
                            "status": candidate.status,
                            "score": candidate.opportunity_score,
                            "net_expected_value": candidate.net_expected_value,
                            "rejection_reasons": candidate.rejection_reasons,
                        },
                        created_at=timestamp,
                        instrument=candidate.instrument_id,
                        epic=candidate.epic,
                        strategy_variant=candidate.strategy_id,
                        environment="DEMO",
                    ),
                )
            )
            if candidate.status is CandidateStatus.SUPPRESSED:
                correlation = any(
                    "CORRELATION" in reason.value for reason in candidate.rejection_reasons
                )
                sources.append(
                    JournalSource(
                        record_type=(
                            JournalRecordType.OPPORTUNITY_CORRELATION_REJECTED
                            if correlation
                            else JournalRecordType.OPPORTUNITY_DUPLICATE_SUPPRESSED
                        ),
                        source_record_id=f"{candidate.candidate_id}:suppression",
                        source_parent_ids=(f"{candidate.candidate_id}:outcome",),
                        payload={"rejection_reasons": candidate.rejection_reasons},
                        created_at=timestamp,
                        instrument=candidate.instrument_id,
                        epic=candidate.epic,
                        strategy_variant=candidate.strategy_id,
                        environment="DEMO",
                    )
                )
        sources.extend(
            (
                JournalSource(
                    record_type=JournalRecordType.OPPORTUNITY_RANKING_CREATED,
                    source_record_id=result.ranking.ranking_id,
                    source_parent_ids=tuple(item.candidate_id for item in result.candidates),
                    payload=result.ranking,
                    created_at=timestamp,
                    environment="DEMO",
                ),
                *(
                    JournalSource(
                        record_type=JournalRecordType.OPPORTUNITY_SELECTED,
                        source_record_id=f"{candidate_id}:selected",
                        source_parent_ids=(result.ranking.ranking_id, candidate_id),
                        payload={"candidate_id": candidate_id},
                        created_at=timestamp,
                        environment="DEMO",
                    )
                    for candidate_id in result.ranking.selected_candidate_ids
                ),
                JournalSource(
                    record_type=JournalRecordType.INACTIVITY_DIAGNOSTIC_CREATED,
                    source_record_id=result.diagnostic.diagnostic_id,
                    source_parent_ids=(result.ranking.ranking_id,),
                    payload=result.diagnostic,
                    created_at=timestamp,
                    environment="DEMO",
                ),
                JournalSource(
                    record_type=JournalRecordType.OPPORTUNITY_CYCLE_COMPLETED,
                    source_record_id=result.cycle_id,
                    source_parent_ids=(
                        result.ranking.ranking_id,
                        result.diagnostic.diagnostic_id,
                    ),
                    payload=result,
                    created_at=timestamp,
                    environment="DEMO",
                ),
            )
        )
        return self.writer.append_sources(sources)

    def append_failure(
        self,
        cycle_id: str,
        created_at,
        reason_code: str,  # type: ignore[no-untyped-def]
    ) -> JournalRecord:
        return self.writer.append_source(
            record_type=JournalRecordType.OPPORTUNITY_CYCLE_FAILED,
            source_record_id=f"{cycle_id}:failed:{reason_code}",
            source={"cycle_id": cycle_id, "reason_code": reason_code},
            created_at=created_at,
            environment="DEMO",
        )

    def append_risk_decision(
        self, candidate_id: str, decision: RiskDecision
    ) -> tuple[JournalRecord, ...]:
        submitted = JournalSource(
            record_type=JournalRecordType.OPPORTUNITY_RISK_SUBMITTED,
            source_record_id=f"{decision.decision_id}:submitted",
            source_parent_ids=(candidate_id,),
            payload={"candidate_id": candidate_id, "decision_id": decision.decision_id},
            created_at=decision.decision_timestamp,
            environment="DEMO",
        )
        outcome = JournalSource(
            record_type=(
                JournalRecordType.OPPORTUNITY_EXECUTION_APPROVED
                if decision.status is RiskDecisionStatus.APPROVED
                else JournalRecordType.OPPORTUNITY_RISK_REJECTED
            ),
            source_record_id=f"{decision.decision_id}:outcome",
            source_parent_ids=(submitted.source_record_id,),
            payload={
                "candidate_id": candidate_id,
                "decision_id": decision.decision_id,
                "status": decision.status,
                "reason_codes": decision.reason_codes,
            },
            created_at=decision.decision_timestamp,
            environment="DEMO",
        )
        return self.writer.append_sources((submitted, outcome))

    def append_preflight_rejection(
        self,
        candidate_id: str,
        created_at,  # type: ignore[no-untyped-def]
        decision: ExplorationPreflightDecision,
    ) -> JournalRecord:
        return self.writer.append_source(
            record_type=JournalRecordType.OPPORTUNITY_REJECTED,
            source_record_id=f"{candidate_id}:preflight:{'-'.join(decision.rejection_codes)}",
            source_parent_ids=(candidate_id,),
            source={
                "candidate_id": candidate_id,
                "stage": "DEMO_EXPLORATION_PREFLIGHT",
                "rejection_codes": decision.rejection_codes,
            },
            created_at=created_at,
            environment="DEMO",
        )

    def append_campaign(self, snapshot: DemoCampaignSnapshot) -> JournalRecord:
        record_type = (
            JournalRecordType.DEMO_CAMPAIGN_HALTED
            if snapshot.entry_halted
            else JournalRecordType.DEMO_CAMPAIGN_SNAPSHOT_CREATED
        )
        return self.writer.append_source(
            record_type=record_type,
            source_record_id=snapshot.snapshot_fingerprint,
            source=snapshot,
            created_at=snapshot.snapshot_at,
            environment="DEMO",
        )

    def append_campaign_started(self, snapshot: DemoCampaignSnapshot) -> JournalRecord:
        return self.writer.append_source(
            record_type=JournalRecordType.DEMO_CAMPAIGN_STARTED,
            source_record_id=f"{snapshot.campaign_id}:started",
            source=snapshot,
            created_at=snapshot.started_at,
            environment="DEMO",
        )
