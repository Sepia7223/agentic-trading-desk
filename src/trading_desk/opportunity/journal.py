"""Append-only journal mapping for Opportunity Engine evidence."""

from __future__ import annotations

from trading_desk.journal.models import JournalRecord, JournalRecordType
from trading_desk.journal.writer import DurableJournalWriter, JournalSource
from trading_desk.opportunity.campaign import DemoCampaignSnapshot
from trading_desk.opportunity.models import CandidateStatus
from trading_desk.opportunity.service import OpportunityCycleResult


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
        for candidate in result.candidates:
            instrument_id = f"{candidate.candidate_id}:instrument"
            strategy_id = f"{candidate.candidate_id}:strategy"
            cost_id = f"{candidate.candidate_id}:cost"
            sources.extend(
                (
                    JournalSource(
                        record_type=JournalRecordType.INSTRUMENT_EVALUATED,
                        source_record_id=instrument_id,
                        source_parent_ids=(f"{result.cycle_id}:universe",),
                        payload={
                            "instrument_id": candidate.instrument_id,
                            "epic": candidate.epic,
                            "timeframe": candidate.timeframe,
                            "completed_bar_timestamp": candidate.completed_bar_timestamp,
                        },
                        created_at=timestamp,
                        instrument=candidate.instrument_id,
                        epic=candidate.epic,
                        environment="DEMO",
                    ),
                    JournalSource(
                        record_type=JournalRecordType.STRATEGY_EVALUATED,
                        source_record_id=strategy_id,
                        source_parent_ids=(instrument_id, *candidate.evidence_ids),
                        payload={
                            "strategy_id": candidate.strategy_id,
                            "strategy_fingerprint": candidate.strategy_fingerprint,
                            "validation_states": candidate.strategy_validation_states,
                            "regime": candidate.regime,
                        },
                        created_at=timestamp,
                        instrument=candidate.instrument_id,
                        epic=candidate.epic,
                        strategy_variant=candidate.strategy_id,
                        environment="DEMO",
                        deferred_linkage=True,
                    ),
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
