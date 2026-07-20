"""Append-only journal mapping for portfolio allocation evidence.

Every evaluated batch and every candidate decision is journaled so later
Risk, execution, lifecycle, and attribution records can be linked back to
the portfolio decision that proposed them. The journal grants no allocation
authority: it records decisions, it never makes them.
"""

from __future__ import annotations

from trading_desk.allocation.models import PortfolioDecision
from trading_desk.allocation.state import PersistedBatch
from trading_desk.journal.models import JournalRecord, JournalRecordType
from trading_desk.journal.writer import DurableJournalWriter


class PortfolioAllocationJournal:
    def __init__(self, writer: DurableJournalWriter) -> None:
        self.writer = writer

    def append_batch(self, batch: PersistedBatch) -> JournalRecord:
        """Record one evaluated batch; decisions are appended individually."""

        decided_at = min(item.decided_at for item in batch.decisions)
        return self.writer.append_source(
            record_type=JournalRecordType.PORTFOLIO_BATCH_EVALUATED,
            source_record_id=batch.batch_id,
            source=batch,
            created_at=decided_at,
            strategy_variant="portfolio",
            environment="LOCAL",
        )

    def append_decision(self, decision: PortfolioDecision, *, strategy_id: str) -> JournalRecord:
        """Record one candidate decision linked to its evaluated batch."""

        return self.writer.append_source(
            record_type=JournalRecordType.PORTFOLIO_DECISION_CREATED,
            source_record_id=decision.decision_id,
            source=decision,
            created_at=decision.decided_at,
            strategy_variant=strategy_id,
            environment="LOCAL",
            source_parent_ids=(decision.batch_id,),
        )
