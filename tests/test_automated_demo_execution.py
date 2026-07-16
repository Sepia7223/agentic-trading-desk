from __future__ import annotations

import asyncio
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.test_risk_integration_security import _strategy_candidate

from trading_desk.execution.automated import (
    AutomatedCycleStatus,
    AutomatedDemoRunner,
    AutomatedHaltReason,
    create_initial_state,
    update_state,
)
from trading_desk.execution.config import (
    AutomatedDemoExecutionPolicy,
    ExecutionConfiguration,
    ExecutionMode,
)
from trading_desk.execution.errors import ExecutionBrokerError
from trading_desk.execution.idempotency import ExecutionIdempotencyStore
from trading_desk.execution.journal import InMemoryExecutionJournal
from trading_desk.execution.models import (
    BrokerConfirmation,
    BrokerConfirmationStatus,
    BrokerOrderRequest,
    BrokerSubmission,
    ExecutionDirection,
)
from trading_desk.execution.state import AutomatedDemoStateStore
from trading_desk.ig.models import (
    Account,
    AccountBalance,
    AccountType,
    APIAllowanceMetadata,
    DealingRuleUnit,
    DealingRuleValue,
    HistoricalPriceBar,
    HistoricalPricePage,
    HistoricalPriceValue,
    InstrumentType,
    MarketDetails,
    MarketStatus,
    OpenPosition,
    PaginationMetadata,
    PositionMarketSnapshot,
)
from trading_desk.strategy.models import StrategyAction
from trading_desk.strategy.pipeline import RegimeAwareStrategyPipeline

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)
EPIC = "CS.D.TEST.CFD.IP"


def _account() -> Account:
    return Account(
        account_id="demo-account-id",
        account_name="Demo",
        account_type=AccountType.CFD,
        preferred=True,
        currency="USD",
        balance=AccountBalance(
            balance=Decimal("100000"),
            deposit=Decimal("0"),
            profit_loss=Decimal("0"),
            available_funds=Decimal("100000"),
        ),
    )


def _details() -> MarketDetails:
    return MarketDetails(
        epic=EPIC,
        instrument_name="Test market",
        instrument_type=InstrumentType.CURRENCIES,
        expiry="-",
        market_status=MarketStatus.TRADEABLE,
        bid=Decimal("99.91"),
        offer=Decimal("100"),
        currency_code="USD",
        lot_size=Decimal("1"),
        contract_size=Decimal("1"),
        value_of_one_pip=Decimal("0.01"),
        scaling_factor=Decimal("100"),
        update_time=time(12, 0),
        min_deal_size=DealingRuleValue(value=Decimal("0.5"), unit=DealingRuleUnit.POINTS),
        min_normal_stop_or_limit_distance=DealingRuleValue(
            value=Decimal("1"), unit=DealingRuleUnit.POINTS
        ),
        max_stop_or_limit_distance=DealingRuleValue(
            value=Decimal("90"), unit=DealingRuleUnit.PERCENTAGE
        ),
    )


def _page() -> HistoricalPricePage:
    bars = []
    for index in range(240):
        close = Decimal("90") + Decimal(index) / Decimal("100")
        value = lambda price: HistoricalPriceValue(  # noqa: E731
            bid=price - Decimal("0.01"), ask=price + Decimal("0.01")
        )
        bars.append(
            HistoricalPriceBar(
                timestamp=NOW - timedelta(days=239 - index),
                open=value(close),
                high=value(close + Decimal("0.2")),
                low=value(close - Decimal("0.2")),
                close=value(close),
                valid_for_strategy=True,
            )
        )
    return HistoricalPricePage(
        bars=tuple(bars),
        pagination=PaginationMetadata(page_number=1, page_size=240, total_pages=1),
        allowance=APIAllowanceMetadata(
            allowance_expiry_seconds=60,
            remaining_allowance=99,
            total_allowance=100,
        ),
    )


