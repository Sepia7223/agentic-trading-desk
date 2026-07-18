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
    OpportunityRanking,
)
from trading_desk.opportunity.ranking import rank_candidates
from trading_desk.opportunity.state import OpportunityStateStore, update_state


class OpportunityEvidenceProvider(Protocol):
    async def evaluate(
        self,
        market: MarketDefinition,
        timeframe: ContextTimeframe,
        cycle_timestamp: datetime,
    ) -> tuple[CandidateEvidence, ...]: ...


class OpportunityCycleResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    cycle_id: str = Field(min_length=64, max_length=64)
    cycle_timestamp: datetime
    universe_fingerprint: str
    configuration_fingerprint: str
    evaluation_keys: tuple[str, ...]
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
    ) -> None:
        self.engine = engine
        self.provider = provider
        self.state_store = state_store

    async def run_cycle(
        self,
        cycle_timestamp: datetime,
        *,
        existing_epics: tuple[str, ...] = (),
        occupied_correlation_groups: tuple[str, ...] = (),
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
            evaluation_keys: list[str] = []
            markets_scanned = 0
            strategy_evaluations = 0
            limit_reached = False
            for market in self.engine.universe.markets:
                if not market.enabled or limit_reached:
                    continue
                markets_scanned += 1
                for timeframe in market.supported_timeframes:
                    evidence_items = await self.provider.evaluate(market, timeframe, now)
                    strategy_evaluations += len(evidence_items)
                    for evidence in evidence_items:
                        key = fingerprint(
                            {
                                "instrument": market.instrument_id,
                                "timeframe": timeframe,
                                "completed_bar_timestamp": evidence.completed_bar_timestamp,
                                "strategy_fingerprint": evidence.strategy.fingerprint,
                            }
                        )
                        if key in state.completed_evaluation_keys:
                            continue
                        evaluation_keys.append(key)
                        candidates.append(self.engine.evaluate(evidence))
                        if (
                            len(candidates)
                            >= self.engine.configuration.maximum_candidates_per_cycle
                        ):
                            limit_reached = True
                            break
                    if limit_reached:
                        break
            filtered = suppress_candidates(
                tuple(candidates),
                existing_epics=existing_epics,
                occupied_correlation_groups=occupied_correlation_groups,
                cooldown_seconds=self.engine.configuration.recent_reentry_cooldown_seconds,
                maximum_correlated_positions=self.engine.configuration.maximum_correlated_positions,
            )
            ranking = rank_candidates(cycle_id, now, filtered, self.engine.configuration)
            counters = ActivityCounters(
                markets_scanned=markets_scanned,
                instrument_timeframes_evaluated=len(evaluation_keys),
                strategy_evaluations=strategy_evaluations,
                eligible_strategy_evaluations=sum(
                    1 for item in filtered if item.strategy_validation_states
                ),
                candidates_created=len(filtered),
                positive_expected_value_candidates=sum(
                    1 for item in filtered if item.net_expected_value > 0
                ),
                candidates_rejected_by_correlation=sum(
                    1 for item in filtered if item.status.value == "SUPPRESSED"
                ),
            )
            diagnostic = diagnose_inactivity(now, "CYCLE", counters)
            fields = {
                "cycle_id": cycle_id,
                "cycle_timestamp": now,
                "universe_fingerprint": self.engine.universe.configuration_fingerprint,
                "configuration_fingerprint": self.engine.configuration.configuration_fingerprint,
                "evaluation_keys": tuple(evaluation_keys),
                "candidates": filtered,
                "ranking": ranking,
                "diagnostic": diagnostic,
            }
            result = OpportunityCycleResult.model_validate(
                {**fields, "result_fingerprint": fingerprint(fields)}
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
                            *(item.candidate_fingerprint for item in filtered),
                        )
                    )[-50000:],
                    last_cycle_timestamp=now,
                    configuration_fingerprint=self.engine.configuration.configuration_fingerprint,
                )
            )
            return result
        finally:
            self.state_store.release_lock(descriptor)
