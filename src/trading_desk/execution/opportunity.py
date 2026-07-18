"""Controlled execution composition for approved Opportunity candidates."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from trading_desk.execution.automated import (
    _account_state,
    _market_state,
    _risk_configuration,
    create_initial_state,
)
from trading_desk.execution.config import (
    AutomatedDemoExecutionPolicy,
    ExecutionConfiguration,
    ExecutionMode,
)
from trading_desk.execution.engine import ExecutionEngine
from trading_desk.execution.mapping import create_execution_request
from trading_desk.execution.models import ExecutionOutcome
from trading_desk.ig.execution import IGDemoExecutionAdapter
from trading_desk.ig.models import OpenPosition
from trading_desk.opportunity.config import DemoExplorationConfiguration
from trading_desk.opportunity.ledger import DemoTradeLedger, DemoTradeStatus
from trading_desk.risk.engine import RiskEngine
from trading_desk.risk.models import (
    AccountRiskState,
    ApprovedTradeIntent,
    ExposureAmount,
    MarketRiskState,
    PositionCount,
    RiskDecision,
    TradeCandidate,
)


class ControlledOpportunityAuthority:
    """Risk evaluates first; execution consumes only that approved intent once."""

    def __init__(
        self,
        broker: IGDemoExecutionAdapter,
        ledger: DemoTradeLedger,
        exploration_configuration: DemoExplorationConfiguration,
        *,
        policy: AutomatedDemoExecutionPolicy | None = None,
    ) -> None:
        self.broker = broker
        self.ledger = ledger
        self.exploration_configuration = exploration_configuration
        self.policy = policy or AutomatedDemoExecutionPolicy(enabled=True)
        self._decision: RiskDecision | None = None
        self._candidate: TradeCandidate | None = None
        self._account: AccountRiskState | None = None
        self._market: MarketRiskState | None = None
        self._positions: tuple[OpenPosition, ...] = ()
        self._currency: str | None = None
        self._risk_engine: RiskEngine | None = None

    @property
    def maximum_orders_per_day(self) -> int:
        """Return the immutable daily limit shared with Opportunity preflight."""

        return self.exploration_configuration.maximum_trades_per_day

    async def evaluate(self, candidate: object, evaluated_at: datetime) -> RiskDecision:
        if not isinstance(candidate, TradeCandidate):
            raise ValueError("Risk authority requires a typed candidate")
        accounts = await self.broker.get_accounts()
        preferred = tuple(item for item in accounts if item.preferred)
        if len(preferred) != 1:
            raise ValueError("exactly one authoritative preferred Demo account is required")
        account = preferred[0]
        details = await self.broker.get_market_details(candidate.epic)
        positions = await self.broker.get_open_positions()
        state = create_initial_state(account, evaluated_at)
        market = _market_state(details, evaluated_at)
        account_state = _account_state(account, details, state, evaluated_at)
        notionals: dict[str, Decimal] = {}
        counts: dict[str, int] = {}
        gross = Decimal("0")
        for position in positions:
            notional = position.size * position.opening_level
            notionals[position.market.epic] = (
                notionals.get(position.market.epic, Decimal("0")) + notional
            )
            counts[position.market.epic] = counts.get(position.market.epic, 0) + 1
            gross += notional
        notionals.setdefault(candidate.epic, Decimal("0"))
        counts.setdefault(candidate.epic, 0)
        account_state = account_state.model_copy(
            update={
                "gross_exposure": gross,
                "open_position_count": len(positions),
                "instrument_exposure": tuple(
                    ExposureAmount(key=key, amount=value)
                    for key, value in sorted(notionals.items())
                ),
                "asset_class_exposure": (ExposureAmount(key="FOREX", amount=gross),),
                "instrument_position_count": tuple(
                    PositionCount(key=key, count=value) for key, value in sorted(counts.items())
                ),
            }
        )
        maximum_quantity = self.policy.maximum_quantity or market.minimum_deal_size
        if maximum_quantity is None:
            raise ValueError("authoritative maximum Demo quantity is unavailable")
        risk_configuration = _risk_configuration(
            self.policy,
            market,
            maximum_quantity,
            candidate.strategy_configuration_fingerprint,
        )
        risk_engine = RiskEngine(risk_configuration)
        decision = risk_engine.evaluate(candidate, account_state, market, evaluated_at)
        self._decision = decision
        self._candidate = candidate
        self._account = account_state
        self._market = market
        self._positions = positions
        self._currency = details.currency_code or account.currency
        self._risk_engine = risk_engine
        return decision

    async def submit(self, intent: ApprovedTradeIntent) -> ExecutionOutcome:
        if (
            self._decision is None
            or self._candidate is None
            or self._account is None
            or self._market is None
            or self._currency is None
            or self._risk_engine is None
            or self._decision.approved_intent != intent
        ):
            raise ValueError("controlled execution has no matching Risk approval")
        candidate = self._candidate
        assert candidate is not None
        now = datetime.now(UTC)
        configuration = ExecutionConfiguration(
            execution_enabled=True,
            automatic_execution_enabled=True,
            execution_mode=ExecutionMode.DEMO_EXPLORATION,
            require_operator_confirmation=False,
            maximum_order_quantity=intent.approved_quantity,
            maximum_order_notional=intent.notional_exposure,
            maximum_orders_per_day=self.maximum_orders_per_day,
        )
        request = create_execution_request(
            self._decision,
            candidate,
            requested_quantity=intent.approved_quantity,
            currency=self._currency,
            evaluation_timestamp=now,
            configuration=configuration,
        )

        def persist_submission() -> None:
            self.ledger.append(
                self.ledger.create_record(
                    occurred_at=now,
                    status=DemoTradeStatus.SUBMITTED,
                    strategy=candidate.strategy_variant,
                    instrument=candidate.instrument,
                    timeframe="OPPORTUNITY",
                    regime="VALIDATED",
                    session="DEMO",
                    candidate_id=candidate.candidate_id,
                    execution_id=request.execution_request_id,
                )
            )

        outcome = await ExecutionEngine(
            self.broker,
            configuration=configuration,
            risk_engine=self._risk_engine,
            before_submission=persist_submission,
        ).execute(
            request=request,
            decision=self._decision,
            candidate=candidate,
            account=self._account,
            market=self._market,
            positions=self._positions,
            confirmation=None,
            evaluation_timestamp=now,
            orders_today=self.ledger.submitted_on(now.date()),
            automatic=True,
        )
        if outcome.result.status.value == "ACCEPTED":
            self.ledger.append(
                self.ledger.create_record(
                    occurred_at=now,
                    status=DemoTradeStatus.CONFIRMED,
                    strategy=candidate.strategy_variant,
                    instrument=candidate.instrument,
                    timeframe="OPPORTUNITY",
                    regime="VALIDATED",
                    session="DEMO",
                    candidate_id=candidate.candidate_id,
                    execution_id=request.execution_request_id,
                )
            )
        return outcome