class AutomatedBroker:
    def __init__(
        self,
        *,
        ambiguous: bool = False,
        rejected: bool = False,
        existing: bool = False,
        account: Account | None = None,
    ) -> None:
        self.ambiguous = ambiguous
        self.rejected = rejected
        self.existing = existing
        self.account = account or _account()
        self.submission_calls = 0
        self.order: BrokerOrderRequest | None = None
        self.position_calls = 0

    async def get_accounts(self):  # type: ignore[no-untyped-def]
        return (self.account,)

    async def get_open_positions(self):  # type: ignore[no-untyped-def]
        self.position_calls += 1
        if self.existing or (self.order is not None and self.position_calls > 1):
            assert self.order is not None or self.existing
            order = self.order
            return (
                OpenPosition(
                    deal_id="deal-id-1",
                    deal_reference="deal-ref-1",
                    direction="BUY",
                    size=order.size if order is not None else Decimal("0.5"),
                    opening_level=Decimal("100"),
                    stop_level=order.stop_level if order is not None else Decimal("99"),
                    limit_level=order.limit_level if order is not None else None,
                    controlled_risk=False,
                    currency="USD",
                    created_at=NOW,
                    market=PositionMarketSnapshot(
                        epic=EPIC,
                        instrument_name="Test market",
                        bid=Decimal("99.9"),
                        offer=Decimal("100"),
                        market_status="TRADEABLE",
                        update_time_utc=NOW,
                    ),
                ),
            )
        return ()

    async def get_market_details(self, epic: str):  # type: ignore[no-untyped-def]
        assert epic == EPIC
        return _details()

    async def get_historical_prices(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return _page()

    async def submit_market_position(self, request: BrokerOrderRequest) -> BrokerSubmission:
        self.submission_calls += 1
        self.order = request
        if self.ambiguous:
            raise ExecutionBrokerError(
                "safe transport failure", operation="OPEN_POSITION", ambiguous=True
            )
        if self.rejected:
            raise ExecutionBrokerError(
                "safe broker rejection", operation="OPEN_POSITION", ambiguous=False
            )
        return BrokerSubmission(deal_reference="deal-ref-1", safe_request_id="safe-1")

    async def get_deal_confirmation(self, deal_reference: str) -> BrokerConfirmation:
        assert self.order is not None
        return BrokerConfirmation(
            deal_reference=deal_reference,
            deal_id="deal-id-1",
            status=BrokerConfirmationStatus.ACCEPTED,
            broker_status="OPEN",
            broker_reason="SUCCESS",
            epic=EPIC,
            direction=ExecutionDirection.BUY,
            executed_level=Decimal("100"),
            executed_size=self.order.size,
            stop_level=self.order.stop_level,
            limit_level=self.order.limit_level,
            confirmed_at=NOW,
        )


def _configuration() -> ExecutionConfiguration:
    return ExecutionConfiguration(
        execution_enabled=True,
        automatic_execution_enabled=True,
        execution_mode=ExecutionMode.AUTOMATED_DEMO,
        require_operator_confirmation=False,
    )


def _runner(broker: AutomatedBroker) -> AutomatedDemoRunner:
    return AutomatedDemoRunner(
        broker,
        execution_configuration=_configuration(),
        policy=AutomatedDemoExecutionPolicy(enabled=True),
        state=create_initial_state(_account(), NOW),
    )


def test_automated_policy_is_disabled_immutable_and_fingerprinted() -> None:
    policy = AutomatedDemoExecutionPolicy()
    assert policy.enabled is False
    assert policy.maximum_orders_per_cycle == 1
    assert policy.maximum_orders_per_day == 1
    assert policy.allow_short is False
    assert policy.allow_position_close is False
    assert policy.fingerprint == AutomatedDemoExecutionPolicy().fingerprint
    with pytest.raises(ValidationError):
        policy.enabled = True  # type: ignore[misc]


@pytest.mark.parametrize(
    "values",
    [
        {"automatic_execution_enabled": True},
        {
            "execution_enabled": True,
            "automatic_execution_enabled": True,
            "execution_mode": ExecutionMode.AUTOMATED_DEMO,
        },
        {
            "execution_enabled": True,
            "execution_mode": ExecutionMode.AUTOMATED_DEMO,
            "require_operator_confirmation": False,
        },
    ],
)
def test_automated_configuration_requires_every_explicit_switch(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ExecutionConfiguration.model_validate(values)


def test_manual_mode_keeps_operator_confirmation() -> None:
    config = ExecutionConfiguration(execution_enabled=True)
    assert config.execution_mode is ExecutionMode.MANUAL_CONFIRMED
    assert config.require_operator_confirmation is True
    assert config.automatic_execution_enabled is False


def test_automated_policy_rejects_production_gateway() -> None:
    with pytest.raises(ValidationError):
        AutomatedDemoExecutionPolicy(enabled=True, demo_gateway="https://api.ig.com/gateway/deal")


def test_accepted_cycle_submits_once_confirms_reconciles_and_journals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _strategy_candidate()
    monkeypatch.setattr(
        RegimeAwareStrategyPipeline,
        "analyze_latest",
        lambda *args, **kwargs: candidate,
    )
    broker = AutomatedBroker()
    runner = _runner(broker)
    result = asyncio.run(runner.run_cycle(EPIC, NOW))

    assert result.status is AutomatedCycleStatus.ACCEPTED
    assert broker.submission_calls == 1
    assert result.execution is not None
    assert result.execution.reconciliation is not None
    assert result.execution.reconciliation.status.value == "RECONCILED"
    assert result.submitted_quantity == Decimal("0.5")
    assert result.stop_reference is not None
    assert len(result.journal_record_ids) >= 7
    assert result.state.orders_today == 1
    assert result.state.halted is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("allow_short", True),
        ("allow_limit_orders", True),
        ("allow_working_orders", True),
        ("allow_position_amendment", True),
        ("allow_position_close", True),
        ("allow_account_switch", True),
        ("maximum_orders_per_day", 2),
        ("minimum_seconds_between_orders", 3599),
    ],
)
def test_automated_policy_rejects_expanded_capability(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        AutomatedDemoExecutionPolicy.model_validate({field: value})


def test_ambiguous_submission_is_not_retried_and_latches_halt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        RegimeAwareStrategyPipeline,
        "analyze_latest",
        lambda *args, **kwargs: _strategy_candidate(),
    )
    broker = AutomatedBroker(ambiguous=True)
    runner = _runner(broker)
    result = asyncio.run(runner.run_cycle(EPIC, NOW))

    assert broker.submission_calls == 1
    assert result.status is AutomatedCycleStatus.HALTED
    assert result.state.halted is True
    assert result.state.unresolved_execution is True
    assert result.state.halt_reason is AutomatedHaltReason.RECONCILIATION_REQUIRED
    second = asyncio.run(runner.run_cycle(EPIC, NOW + timedelta(hours=2)))
    assert second.status is AutomatedCycleStatus.HALTED
    assert broker.submission_calls == 1


