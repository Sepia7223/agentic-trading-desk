"""Bounded provider-neutral multi-market Opportunity cycle service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.context.models import ContextTimeframe
from trading_desk.opportunity.config import MarketDefinition
from trading_desk.opportunity.correlation import suppress_candidates
from trading_desk.opportunity.diagnostics import (
    ActivityCounters,
    InactivityDiagnostic,
    diagnose_inactivity,
)
from trading_desk.opportunity.engine import OpportunityEngine
from trading_desk.opportunity.errors import OpportunityStateError
from trading_desk.opportunity.fingerprints import fingerprint
from trading_desk.opportunity.models import (
    CandidateEvidence,
    OpportunityCandidate,
    OpportunityEvaluationRecord,
    OpportunityRanking,
    OpportunityRejectionCode,
)
from trading_desk.opportunity.ranking import rank_candidates
from trading_desk.opportunity.scheduler import ScheduledOpportunityEvaluation, plan_completed_bars
from trading_desk.opportunity.state import OpportunityStateStore, update_state


class OpportunityEvidenceProvider(Protocol):
    async def evaluate(
        self,
        market: MarketDefinition,
        timeframe: ContextTimeframe,
        cycle_timestamp: datetime,
        *,
        completed_bar_timestamp: datetime | None = None,
    ) -> tuple[CandidateEvidence, ...]: ...


class OpportunityCycleJournal(Protocol):
    def append_cycle(self, result: OpportunityCycleResult) -> object: ...

    def append_failure(self, cycle_id: str, created_at: datetime, reason_code: str) -> object: ...


class OpportunityCycleResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    cycle_id: str = Field(min_length=64, max_length=64)
    cycle_timestamp: datetime
    universe_fingerprint: str
    configuration_fingerprint: str
    evaluation_keys: tuple[str, ...]
    evaluations: tuple[OpportunityEvaluationRecord, ...]
    skipped_evaluation_ids: tuple[str, ...]
    cycle_complete: bool
    candidates: tuple[OpportunityCandidate, ...]
    ranking: OpportunityRanking
    diagnostic: InactivityDiagnostic
    result_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("cycle_timestamp")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("cycle timestamp must be UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def identity(self):  # type: ignore[no-untyped-def]
        expected = fingerprint(self.model_dump(mode="python", exclude={"result_fingerprint"}))
        if self.result_fingerprint != expected:
            raise ValueError("opportunity cycle result fingerprint mismatch")
        return self


class OpportunityCycleService:
    def __init__(
        self,
        engine: OpportunityEngine,
        provider: OpportunityEvidenceProvider,
        state_store: OpportunityStateStore,
        journal: OpportunityCycleJournal | None = None,
    ) -> None:
        self.engine = engine
        self.provider = provider
        self.state_store = state_store
        self.journal = journal

    async def run_cycle(
        self,
        cycle_timestamp: datetime,
        *,
        existing_epics: tuple[str, ...] = (),
        occupied_correlation_groups: tuple[str, ...] = (),
        recent_entries: tuple[tuple[str, datetime], ...] = (),
        current_position_count: int = 0,
        scheduled_evaluations: tuple[ScheduledOpportunityEvaluation, ...] | None = None,
    ) -> OpportunityCycleResult:
        if cycle_timestamp.tzinfo is None:
            raise ValueError("cycle timestamp must be timezone-aware")
        now = cycle_timestamp.astimezone(UTC)
        cycle_fields = {
            "cycle_timestamp": now,
            "universe": self.engine.universe.configuration_fingerprint,
            "configuration": self.engine.configuration.configuration_fingerprint,
        }
        cycle_id = fingerprint(cycle_fields)
        descriptor = self.state_store.acquire_lock()
        try:
            state = self.state_store.load()
            if cycle_id in state.completed_cycle_ids:
                raise OpportunityStateError("duplicate opportunity cycle is prohibited")
            candidates: list[OpportunityCandidate] = []
            evaluations: list[OpportunityEvaluationRecord] = []
            evaluation_keys: list[str] = []
            previous_bars = tuple(
                (instrument, ContextTimeframe(timeframe), timestamp)
                for instrument, timeframe, timestamp in state.last_completed_bars
            )
            scheduled = scheduled_evaluations or plan_completed_bars(
                self.engine.universe,
                now,
                last_completed=previous_bars,
                maximum_catch_up_bars=1,
            )
            scheduled = tuple(sorted(scheduled, key=lambda item: item.evaluation_id))
            skipped: tuple[ScheduledOpportunityEvaluation, ...] = ()
            maximum = self.engine.configuration.maximum_evaluations_per_cycle
            if len(scheduled) > maximum:
                cursor = state.fair_schedule_cursor % len(scheduled)
                rotated = scheduled[cursor:] + scheduled[:cursor]
                scheduled, skipped = rotated[:maximum], rotated[maximum:]
            markets_scanned_set: set[str] = set()
            strategy_evaluations = 0
            for scheduled_item in scheduled:
                market = self.engine.universe.require_enabled(scheduled_item.instrument_id)
                markets_scanned_set.add(market.instrument_id)
                strategy_count = int(getattr(self.provider, "strategy_evaluations_per_request", 1))
                base_key = fingerprint(
                    {
                        "instrument": market.instrument_id,
                        "timeframe": scheduled_item.timeframe,
                        "completed_bar_timestamp": scheduled_item.completed_bar_timestamp,
                    }
                )
                if base_key in state.completed_evaluation_keys:
                    continue
                if getattr(self.provider, "supports_scheduled_cutoff", False):
                    evidence_items = await self.provider.evaluate(
                        market,
                        scheduled_item.timeframe,
                        now,
                        completed_bar_timestamp=scheduled_item.completed_bar_timestamp,
                    )
                else:
                    evidence_items = await self.provider.evaluate(
                        market,
                        scheduled_item.timeframe,
                        now,
                    )
                strategy_evaluations += strategy_count
                created_ids: list[str] = []
                evaluation_keys.append(base_key)
                for evidence in evidence_items:
                    evidence = evidence.model_copy(update={"cycle_id": cycle_id})
                    candidate = self.engine.evaluate(evidence)
                    candidates.append(candidate)
                    created_ids.append(candidate.candidate_id)
                executable_count = 1
                research_count = max(0, strategy_count - executable_count)
                fields = {
                    "instrument_id": market.instrument_id,
                    "epic": market.epic,
                    "timeframe": scheduled_item.timeframe,
                    "completed_bar_timestamp": scheduled_item.completed_bar_timestamp,
                    "strategy_evaluations": strategy_count,
                    "research_only_evaluations": research_count,
                    "backtest_validated_evaluations": executable_count,
                    "demo_executable_evaluations": executable_count,
                    "ineligible_regime_evaluations": executable_count if not created_ids else 0,
                    "candidate_producing_evaluations": len(created_ids),
                    "candidate_ids": tuple(created_ids),
                    "rejection_codes": (
                        () if created_ids else (OpportunityRejectionCode.MISSING_EVIDENCE,)
                    ),
                }
                evaluations.append(
                    OpportunityEvaluationRecord.model_validate(
                        {**fields, "evaluation_id": fingerprint(fields)}
                    )
                )
            filtered = suppress_candidates(
                tuple(candidates),
                existing_epics=existing_epics,
                occupied_correlation_groups=occupied_correlation_groups,
                recent_entries=recent_entries,
                cooldown_seconds=self.engine.configuration.recent_reentry_cooldown_seconds,
                maximum_correlated_positions=self.engine.configuration.maximum_correlated_positions,
                current_position_count=current_position_count,
                maximum_existing_positions=self.engine.configuration.maximum_existing_positions,
            )
            retained = filtered[: self.engine.configuration.maximum_candidates_retained_per_cycle]
            ranking = rank_candidates(cycle_id, now, retained, self.engine.configuration)
            counters = ActivityCounters(
                markets_scanned=len(markets_scanned_set),
                instrument_timeframes_evaluated=len(evaluations),
                strategy_evaluations=strategy_evaluations,
                eligible_strategy_evaluations=sum(
                    item.demo_executable_evaluations for item in evaluations
                ),
                research_only_strategy_evaluations=sum(
                    item.research_only_evaluations for item in evaluations
                ),
                backtest_validated_evaluations=sum(
                    item.backtest_validated_evaluations for item in evaluations
                ),
                demo_executable_evaluations=sum(
                    item.demo_executable_evaluations for item in evaluations
                ),
                ineligible_regime_evaluations=sum(
                    item.ineligible_regime_evaluations for item in evaluations
                ),
                candidate_producing_evaluations=sum(
                    item.candidate_producing_evaluations for item in evaluations
                ),
                candidates_created=len(retained),
                positive_expected_value_candidates=sum(
                    1 for item in retained if item.net_expected_value > 0
                ),
                candidates_rejected_by_correlation=sum(
                    1 for item in retained if item.status.value == "SUPPRESSED"
                ),
            )
            diagnostic = diagnose_inactivity(now, "CYCLE", counters)
            fields = {
                "cycle_id": cycle_id,
                "cycle_timestamp": now,
                "universe_fingerprint": self.engine.universe.configuration_fingerprint,
                "configuration_fingerprint": self.engine.configuration.configuration_fingerprint,
                "evaluation_keys": tuple(evaluation_keys),
                "evaluations": tuple(evaluations),
                "skipped_evaluation_ids": tuple(item.evaluation_id for item in skipped),
                "cycle_complete": not skipped,
                "candidates": retained,
                "ranking": ranking,
                "diagnostic": diagnostic,
            }
            result = OpportunityCycleResult.model_validate(
                {**fields, "result_fingerprint": fingerprint(fields)}
            )
            if self.journal is not None:
                self.journal.append_cycle(result)
            completed_bars = {
                (instrument, timeframe): timestamp
                for instrument, timeframe, timestamp in state.last_completed_bars
            }
            for item in scheduled:
                completed_bars[(item.instrument_id, item.timeframe.value)] = (
                    item.completed_bar_timestamp
                )
            self.state_store.save(
                update_state(
                    state,
                    completed_cycle_ids=tuple((*state.completed_cycle_ids, cycle_id))[-10000:],
                    completed_evaluation_keys=tuple(
                        (*state.completed_evaluation_keys, *evaluation_keys)
                    )[-50000:],
                    candidate_fingerprints=tuple(
                        (
                            *state.candidate_fingerprints,
                            *(item.candidate_fingerprint for item in retained),
                        )
                    )[-50000:],
                    last_cycle_timestamp=now,
                    last_completed_bars=tuple(
                        (instrument, timeframe, timestamp)
                        for (instrument, timeframe), timestamp in sorted(completed_bars.items())
                    ),
                    fair_schedule_cursor=(state.fair_schedule_cursor + len(scheduled)),
                    missed_evaluation_count=(state.missed_evaluation_count + len(skipped)),
                    configuration_fingerprint=self.engine.configuration.configuration_fingerprint,
                )
            )
            return result
        except Exception as error:
            if self.journal is not None:
                self.journal.append_failure(cycle_id, now, type(error).__name__)
            raise
        finally:
            self.state_store.release_lock(descriptor)
