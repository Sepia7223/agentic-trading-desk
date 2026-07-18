from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from trading_desk.context.config import MarketContextConfiguration
from trading_desk.context.models import ContextTimeframe
from trading_desk.context.operational import (
    EconomicCalendarSnapshot,
    HolidayCalendarSnapshot,
    OperationalCandidateContextProvider,
    OperationalContextConfiguration,
)
from trading_desk.ig.models import (
    Account,
    AccountBalance,
    AccountType,
    APIAllowanceMetadata,
    HistoricalPriceBar,
    HistoricalPricePage,
    HistoricalPriceValue,
    InstrumentType,
    MarketDetails,
    MarketStatus,
    PaginationMetadata,
    PriceResolution,
)
from trading_desk.journal.config import JournalConfiguration
from trading_desk.journal.models import JournalRecordType
from trading_desk.journal.sqlite import SQLiteJournalRepository
from trading_desk.journal.writer import DurableJournalWriter
from trading_desk.opportunity.campaign import (
    DemoCampaignService,
    DemoCampaignStateStore,
    campaign_report,
    campaign_snapshot,
)
from trading_desk.opportunity.config import (
    DemoCampaignConfiguration,
    DemoExplorationConfiguration,
    MarketUniverse,
    OpportunityEngineConfiguration,
)
from trading_desk.opportunity.engine import OpportunityEngine
from trading_desk.opportunity.exposure import CurrentExposureSnapshot
from trading_desk.opportunity.fingerprints import fingerprint
from trading_desk.opportunity.journal import OpportunityJournal
from trading_desk.opportunity.ledger import DemoTradeLedger, DemoTradeStatus
from trading_desk.opportunity.operational import OperationalOpportunityEvidenceProvider
from trading_desk.opportunity.orchestrator import OpportunityOrchestrator
from trading_desk.opportunity.preflight import (
    ExplorationRejectionCode,
    exploration_preflight,
)
from trading_desk.opportunity.scheduler import plan_completed_bars
from trading_desk.opportunity.service import OpportunityCycleService
from trading_desk.opportunity.state import OpportunityStateStore
from trading_desk.risk.config import RiskConfiguration
from trading_desk.risk.engine import RiskEngine
from trading_desk.risk.models import (
    AccountRiskState,
    AssetClass,
    ExposureAmount,
    MarketRiskState,
    PositionCount,
    RiskMarketStatus,
)
from trading_desk.strategy.models import (
    ExecutionTimingPolicy,
    MacroState,
    Regime,
    RegimeProbability,
    StrategyAction,
    StrategyVariant,
    TradeCandidate,
)

NOW = datetime(2026, 7, 17, 12, 0, 30, tzinfo=UTC)
EPIC = "CS.D.EURUSD.CFD.IP"


class SnapshotSource:
    def __init__(self, value: object) -> None:
        self.value = value

    def snapshot(self):  # type: ignore[no-untyped-def]
        return self.value


class ReadOnlyMarketSource:
    def __init__(self, page: HistoricalPricePage, details: MarketDetails) -> None:
        self.page = page
        self.details = details
        self.calls: list[tuple[str, object]] = []

    async def get_market_details(self, epic: str) -> MarketDetails:
        self.calls.append(("details", epic))
        return self.details

    async def get_historical_prices(
        self,
        epic: str,
        resolution: PriceResolution | str = PriceResolution.DAY,
        max_points: int | None = None,
        page_number: int = 1,
    ) -> HistoricalPricePage:
        self.calls.append(("prices", (epic, resolution, max_points, page_number)))
        return self.page


class BullishPipeline:
    def analyze_latest(self, data, context, inherited_findings=()):  # type: ignore[no-untyped-def]
        del context, inherited_findings
        return bullish_strategy_candidate(data.epic, data.instrument_name, data.timestamps[-1])