def test_broker_rejection_latches_halt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        RegimeAwareStrategyPipeline,
        "analyze_latest",
        lambda *args, **kwargs: _strategy_candidate(),
    )
    broker = AutomatedBroker(rejected=True)
    result = asyncio.run(_runner(broker).run_cycle(EPIC, NOW))
    assert broker.submission_calls == 1
    assert result.state.halt_reason is AutomatedHaltReason.BROKER_ERROR
    assert result.status is AutomatedCycleStatus.HALTED


def test_existing_position_blocks_without_mutation() -> None:
    broker = AutomatedBroker(existing=True)
    broker.order = BrokerOrderRequest(
        deal_reference="existing",
        epic=EPIC,
        direction="BUY",
        size=Decimal("0.5"),
        order_type="MARKET",
        currency_code="USD",
        expiry="-",
        force_open=True,
        guaranteed_stop=False,
        stop_level=Decimal("99"),
    )
    result = asyncio.run(_runner(broker).run_cycle(EPIC, NOW))
    assert result.status is AutomatedCycleStatus.BLOCKED
    assert "POSITION_ALREADY_EXISTS" in result.reason_codes
    assert broker.submission_calls == 0


def test_state_store_round_trip_and_detects_tampering(tmp_path: Path) -> None:
    store = AutomatedDemoStateStore(tmp_path / "state.json")
    state = create_initial_state(_account(), NOW)
    snapshot = store.save(
        state,
        ExecutionIdempotencyStore().snapshot(),
        InMemoryExecutionJournal().records(),
    )
    assert store.load() == snapshot
    payload = store.path.read_text(encoding="utf-8").replace(
        '"orders_today": 0', '"orders_today": 1'
    )
    store.path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValidationError):
        store.load()


