"""Fail-closed orchestration for explicitly enabled automated IG Demo cycles."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.execution.config import (
    AutomatedDemoExecutionPolicy,
    ExecutionConfiguration,
    ExecutionMode,
)
from trading_desk.execution.engine import ExecutionEngine
from trading_desk.execution.fingerprints import fingerprint
from trading_desk.execution.idempotency import ExecutionIdempotencyStore
from trading_desk.execution.journal import InMemoryExecutionJournal
from trading_desk.execution.mapping import create_execution_request
from trading_desk.execution.models import (
    ExecutionEventType,
    ExecutionOutcome,
    ExecutionStatus,
    ReconciliationStatus,
)
from trading_desk.ig.models import (
    Account,
    DealingRuleUnit,
    DealingRuleValue,
    HistoricalPricePage,
    InstrumentType,
    MarketDetails,
    OpenPosition,
    PriceResolution,
)
from trading_desk.risk.config import RiskConfiguration
from trading_desk.risk.engine import RiskEngine
from trading_desk.risk.mapping import map_strategy_candidate
from trading_desk.risk.models import (
    AccountRiskState,
    AssetClass,
    ExposureAmount,
    MarketRiskState,
    PositionCount,
    RiskDecisionStatus,
    RiskMarketStatus,
)
from trading_desk.strategy.configuration import StrategyConfiguration
from trading_desk.strategy.data_validation import market_data_from_ig_page
from trading_desk.strategy.models import (
    StrategyAction,
    StrategyBarResolution,
    StrategyContext,
    StrategyMarketData,
)
from trading_desk.strategy.pipeline import RegimeAwareStrategyPipeline


class AutomatedDemoBroker(Protocol):
    async def get_accounts(self) -> tuple[Account, ...]: ...

    async def get_open_positions(self) -> tuple[OpenPosition, ...]: ...

    async def get_market_details(self, epic: str) -> MarketDetails: ...

    async def get_historical_prices(
        self,
        epic: str,
        resolution: PriceResolution = PriceResolution.DAY,
        max_points: int | None = None,
        page_number: int = 1,
    ) -> HistoricalPricePage: ...

    async def submit_market_position(self, request): ...  # type: ignore[no-untyped-def]

    async def get_deal_confirmation(self, deal_reference: str): ...  # type: ignore[no-untyped-def]


class AutomatedCycleStatus(StrEnum):
    NO_SIGNAL = "NO_SIGNAL"
    BLOCKED = "BLOCKED"
    ACCEPTED = "ACCEPTED"
    HALTED = "HALTED"


class AutomatedHaltReason(StrEnum):
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
    DAILY_LOSS_LIMIT_REACHED = "DAILY_LOSS_LIMIT_REACHED"
    DRAWDOWN_LIMIT_REACHED = "DRAWDOWN_LIMIT_REACHED"
    MAX_CONSECUTIVE_LOSSES_REACHED = "MAX_CONSECUTIVE_LOSSES_REACHED"
    MAX_ORDERS_PER_DAY_REACHED = "MAX_ORDERS_PER_DAY_REACHED"
    BROKER_ERROR = "BROKER_ERROR"
    BROKER_CONFIRMATION_UNKNOWN = "BROKER_CONFIRMATION_UNKNOWN"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    RECONCILIATION_MISMATCH = "RECONCILIATION_MISMATCH"
    POSITION_NOT_FOUND = "POSITION_NOT_FOUND"
    INTEGRITY_FAILURE = "INTEGRITY_FAILURE"
    ACCOUNT_STATE_UNKNOWN = "ACCOUNT_STATE_UNKNOWN"
    MARKET_STATE_UNKNOWN = "MARKET_STATE_UNKNOWN"
    CONFIGURATION_MISMATCH = "CONFIGURATION_MISMATCH"


class AutomatedDemoState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    initialized_at: datetime
    trading_day: date
    account_identity_fingerprint: str = Field(min_length=64, max_length=64)
    daily_start_equity: Decimal = Field(gt=0)
    peak_equity: Decimal = Field(gt=0)
    orders_today: int = Field(default=0, ge=0, le=1)
    last_order_at: datetime | None = None
    consecutive_losses: int = Field(default=0, ge=0)
    halted: bool = False
    halt_reason: AutomatedHaltReason | None = None
    unresolved_execution: bool = False
    state_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("initialized_at", "last_order_at")
    @classmethod
    def utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("automated Demo timestamps must be UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_integrity(self) -> Self:
        if self.halted != (self.halt_reason is not None):
            raise ValueError("halt state and reason must agree")
        expected = fingerprint(self.model_dump(mode="python", exclude={"state_fingerprint"}))
        if self.state_fingerprint != expected:
            raise ValueError("automated Demo state fingerprint is invalid")
        return self


class AutomatedDemoCycleResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    cycle_id: str = Field(min_length=64, max_length=64)
    evaluated_at: datetime
    epic: str
    status: AutomatedCycleStatus
    strategy_action: str
    candidate_id: str | None = None
    risk_decision_id: str | None = None
    approved_intent_id: str | None = None
    approved_quantity: Decimal | None = None
    submitted_quantity: Decimal | None = None
    stop_reference: Decimal | None = None
    request_fingerprint: str | None = None
    execution: ExecutionOutcome | None = None
    reason_codes: tuple[str, ...] = ()
    journal_record_ids: tuple[str, ...]
    state: AutomatedDemoState
    cycle_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("evaluated_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("cycle timestamp must be UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_integrity(self) -> Self:
        expected = fingerprint(
            self.model_dump(mode="python", exclude={"cycle_id", "cycle_fingerprint"})
        )
        if self.cycle_id != expected or self.cycle_fingerprint != expected:
            raise ValueError("automated cycle fingerprint is invalid")
        return self


class AutomatedDemoRunner:
    def __init__(
        self,
        broker: AutomatedDemoBroker,
        *,
        execution_configuration: ExecutionConfiguration,
        policy: AutomatedDemoExecutionPolicy,
        state: AutomatedDemoState,
        idempotency: ExecutionIdempotencyStore | None = None,
        journal: InMemoryExecutionJournal | None = None,
    ) -> None:
        if (
            not execution_configuration.execution_enabled
            or not execution_configuration.automatic_execution_enabled
            or execution_configuration.execution_mode is not ExecutionMode.AUTOMATED_DEMO
            or execution_configuration.require_operator_confirmation
            or not policy.enabled
        ):
            raise ValueError("automated Demo configuration is not explicitly enabled")
        if execution_configuration.demo_gateway != policy.demo_gateway:
            raise ValueError("automated Demo gateway configuration mismatch")
        self.broker = broker
        self.execution_configuration = execution_configuration
        self.policy = policy
        self.state = state
        self.idempotency = idempotency or ExecutionIdempotencyStore()
        self.journal = journal or InMemoryExecutionJournal()

    async def run_cycle(self, epic: str, evaluated_at: datetime) -> AutomatedDemoCycleResult:
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() != UTC.utcoffset(evaluated_at):
            raise ValueError("cycle timestamp must be UTC")
        evaluated_at = evaluated_at.astimezone(UTC)
        if self.state.halted or self.state.unresolved_execution:
            return self._result(
                evaluated_at,
                epic,
                AutomatedCycleStatus.HALTED,
                "NOT_EVALUATED",
                (self.state.halt_reason or AutomatedHaltReason.INTEGRITY_FAILURE).value,
            )
        if (
            self.state.trading_day == evaluated_at.date()
            and self.state.orders_today >= self.policy.maximum_orders_per_day
        ):
            self.state = halt_state(self.state, AutomatedHaltReason.MAX_ORDERS_PER_DAY_REACHED)
            return self._result(
                evaluated_at,
                epic,
                AutomatedCycleStatus.HALTED,
                "NOT_EVALUATED",
                AutomatedHaltReason.MAX_ORDERS_PER_DAY_REACHED.value,
            )
        if (
            self.state.last_order_at is not None
            and (evaluated_at - self.state.last_order_at).total_seconds()
            < self.policy.minimum_seconds_between_orders
        ):
            return self._result(
                evaluated_at,
                epic,
                AutomatedCycleStatus.BLOCKED,
                "NOT_EVALUATED",
                "ORDER_COOLDOWN_ACTIVE",
            )

        accounts = await self.broker.get_accounts()
        positions = await self.broker.get_open_positions()
        details = await self.broker.get_market_details(epic)
        page = await self.broker.get_historical_prices(
            epic,
            resolution=PriceResolution.DAY,
            max_points=max(500, StrategyConfiguration().minimum_bars_required),
            page_number=1,
        )
        account = _preferred_account(accounts)
        if fingerprint(account.account_id) != self.state.account_identity_fingerprint:
            self.state = halt_state(self.state, AutomatedHaltReason.ACCOUNT_STATE_UNKNOWN)
            return self._result(
                evaluated_at,
                epic,
                AutomatedCycleStatus.HALTED,
                "NOT_EVALUATED",
                AutomatedHaltReason.ACCOUNT_STATE_UNKNOWN.value,
            )
        if self.state.trading_day != evaluated_at.date():
            self.state = update_state(
                self.state,
                trading_day=evaluated_at.date(),
                daily_start_equity=account.balance.balance,
                peak_equity=max(self.state.peak_equity, account.balance.balance),
                orders_today=0,
            )
        if positions:
            return self._result(
                evaluated_at,
                epic,
                AutomatedCycleStatus.BLOCKED,
                "NO_TRADE",
                "POSITION_ALREADY_EXISTS",
            )

        risk_market = _market_state(details, evaluated_at)
        risk_account = _account_state(account, details, self.state, evaluated_at)
        if not risk_market.state_complete:
            self.state = halt_state(self.state, AutomatedHaltReason.MARKET_STATE_UNKNOWN)
            return self._result(
                evaluated_at,
                epic,
                AutomatedCycleStatus.HALTED,
                "NO_TRADE",
                AutomatedHaltReason.MARKET_STATE_UNKNOWN.value,
            )
        if not risk_account.state_complete or risk_account.current_drawdown_fraction is None:
            self.state = halt_state(self.state, AutomatedHaltReason.ACCOUNT_STATE_UNKNOWN)
            return self._result(
                evaluated_at,
                epic,
                AutomatedCycleStatus.HALTED,
                "NO_TRADE",
                AutomatedHaltReason.ACCOUNT_STATE_UNKNOWN.value,
            )
        account_pnl = (risk_account.realized_daily_pnl or Decimal("0")) + (
            risk_account.unrealized_pnl or Decimal("0")
        )
        daily_loss_fraction = max(Decimal("0"), -account_pnl / account.balance.balance)
        if daily_loss_fraction >= self.policy.maximum_daily_loss_fraction:
            self.state = halt_state(self.state, AutomatedHaltReason.DAILY_LOSS_LIMIT_REACHED)
            return self._result(
                evaluated_at,
                epic,
                AutomatedCycleStatus.HALTED,
                "NO_TRADE",
                AutomatedHaltReason.DAILY_LOSS_LIMIT_REACHED.value,
            )
        if risk_account.current_drawdown_fraction >= self.policy.maximum_drawdown_fraction:
            self.state = halt_state(self.state, AutomatedHaltReason.DRAWDOWN_LIMIT_REACHED)
            return self._result(
                evaluated_at,
                epic,
                AutomatedCycleStatus.HALTED,
                "NO_TRADE",
                AutomatedHaltReason.DRAWDOWN_LIMIT_REACHED.value,
            )
        if self.state.consecutive_losses >= self.policy.maximum_consecutive_losses:
            self.state = halt_state(self.state, AutomatedHaltReason.MAX_CONSECUTIVE_LOSSES_REACHED)
            return self._result(
                evaluated_at,
                epic,
                AutomatedCycleStatus.HALTED,
                "NO_TRADE",
                AutomatedHaltReason.MAX_CONSECUTIVE_LOSSES_REACHED.value,
            )

        build = market_data_from_ig_page(
            page,
            epic=details.epic,
            instrument_name=details.instrument_name,
            market_status=details.market_status.value,
            data_retrieval_time=evaluated_at,
            bar_resolution=StrategyBarResolution.DAY,
        )
        if build.data is None:
            return self._result(
                evaluated_at,
                epic,
                AutomatedCycleStatus.BLOCKED,
                "NO_TRADE",
                *(item.code.value for item in build.findings),
            )
        if details.bid is None or details.offer is None or details.offer <= details.bid:
            self.state = halt_state(self.state, AutomatedHaltReason.MARKET_STATE_UNKNOWN)
            return self._result(
                evaluated_at,
                epic,
                AutomatedCycleStatus.HALTED,
                "NO_TRADE",
                AutomatedHaltReason.MARKET_STATE_UNKNOWN.value,
            )
        spread = details.offer - details.bid
        midpoint = (details.offer + details.bid) / Decimal("2")
        spread_bps = Decimal("10000") * spread / midpoint
        context = StrategyContext(
            holding=False,
            macro_score=None,
            current_spread=float(spread),
            current_spread_bps=float(spread_bps),
            market_status=details.market_status.value,
            current_time=evaluated_at,
            account_exposure_summary="verified flat Demo account",
        )
        strategy = RegimeAwareStrategyPipeline().analyze_latest(
            build.data, context, inherited_findings=build.findings
        )
        if strategy.action is not StrategyAction.LONG_CANDIDATE:
            return self._result(
                evaluated_at,
                epic,
                AutomatedCycleStatus.NO_SIGNAL,
                strategy.action.value,
                *strategy.rejection_reasons,
            )

        stop_distance = _protective_stop_distance(details, build.data, self.policy)
        stop_reference = details.offer - stop_distance
        if stop_reference <= 0:
            self.state = halt_state(self.state, AutomatedHaltReason.MARKET_STATE_UNKNOWN)
            return self._result(
                evaluated_at,
                epic,
                AutomatedCycleStatus.HALTED,
                strategy.action.value,
                "INVALID_PROTECTIVE_STOP",
            )
        candidate_id = fingerprint(
            {
                "epic": strategy.epic,
                "signal_timestamp": strategy.signal_timestamp,
                "action": strategy.action,
                "variant": strategy.strategy_variant,
                "strategy_configuration_fingerprint": strategy.configuration_fingerprint,
            }
        )
        signal_id = fingerprint(
            {"candidate_id": candidate_id, "signal_timestamp": strategy.signal_timestamp}
        )
        risk_candidate = map_strategy_candidate(
            strategy,
            candidate_id=candidate_id,
            signal_id=signal_id,
            asset_class=_asset_class(details.instrument_type),
            candidate_expiry=evaluated_at + timedelta(minutes=5),
            entry_reference=details.offer,
            stop_reference=stop_reference,
            target_reference=None,
            bid=details.bid,
            ask=details.offer,
            spread_bps=risk_market.spread_bps,
            volatility_or_atr=_atr(build.data),
            market_status=risk_market.market_status,
            holding_state=False,
        )
        maximum_quantity = self.policy.maximum_quantity or risk_market.minimum_deal_size
        assert maximum_quantity is not None
        risk_configuration = _risk_configuration(
            self.policy, risk_market, maximum_quantity, strategy.configuration_fingerprint
        )
        risk_engine = RiskEngine(risk_configuration)
        decision = risk_engine.evaluate(risk_candidate, risk_account, risk_market, evaluated_at)
        if decision.status is not RiskDecisionStatus.APPROVED or decision.approved_intent is None:
            return self._result(
                evaluated_at,
                epic,
                AutomatedCycleStatus.BLOCKED,
                strategy.action.value,
                *(item.value for item in decision.reason_codes),
                candidate_id=candidate_id,
                risk_decision_id=decision.decision_id,
            )
        assert risk_market.minimum_deal_size is not None
        assert risk_account.account_equity is not None
        requested_quantity = min(
            decision.approved_intent.approved_quantity,
            maximum_quantity,
            risk_market.minimum_deal_size,
        )
        execution_configuration = ExecutionConfiguration.model_validate(
            {
                **self.execution_configuration.model_dump(mode="python"),
                "maximum_order_quantity": maximum_quantity,
                "maximum_order_notional": (
                    risk_account.account_equity * self.policy.maximum_notional_fraction
                ),
                "maximum_orders_per_day": self.policy.maximum_orders_per_day,
                "reject_on_price_drift_bps": self.policy.maximum_adverse_price_drift_bps,
            }
        )
        request = create_execution_request(
            decision,
            risk_candidate,
            requested_quantity=requested_quantity,
            currency=details.currency_code or account.currency,
            evaluation_timestamp=evaluated_at,
            configuration=execution_configuration,
            expiry=details.expiry or "-",
        )
        engine = ExecutionEngine(
            self.broker,
            configuration=execution_configuration,
            risk_engine=risk_engine,
            idempotency=self.idempotency,
            journal=self.journal,
        )
        outcome = await engine.execute(
            request=request,
            decision=decision,
            candidate=risk_candidate,
            account=risk_account,
            market=risk_market,
            positions=positions,
            confirmation=None,
            evaluation_timestamp=evaluated_at,
            orders_today=self.state.orders_today,
            automatic=True,
        )
        submitted = outcome.result.submitted_at is not None
        if submitted:
            self.state = update_state(
                self.state,
                orders_today=self.state.orders_today + 1,
                last_order_at=evaluated_at,
                peak_equity=max(self.state.peak_equity, account.balance.balance),
            )
        halt_reason = _outcome_halt_reason(outcome)
        if halt_reason is not None:
            self.state = halt_state(self.state, halt_reason, unresolved=True)
        status = (
            AutomatedCycleStatus.ACCEPTED
            if outcome.result.status is ExecutionStatus.ACCEPTED
            and outcome.reconciliation is not None
            and outcome.reconciliation.status is ReconciliationStatus.RECONCILED
            else AutomatedCycleStatus.HALTED
            if self.state.halted
            else AutomatedCycleStatus.BLOCKED
        )
        return self._result(
            evaluated_at,
            epic,
            status,
            strategy.action.value,
            *(item.value for item in outcome.result.reason_codes),
            candidate_id=candidate_id,
            risk_decision_id=decision.decision_id,
            approved_intent_id=fingerprint(decision.approved_intent),
            approved_quantity=decision.approved_intent.approved_quantity,
            submitted_quantity=outcome.preflight.validated_quantity,
            stop_reference=stop_reference,
            request_fingerprint=request.request_fingerprint,
            execution=outcome,
        )

    def _result(
        self,
        evaluated_at: datetime,
        epic: str,
        status: AutomatedCycleStatus,
        strategy_action: str,
        *reason_codes: str,
        candidate_id: str | None = None,
        risk_decision_id: str | None = None,
        approved_intent_id: str | None = None,
        approved_quantity: Decimal | None = None,
        submitted_quantity: Decimal | None = None,
        stop_reference: Decimal | None = None,
        request_fingerprint: str | None = None,
        execution: ExecutionOutcome | None = None,
    ) -> AutomatedDemoCycleResult:
        if self.state.halted:
            self.journal.append(
                ExecutionEventType.AUTOMATED_HALTED,
                evaluated_at,
                {
                    "epic": epic,
                    "reason": self.state.halt_reason,
                    "state_fingerprint": self.state.state_fingerprint,
                },
                candidate_id=candidate_id,
                risk_decision_id=risk_decision_id,
                approved_intent_id=approved_intent_id,
            )
        self.journal.append(
            ExecutionEventType.AUTOMATED_CYCLE_EVALUATED,
            evaluated_at,
            {
                "epic": epic,
                "status": status,
                "strategy_action": strategy_action,
                "reason_codes": reason_codes,
                "state_fingerprint": self.state.state_fingerprint,
            },
            candidate_id=candidate_id,
            risk_decision_id=risk_decision_id,
            approved_intent_id=approved_intent_id,
        )
        fields = {
            "evaluated_at": evaluated_at,
            "epic": epic,
            "status": status,
            "strategy_action": strategy_action,
            "candidate_id": candidate_id,
            "risk_decision_id": risk_decision_id,
            "approved_intent_id": approved_intent_id,
            "approved_quantity": approved_quantity,
            "submitted_quantity": submitted_quantity,
            "stop_reference": stop_reference,
            "request_fingerprint": request_fingerprint,
            "execution": execution,
            "reason_codes": tuple(dict.fromkeys(reason_codes)),
            "journal_record_ids": tuple(record.record_id for record in self.journal.records()),
            "state": self.state,
        }
        cycle_fingerprint = fingerprint(fields)
        return AutomatedDemoCycleResult.model_validate(
            {**fields, "cycle_id": cycle_fingerprint, "cycle_fingerprint": cycle_fingerprint}
        )


def create_initial_state(account: Account, initialized_at: datetime) -> AutomatedDemoState:
    fields = {
        "initialized_at": initialized_at,
        "trading_day": initialized_at.date(),
        "account_identity_fingerprint": fingerprint(account.account_id),
        "daily_start_equity": account.balance.balance,
        "peak_equity": account.balance.balance,
        "orders_today": 0,
        "last_order_at": None,
        "consecutive_losses": 0,
        "halted": False,
        "halt_reason": None,
        "unresolved_execution": False,
    }
    return AutomatedDemoState.model_validate({**fields, "state_fingerprint": fingerprint(fields)})


def update_state(state: AutomatedDemoState, **updates: object) -> AutomatedDemoState:
    fields = state.model_dump(mode="python", exclude={"state_fingerprint"})
    fields.update(updates)
    return AutomatedDemoState.model_validate({**fields, "state_fingerprint": fingerprint(fields)})


def halt_state(
    state: AutomatedDemoState,
    reason: AutomatedHaltReason,
    *,
    unresolved: bool = False,
) -> AutomatedDemoState:
    return update_state(
        state,
        halted=True,
        halt_reason=reason,
        unresolved_execution=unresolved,
    )


def _preferred_account(accounts: tuple[Account, ...]) -> Account:
    preferred = tuple(account for account in accounts if account.preferred)
    if len(preferred) != 1:
        raise ValueError("exactly one preferred Demo account is required")
    return preferred[0]


def _market_state(details: MarketDetails, timestamp: datetime) -> MarketRiskState:
    minimum_stop = _dealing_distance(
        details.min_normal_stop_or_limit_distance, details.offer, details.scaling_factor
    )
    maximum_stop = _dealing_distance(
        details.max_stop_or_limit_distance, details.offer, details.scaling_factor
    )
    economic_values = tuple(
        value
        for value in (
            details.contract_size,
            details.lot_size,
            (
                details.value_of_one_pip * details.scaling_factor
                if details.value_of_one_pip is not None and details.scaling_factor is not None
                else None
            ),
        )
        if value is not None
    )
    value_per_price_unit = max(economic_values) if economic_values else None
    status = (
        RiskMarketStatus(details.market_status.value)
        if details.market_status.value in {item.value for item in RiskMarketStatus}
        else RiskMarketStatus.UNKNOWN
    )
    spread_bps = None
    if details.bid is not None and details.offer is not None and details.offer > details.bid:
        spread_bps = (
            Decimal("10000")
            * (details.offer - details.bid)
            / ((details.offer + details.bid) / Decimal("2"))
        )
    minimum_size = details.min_deal_size.value if details.min_deal_size is not None else None
    return MarketRiskState(
        snapshot_id=fingerprint({"details": details, "timestamp": timestamp}),
        instrument=details.instrument_name,
        epic=details.epic,
        timestamp=timestamp,
        market_status=status,
        bid=details.bid,
        ask=details.offer,
        spread_bps=spread_bps,
        minimum_deal_size=minimum_size,
        quantity_increment=minimum_size,
        minimum_stop_distance=minimum_stop,
        maximum_stop_distance=maximum_stop,
        value_per_price_unit=value_per_price_unit,
        state_complete=all(
            value is not None
            for value in (
                details.bid,
                details.offer,
                minimum_size,
                minimum_stop,
                maximum_stop,
                value_per_price_unit,
                details.currency_code,
            )
        ),
    )


def _account_state(
    account: Account,
    details: MarketDetails,
    state: AutomatedDemoState,
    timestamp: datetime,
) -> AccountRiskState:
    equity = account.balance.balance
    daily_change = equity - state.daily_start_equity
    drawdown = max(Decimal("0"), (state.peak_equity - equity) / state.peak_equity)
    asset_class = _asset_class(details.instrument_type)
    return AccountRiskState(
        snapshot_id=fingerprint(
            {"account": account.account_id, "balance": account.balance, "timestamp": timestamp}
        ),
        timestamp=timestamp,
        account_equity=equity,
        available_capital=account.balance.available_funds,
        realized_daily_pnl=min(Decimal("0"), daily_change),
        unrealized_pnl=min(Decimal("0"), account.balance.profit_loss),
        current_drawdown_fraction=drawdown,
        gross_exposure=Decimal("0"),
        open_risk_amount=Decimal("0"),
        open_position_count=0,
        instrument_exposure=(ExposureAmount(key=details.epic, amount=Decimal("0")),),
        asset_class_exposure=(ExposureAmount(key=asset_class.value, amount=Decimal("0")),),
        instrument_position_count=(PositionCount(key=details.epic, count=0),),
        consecutive_losses=state.consecutive_losses,
        kill_switch_active=False,
        state_complete=True,
    )


def _risk_configuration(
    policy: AutomatedDemoExecutionPolicy,
    market: MarketRiskState,
    maximum_quantity: Decimal,
    strategy_fingerprint: str,
) -> RiskConfiguration:
    assert market.minimum_deal_size is not None
    assert market.quantity_increment is not None
    assert market.minimum_stop_distance is not None
    assert market.maximum_stop_distance is not None
    return RiskConfiguration(
        risk_per_trade_fraction=policy.maximum_risk_fraction,
        maximum_daily_realized_loss_fraction=policy.maximum_daily_loss_fraction,
        maximum_daily_total_loss_fraction=policy.maximum_daily_loss_fraction,
        maximum_portfolio_drawdown_fraction=policy.maximum_drawdown_fraction,
        maximum_gross_exposure_fraction=policy.maximum_notional_fraction,
        maximum_instrument_exposure_fraction=policy.maximum_notional_fraction,
        maximum_asset_class_exposure_fraction=policy.maximum_notional_fraction,
        maximum_open_positions=policy.maximum_open_demo_positions,
        maximum_positions_per_instrument=policy.maximum_positions_per_instrument,
        maximum_spread_bps=policy.maximum_spread_bps,
        minimum_stop_distance=market.minimum_stop_distance,
        maximum_stop_distance=market.maximum_stop_distance,
        maximum_consecutive_losses=policy.maximum_consecutive_losses,
        quantity_increment=market.quantity_increment,
        minimum_approved_quantity=market.minimum_deal_size,
        maximum_approved_quantity=maximum_quantity,
        required_strategy_configuration_fingerprint=strategy_fingerprint,
    )


def _protective_stop_distance(
    details: MarketDetails,
    data: StrategyMarketData,
    policy: AutomatedDemoExecutionPolicy,
) -> Decimal:
    minimum = _dealing_distance(
        details.min_normal_stop_or_limit_distance, details.offer, details.scaling_factor
    )
    if minimum is None:
        raise ValueError("minimum protective stop distance is unknown")
    return max(
        minimum * policy.protective_stop_minimum_multiplier,
        _atr(data) * policy.protective_stop_atr_multiplier,
    )


def _atr(data: StrategyMarketData) -> Decimal:
    ranges = [
        Decimal(str(high - low))
        for high, low in zip(data.high_midpoints[-14:], data.low_midpoints[-14:], strict=True)
    ]
    if not ranges:
        raise ValueError("volatility state is unavailable")
    return sum(ranges, Decimal("0")) / Decimal(len(ranges))


def _dealing_distance(
    rule: DealingRuleValue | None,
    reference: Decimal | None,
    scaling_factor: Decimal | None,
) -> Decimal | None:
    if rule is None or reference is None:
        return None
    if rule.unit is DealingRuleUnit.POINTS:
        if scaling_factor is None or scaling_factor <= 0:
            return None
        return rule.value / scaling_factor
    if rule.unit is DealingRuleUnit.PERCENTAGE:
        return reference * rule.value / Decimal("100")
    return None


def _asset_class(instrument_type: InstrumentType) -> AssetClass:
    return {
        InstrumentType.CURRENCIES: AssetClass.FOREX,
        InstrumentType.INDICES: AssetClass.INDEX,
        InstrumentType.SHARES: AssetClass.SHARE,
        InstrumentType.COMMODITIES: AssetClass.COMMODITY,
        InstrumentType.RATES: AssetClass.RATE,
    }.get(instrument_type, AssetClass.OTHER)


def _outcome_halt_reason(outcome: ExecutionOutcome) -> AutomatedHaltReason | None:
    if outcome.result.status is ExecutionStatus.RECONCILIATION_REQUIRED:
        return AutomatedHaltReason.RECONCILIATION_REQUIRED
    if outcome.result.status is ExecutionStatus.REJECTED:
        return AutomatedHaltReason.BROKER_ERROR
    if outcome.reconciliation is None:
        return None
    return {
        ReconciliationStatus.RECONCILIATION_MISMATCH: (AutomatedHaltReason.RECONCILIATION_MISMATCH),
        ReconciliationStatus.POSITION_NOT_FOUND: AutomatedHaltReason.POSITION_NOT_FOUND,
        ReconciliationStatus.RECONCILIATION_PENDING: (AutomatedHaltReason.RECONCILIATION_REQUIRED),
    }.get(outcome.reconciliation.status)