def bullish_strategy_candidate(epic: str, instrument: str, cutoff: datetime) -> TradeCandidate:
    probabilities = (
        RegimeProbability(regime=Regime.BULL_LOW_VOL, probability=0.9),
        RegimeProbability(regime=Regime.TRANSITIONAL, probability=0.05),
        RegimeProbability(regime=Regime.BEAR_HIGH_VOL, probability=0.05),
    )
    return TradeCandidate(
        epic=epic,
        instrument_name=instrument,
        evaluation_timestamp=NOW,
        signal_timestamp=cutoff,
        data_cutoff_timestamp=cutoff,
        earliest_eligible_execution_timestamp=cutoff + timedelta(minutes=5),
        execution_timing_policy=ExecutionTimingPolicy.NEXT_VALID_BAR,
        strategy_variant=StrategyVariant.BASELINE_KALMAN_HMM,
        action=StrategyAction.LONG_CANDIDATE,
        baseline_trend_score=2,
        baseline_momentum_score=2,
        macro_score=None,
        macro_state=MacroState.UNKNOWN,
        total_baseline_score=4,
        current_regime=Regime.BULL_LOW_VOL,
        regime_probabilities=probabilities,
        regime_uncertainty=0.1,
        kalman_level=1.1,
        kalman_slope=0.001,
        kalman_slope_uncertainty=0.001,
        kalman_normalized_slope=0.01,
        kalman_normalized_slope_uncertainty=0.001,
        normalized_price_deviation=0.0,
        current_spread=0.0002,
        current_spread_bps=2.0,
        validation_findings=(),
        mandatory_gates=(),
        deterministic_reasons=("validated bullish test evidence",),
        rejection_reasons=(),
        model_versions=(),
        configuration_fingerprint=fingerprint("strategy-config"),
    )


def page(*, count: int = 240, latest: datetime | None = None) -> HistoricalPricePage:
    end = latest or datetime(2026, 7, 17, 11, 55, tzinfo=UTC)
    bars = []
    for index in range(count):
        timestamp = end - timedelta(minutes=5 * (count - 1 - index))
        midpoint = Decimal("1.0800") + Decimal(index) * Decimal("0.0010")
        bars.append(
            HistoricalPriceBar(
                timestamp=timestamp,
                open=_price(midpoint),
                high=_price(midpoint + Decimal("0.0002")),
                low=_price(midpoint - Decimal("0.0002")),
                close=_price(midpoint + Decimal("0.0001")),
                last_traded_volume=Decimal("100"),
                valid_for_strategy=True,
            )
        )
    return HistoricalPricePage(
        bars=tuple(bars),
        pagination=PaginationMetadata(page_number=1, page_size=count, total_pages=1),
        allowance=APIAllowanceMetadata(
            allowance_expiry_seconds=60,
            remaining_allowance=99,
            total_allowance=100,
        ),
    )


def _price(midpoint: Decimal) -> HistoricalPriceValue:
    return HistoricalPriceValue(
        bid=midpoint - Decimal("0.00005"),
        ask=midpoint + Decimal("0.00005"),
    )


def details() -> MarketDetails:
    return MarketDetails(
        epic=EPIC,
        instrument_name="EUR/USD",
        instrument_type=InstrumentType.CURRENCIES,
        market_status=MarketStatus.TRADEABLE,
        bid=Decimal("1.3190"),
        offer=Decimal("1.3191"),
        currency_code="USD",
    )


def context_provider(*, stale: bool = False) -> OperationalCandidateContextProvider:
    as_of = NOW - timedelta(days=10) if stale else NOW
    events = EconomicCalendarSnapshot(
        source_identifier="TEST_EVENTS",
        as_of=as_of,
        coverage_start=NOW - timedelta(days=1),
        coverage_end=NOW + timedelta(days=1),
        events=(),
    )
    holidays = HolidayCalendarSnapshot(
        source_identifier="TEST_HOLIDAYS",
        as_of=as_of,
        coverage_start=date(2026, 7, 16),
        coverage_end=date(2026, 7, 18),
        entries=(),
    )
    return OperationalCandidateContextProvider(
        SnapshotSource(events),  # type: ignore[arg-type]
        SnapshotSource(holidays),  # type: ignore[arg-type]
        OperationalContextConfiguration(
            market_context=MarketContextConfiguration(compression_percentile=Decimal("0"))
        ),
    )


def operational_provider(*, history: int = 240, stale_calendar: bool = False):  # type: ignore[no-untyped-def]
    source = ReadOnlyMarketSource(page(count=history), details())
    provider = OperationalOpportunityEvidenceProvider(
        source,
        context_provider(stale=stale_calendar),
        maximum_history_points=500,
    )
    provider._pipeline = BullishPipeline()  # type: ignore[assignment]
    return provider, source