def test_state_store_rejects_concurrent_runner(tmp_path: Path) -> None:
    store = AutomatedDemoStateStore(tmp_path / "state.json")
    descriptor = store.acquire_lock()
    try:
        with pytest.raises(RuntimeError, match="concurrent run"):
            store.acquire_lock()
    finally:
        store.release_lock(descriptor)


def test_no_signal_is_safe_and_does_not_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    candidate = _strategy_candidate().model_copy(update={"action": StrategyAction.NO_TRADE})
    monkeypatch.setattr(
        RegimeAwareStrategyPipeline,
        "analyze_latest",
        lambda *args, **kwargs: candidate,
    )
    broker = AutomatedBroker()
    result = asyncio.run(_runner(broker).run_cycle(EPIC, NOW))
    assert result.status is AutomatedCycleStatus.NO_SIGNAL
    assert broker.submission_calls == 0


def test_daily_order_limit_and_cooldown_block_before_submission() -> None:
    broker = AutomatedBroker()
    state = update_state(create_initial_state(_account(), NOW), orders_today=1)
    runner = AutomatedDemoRunner(
        broker,
        execution_configuration=_configuration(),
        policy=AutomatedDemoExecutionPolicy(enabled=True),
        state=state,
    )
    result = asyncio.run(runner.run_cycle(EPIC, NOW))
    assert result.state.halt_reason is AutomatedHaltReason.MAX_ORDERS_PER_DAY_REACHED
    assert broker.submission_calls == 0

    cooldown_state = update_state(
        create_initial_state(_account(), NOW), last_order_at=NOW - timedelta(minutes=30)
    )
    cooldown_runner = AutomatedDemoRunner(
        AutomatedBroker(),
        execution_configuration=_configuration(),
        policy=AutomatedDemoExecutionPolicy(enabled=True),
        state=cooldown_state,
    )
    cooldown = asyncio.run(cooldown_runner.run_cycle(EPIC, NOW))
    assert cooldown.status is AutomatedCycleStatus.BLOCKED
    assert "ORDER_COOLDOWN_ACTIVE" in cooldown.reason_codes


def test_daily_loss_drawdown_and_consecutive_losses_halt() -> None:
    losing = _account().model_copy(
        update={
            "balance": _account().balance.model_copy(
                update={"balance": Decimal("99000"), "profit_loss": Decimal("-1000")}
            )
        }
    )
    daily_runner = AutomatedDemoRunner(
        AutomatedBroker(account=losing),
        execution_configuration=_configuration(),
        policy=AutomatedDemoExecutionPolicy(enabled=True),
        state=create_initial_state(_account(), NOW),
    )
    daily = asyncio.run(daily_runner.run_cycle(EPIC, NOW))
    assert daily.state.halt_reason is AutomatedHaltReason.DAILY_LOSS_LIMIT_REACHED

    drawdown_state = update_state(
        create_initial_state(_account(), NOW), peak_equity=Decimal("110000")
    )
    drawdown_runner = AutomatedDemoRunner(
        AutomatedBroker(),
        execution_configuration=_configuration(),
        policy=AutomatedDemoExecutionPolicy(enabled=True),
        state=drawdown_state,
    )
    drawdown = asyncio.run(drawdown_runner.run_cycle(EPIC, NOW))
    assert drawdown.state.halt_reason is AutomatedHaltReason.DRAWDOWN_LIMIT_REACHED

    loss_state = update_state(create_initial_state(_account(), NOW), consecutive_losses=2)
    loss_runner = AutomatedDemoRunner(
        AutomatedBroker(),
        execution_configuration=_configuration(),
        policy=AutomatedDemoExecutionPolicy(enabled=True),
        state=loss_state,
    )
    losses = asyncio.run(loss_runner.run_cycle(EPIC, NOW))
    assert losses.state.halt_reason is AutomatedHaltReason.MAX_CONSECUTIVE_LOSSES_REACHED
