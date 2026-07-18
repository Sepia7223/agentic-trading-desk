from decimal import Decimal
from pathlib import Path

from tests.execution_helpers import approved_decision

from journal_helpers import configuration
from opportunity_helpers import NOW
from trading_desk.execution.fingerprints import fingerprint as execution_fingerprint
from trading_desk.journal.models import JournalRecordType
from trading_desk.journal.sqlite import SQLiteJournalRepository
from trading_desk.journal.writer import DurableJournalWriter
from trading_desk.opportunity.campaign import campaign_snapshot
from trading_desk.opportunity.journal import OpportunityJournal


def test_campaign_record_is_append_only_and_schema_versioned(tmp_path: Path) -> None:
    snapshot = campaign_snapshot(
        campaign_id="campaign",
        campaign_name="Demo",
        started_at=NOW,
        observed_at=NOW,
        current_balance=Decimal("20000"),
        current_equity=Decimal("20000"),
        maximum_equity=Decimal("20000"),
        daily_pnl=Decimal("0"),
        weekly_drawdown_percent=Decimal("0"),
        consecutive_losses=0,
    )
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        record = OpportunityJournal(DurableJournalWriter(repository)).append_campaign(snapshot)
        assert record.record_type is JournalRecordType.DEMO_CAMPAIGN_SNAPSHOT_CREATED
        assert record.schema_version == 4


def test_approved_risk_decision_persists_trade_intent_lineage(tmp_path: Path) -> None:
    decision = approved_decision()
    assert decision.approved_intent is not None
    with SQLiteJournalRepository(configuration(tmp_path / "risk-journal.db")) as repository:
        writer = DurableJournalWriter(repository)
        writer.append_source(
            record_type=JournalRecordType.OPPORTUNITY_CANDIDATE_CREATED,
            source_record_id=decision.candidate_id,
            source={"candidate_id": decision.candidate_id},
            created_at=decision.decision_timestamp,
            environment="DEMO",
        )
        records = OpportunityJournal(writer).append_risk_decision(decision.candidate_id, decision)

        assert tuple(record.record_type for record in records) == (
            JournalRecordType.OPPORTUNITY_RISK_SUBMITTED,
            JournalRecordType.OPPORTUNITY_EXECUTION_APPROVED,
            JournalRecordType.APPROVED_TRADE_INTENT,
        )
        intent = records[-1]
        assert intent.source_record_id == execution_fingerprint(decision.approved_intent)
        assert intent.source_parent_ids == (records[-2].source_record_id,)