def test_operational_provider_uses_real_context_router_and_completed_ig_bars() -> None:
    provider, source = operational_provider()
    market = MarketUniverse().require_enabled("EUR/USD")
    result = asyncio.run(
        provider.evaluate(
            market,
            ContextTimeframe.MINUTE_5,
            NOW,
            completed_bar_timestamp=datetime(2026, 7, 17, 11, 55, tzinfo=UTC),
        )
    )
    assert len(result) == 1
    assert result[0].completed_bar_timestamp == datetime(2026, 7, 17, 11, 55, tzinfo=UTC)
    assert result[0].strategy.demo_executable
    assert len(result[0].evidence_ids) >= 6
    assert source.calls[1][1][1] is PriceResolution.MINUTE_5  # type: ignore[index]


def test_operational_provider_fetches_market_details_once_per_cycle() -> None:
    provider, source = operational_provider()
    market = MarketUniverse().require_enabled("EUR/USD")
    for timeframe in (
        ContextTimeframe.MINUTE_5,
        ContextTimeframe.MINUTE_15,
        ContextTimeframe.HOUR,
    ):
        asyncio.run(provider.evaluate(market, timeframe, NOW))

    assert source.calls.count(("details", EPIC)) == 1
    assert sum(1 for operation, _ in source.calls if operation == "prices") == 3
    assert len(provider.diagnostics) == 3
    assert all(item.bars_retrieved == 240 for item in provider.diagnostics)
    assert all(item.epic == EPIC for item in provider.diagnostics)


@pytest.mark.parametrize("history", (0, 100, 219))
def test_incomplete_history_produces_no_candidate(history: int) -> None:
    provider, _ = operational_provider(history=history)
    market = MarketUniverse().require_enabled("EUR/USD")
    assert asyncio.run(provider.evaluate(market, ContextTimeframe.MINUTE_5, NOW)) == ()


def test_stale_authoritative_calendar_produces_no_candidate() -> None:
    provider, _ = operational_provider(stale_calendar=True)
    market = MarketUniverse().require_enabled("EUR/USD")
    assert asyncio.run(provider.evaluate(market, ContextTimeframe.MINUTE_5, NOW)) == ()


def test_daily_submitted_trade_limit_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "trades.json"
    ledger = DemoTradeLedger(path)
    ledger.append(
        ledger.create_record(
            occurred_at=NOW,
            status=DemoTradeStatus.SUBMITTED,
            strategy="trend-regime-v1",
            instrument="EUR/USD",
            timeframe="MINUTE_5",
            regime="BULL_LOW_VOL",
            session="LONDON",
            candidate_id="candidate-1",
        )
    )
    assert DemoTradeLedger(path).submitted_on(NOW.date()) == 1


def test_campaign_state_and_report_are_durable(tmp_path: Path) -> None:
    config = DemoCampaignConfiguration(enabled=True)
    snapshot = campaign_snapshot(
        campaign_id="campaign-1",
        campaign_name="Demo",
        started_at=NOW,
        observed_at=NOW,
        current_balance=Decimal("21000"),
        current_equity=Decimal("21200"),
        maximum_equity=Decimal("21500"),
        daily_pnl=Decimal("100"),
        weekly_drawdown_percent=Decimal("1"),
        consecutive_losses=0,
        starting_balance=Decimal("20000"),
        starting_equity=Decimal("20000"),
        configuration=config,
    )
    store = DemoCampaignStateStore(tmp_path / "campaign.json")
    store.save(snapshot)
    record = DemoTradeLedger.create_record(
        occurred_at=NOW,
        status=DemoTradeStatus.CLOSED,
        strategy="trend-regime-v1",
        instrument="EUR/USD",
        timeframe="MINUTE_5",
        regime="BULL_LOW_VOL",
        session="LONDON",
        candidate_id="candidate-1",
        realized_pnl=Decimal("100"),
        holding_period_seconds=Decimal("600"),
    )
    report = campaign_report(store.load(), (record,))
    assert report.realized_pnl == Decimal("1000")
    assert report.unrealized_pnl == Decimal("200")
    assert report.wins == 1
    assert report.strategy_breakdown == (("trend-regime-v1", Decimal("100")),)


