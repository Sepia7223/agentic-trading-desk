import json
from decimal import Decimal
from pathlib import Path

from opportunity_helpers import NOW
from trading_desk.opportunity.campaign import DemoCampaignStateStore, campaign_snapshot
from trading_desk.opportunity.config import DemoCampaignConfiguration
from trading_desk.opportunity.fingerprints import fingerprint


def test_campaign_math_and_stretch_target_are_reporting_only() -> None:
    snapshot = campaign_snapshot(
        campaign_id="campaign",
        campaign_name="Demo",
        started_at=NOW,
        observed_at=NOW,
        current_balance=Decimal("20200"),
        current_equity=Decimal("20400"),
        maximum_equity=Decimal("20500"),
        daily_pnl=Decimal("200"),
        weekly_drawdown_percent=Decimal("0.5"),
        consecutive_losses=0,
        trade_pnls=(Decimal("100"), Decimal("-50")),
    )
    assert snapshot.starting_balance == Decimal("20000")
    assert snapshot.return_percent == Decimal("2")
    assert snapshot.expectancy == Decimal("25")
    assert snapshot.account_currency == "UNKNOWN"
    assert not snapshot.entry_halted


def test_campaign_currency_is_persisted_and_legacy_state_migrates(tmp_path: Path) -> None:
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
        account_currency="USD",
    )
    store = DemoCampaignStateStore(tmp_path / "campaign.json")
    store.save(snapshot)
    assert store.load().account_currency == "USD"

    legacy = json.loads(snapshot.model_dump_json())
    legacy.pop("account_currency")
    legacy.pop("snapshot_fingerprint")
    legacy["snapshot_fingerprint"] = fingerprint(legacy)
    store.path.write_text(json.dumps(legacy), encoding="utf-8")
    assert store.load().account_currency == "UNKNOWN"


def test_campaign_safety_breach_halts_entries() -> None:
    snapshot = campaign_snapshot(
        campaign_id="campaign",
        campaign_name="Demo",
        started_at=NOW,
        observed_at=NOW,
        current_balance=Decimal("19800"),
        current_equity=Decimal("19800"),
        maximum_equity=Decimal("20000"),
        daily_pnl=Decimal("-200"),
        weekly_drawdown_percent=Decimal("1"),
        consecutive_losses=0,
        configuration=DemoCampaignConfiguration(enabled=True),
    )
    assert snapshot.entry_halted
    assert "MAXIMUM_DAILY_LOSS" in snapshot.halt_reasons
