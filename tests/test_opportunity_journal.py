from decimal import Decimal
from pathlib import Path

from journal_helpers import configuration
from opportunity_helpers import NOW
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