class AccountSource:
    async def get_accounts(self) -> tuple[Account, ...]:
        return (
            Account(
                account_id="account-id",
                account_name="Demo",
                account_type=AccountType.CFD,
                preferred=True,
                currency="USD",
                balance=AccountBalance(
                    balance=Decimal("31415"),
                    deposit=Decimal("0"),
                    profit_loss=Decimal("25"),
                    available_funds=Decimal("30000"),
                ),
            ),
        )


def test_campaign_start_uses_authoritative_account_and_rejects_second_active_start(
    tmp_path: Path,
) -> None:
    store = DemoCampaignStateStore(tmp_path / "campaign.json")
    service = DemoCampaignService(
        AccountSource(),
        store,
        DemoCampaignConfiguration(enabled=True),
    )
    snapshot = asyncio.run(service.start("campaign", "Demo", NOW))
    assert snapshot.starting_balance == Decimal("31415")
    assert snapshot.starting_equity == Decimal("31440")
    assert store.load() == snapshot
    with pytest.raises(ValueError, match="active"):
        asyncio.run(service.start("campaign-2", "Demo", NOW + timedelta(seconds=1)))


def test_preflight_enforces_daily_limit_and_persisted_campaign_halt(tmp_path: Path) -> None:
    from opportunity_helpers import candidate

    ledger = DemoTradeLedger(tmp_path / "trades.json")
    ledger.append(
        ledger.create_record(
            occurred_at=NOW,
            status=DemoTradeStatus.SUBMITTED,
            strategy="trend-regime-v1",
            instrument="EUR/USD",
            timeframe="MINUTE_5",
            regime="BULL_LOW_VOL",
            session="LONDON",
            candidate_id="old-candidate",
        )
    )
    exposure_fields = {"observed_at": NOW, "positions": (), "recently_closed": ()}
    exposure = CurrentExposureSnapshot(
        **exposure_fields,
        snapshot_fingerprint=fingerprint(exposure_fields),
    )
    campaign = campaign_snapshot(
        campaign_id="campaign",
        campaign_name="Demo",
        started_at=NOW - timedelta(days=1),
        observed_at=NOW,
        current_balance=Decimal("19000"),
        current_equity=Decimal("19000"),
        maximum_equity=Decimal("20000"),
        daily_pnl=Decimal("-1000"),
        weekly_drawdown_percent=Decimal("5"),
        consecutive_losses=10,
        configuration=DemoCampaignConfiguration(enabled=True),
        starting_balance=Decimal("20000"),
    )
    decision = exploration_preflight(
        candidate(),
        observed_at=NOW,
        engine=OpportunityEngineConfiguration(enabled=True),
        exploration=DemoExplorationConfiguration(enabled=True, maximum_trades_per_day=1),
        explicit_authorization=True,
        exposure=exposure,
        ledger=ledger,
        campaign=campaign,
    )
    assert not decision.ready
    assert ExplorationRejectionCode.DAILY_TRADE_LIMIT in decision.rejection_codes
    assert ExplorationRejectionCode.ENTRY_HALTED in decision.rejection_codes


class EmptyExposureProvider:
    async def snapshot(self, observed_at: datetime) -> CurrentExposureSnapshot:
        fields = {"observed_at": observed_at, "positions": (), "recently_closed": ()}
        return CurrentExposureSnapshot.model_validate(
            {**fields, "snapshot_fingerprint": fingerprint(fields)}
        )


class ApprovingRisk:
    async def evaluate(self, candidate, evaluated_at):  # type: ignore[no-untyped-def]
        account = AccountRiskState(
            snapshot_id="account",
            timestamp=evaluated_at,
            account_equity=Decimal("20000"),
            available_capital=Decimal("20000"),
            realized_daily_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            current_drawdown_fraction=Decimal("0"),
            gross_exposure=Decimal("0"),
            open_risk_amount=Decimal("0"),
            open_position_count=0,
            instrument_exposure=(ExposureAmount(key=candidate.epic, amount=Decimal("0")),),
            asset_class_exposure=(ExposureAmount(key=AssetClass.FOREX.value, amount=Decimal("0")),),
            instrument_position_count=(PositionCount(key=candidate.epic, count=0),),
            consecutive_losses=0,
            kill_switch_active=False,
            state_complete=True,
        )
        market = MarketRiskState(
            snapshot_id="market",
            instrument=candidate.instrument,
            epic=candidate.epic,
            timestamp=evaluated_at,
            market_status=RiskMarketStatus.TRADEABLE,
            bid=candidate.bid,
            ask=candidate.ask,
            spread_bps=candidate.spread_bps,
            minimum_deal_size=Decimal("0.5"),
            quantity_increment=Decimal("0.5"),
            minimum_stop_distance=Decimal("0.0001"),
            maximum_stop_distance=Decimal("1"),
            value_per_price_unit=Decimal("1"),
            state_complete=True,
        )
        config = RiskConfiguration(
            quantity_increment=Decimal("0.5"),
            minimum_approved_quantity=Decimal("0.5"),
            maximum_approved_quantity=Decimal("0.5"),
            minimum_stop_distance=Decimal("0.0001"),
            maximum_stop_distance=Decimal("1"),
            maximum_spread_bps=Decimal("10"),
        )
        return RiskEngine(config).evaluate(candidate, account, market, evaluated_at)


