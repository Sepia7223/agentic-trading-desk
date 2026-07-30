"""Append-only journal mapping for strategy governance evidence."""

from __future__ import annotations

from datetime import UTC, datetime

from trading_desk.journal.models import JournalRecord, JournalRecordType
from trading_desk.journal.writer import DurableJournalWriter
from trading_desk.strategy.circuit_breakers import BreakerState, StrategyCircuitBreaker
from trading_desk.strategy.invalidation import StrategyInvalidationResult
from trading_desk.strategy.validation_state import PromotionDecision, PromotionDecisionType


class StrategyGovernanceJournal:
    def __init__(self, writer: DurableJournalWriter) -> None:
        self.writer = writer

    def append_promotion_decision(self, decision: PromotionDecision) -> JournalRecord:
        record_type = {
            PromotionDecisionType.DISABLE: JournalRecordType.STRATEGY_DISABLED,
            PromotionDecisionType.REMAIN_RESEARCH_ONLY: (
                JournalRecordType.STRATEGY_PROMOTION_DECISION_CREATED
            ),
            PromotionDecisionType.PROMOTE_TO_BACKTEST_VALIDATED: (
                JournalRecordType.STRATEGY_PROMOTED
            ),
            PromotionDecisionType.PROMOTE_TO_DEMO_EXPLORATION: (
                JournalRecordType.STRATEGY_PROMOTED
            ),
        }[decision.decision]
        return self.writer.append_source(
            record_type=record_type,
            source_record_id=decision.promotion_id,
            source=decision,
            created_at=decision.created_at,
            strategy_variant=f"{decision.strategy_id}:{decision.strategy_version}",
            environment="LOCAL",
        )

    def append_circuit_breaker(self, state: StrategyCircuitBreaker) -> JournalRecord:
        record_type = (
            JournalRecordType.STRATEGY_CIRCUIT_BREAKER_TRIGGERED
            if state.state is BreakerState.TRIGGERED
            else JournalRecordType.STRATEGY_CIRCUIT_BREAKER_CLEARED
        )
        created_at = state.triggered_at
        if created_at is None:
            created_at = datetime.combine(state.trading_day, datetime.min.time(), tzinfo=UTC)
        return self.writer.append_source(
            record_type=record_type,
            source_record_id=state.state_fingerprint,
            source=state,
            created_at=created_at,
            strategy_variant=state.strategy_id,
            environment="DEMO",
        )

    def append_invalidation(
        self,
        *,
        source_record_id: str,
        strategy_id: str,
        evaluated_at: datetime,
        result: StrategyInvalidationResult,
    ) -> JournalRecord:
        return self.writer.append_source(
            record_type=JournalRecordType.STRATEGY_INVALIDATION_EVALUATED,
            source_record_id=source_record_id,
            source=result,
            created_at=evaluated_at,
            strategy_variant=strategy_id,
            environment="DEMO",
        )