class AcceptedExecution:
    calls = 0

    async def submit(self, intent):  # type: ignore[no-untyped-def]
        from types import SimpleNamespace

        del intent
        self.calls += 1
        return SimpleNamespace(
            result=SimpleNamespace(
                submitted_at=NOW,
                status=SimpleNamespace(value="ACCEPTED"),
            )
        )


class Lifecycle:
    calls = 0

    async def monitor(self, observed_at):  # type: ignore[no-untyped-def]
        del observed_at
        self.calls += 1
        return ()


def test_full_operational_path_reaches_risk_execution_lifecycle_and_journal(
    tmp_path: Path,
) -> None:
    provider, _ = operational_provider()
    market = (
        MarketUniverse()
        .require_enabled("EUR/USD")
        .model_copy(update={"supported_timeframes": (ContextTimeframe.MINUTE_5,)})
    )
    universe = MarketUniverse(markets=(market,))
    repository = SQLiteJournalRepository(
        JournalConfiguration(database_path=tmp_path / "journal.sqlite3")
    )
    journal = OpportunityJournal(DurableJournalWriter(repository))
    cycle = OpportunityCycleService(
        OpportunityEngine(
            OpportunityEngineConfiguration(enabled=True),
            DemoExplorationConfiguration(enabled=True),
            universe,
        ),
        provider,
        OpportunityStateStore(tmp_path / "opportunity.json"),
        journal,
    )
    campaign_config = DemoCampaignConfiguration(enabled=True)
    campaign = campaign_snapshot(
        campaign_id="campaign",
        campaign_name="Demo",
        started_at=NOW - timedelta(days=1),
        observed_at=NOW,
        current_balance=Decimal("20000"),
        current_equity=Decimal("20000"),
        maximum_equity=Decimal("20000"),
        daily_pnl=Decimal("0"),
        weekly_drawdown_percent=Decimal("0"),
        consecutive_losses=0,
        configuration=campaign_config,
        starting_balance=Decimal("20000"),
    )
    campaign_store = DemoCampaignStateStore(tmp_path / "campaign.json")
    campaign_store.save(campaign)
    execution = AcceptedExecution()
    lifecycle = Lifecycle()
    orchestrator = OpportunityOrchestrator(
        cycle,
        ApprovingRisk(),
        execution,
        lifecycle,
        exposure=EmptyExposureProvider(),
        ledger=DemoTradeLedger(tmp_path / "ledger.json"),
        campaign=campaign_store,
        journal=journal,
    )
    scheduled = plan_completed_bars(universe, NOW)
    result = asyncio.run(
        orchestrator.run(
            NOW,
            explicit_demo_enable=True,
            scheduled_evaluations=scheduled,
        )
    )
    types = {
        item.record_type
        for item in repository.query(
            __import__("trading_desk.journal.models", fromlist=["JournalQuery"]).JournalQuery(
                limit=500
            )
        ).records
    }
    repository.close()
    assert result.cycle.candidates, result.cycle
    assert result.cycle.ranking.selected_candidate_ids, result.cycle.candidates
    assert result.risk_decision_ids, result.cycle.candidates
    assert result.execution_submission_count == 1
    assert execution.calls == 1
    assert lifecycle.calls == 1
    assert JournalRecordType.OPPORTUNITY_CYCLE_COMPLETED in types
    assert JournalRecordType.OPPORTUNITY_RISK_SUBMITTED in types
    assert JournalRecordType.OPPORTUNITY_EXECUTION_APPROVED in types
