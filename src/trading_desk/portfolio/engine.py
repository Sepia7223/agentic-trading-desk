"""Atomic deterministic simulated position lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from trading_desk.portfolio.config import (
    EndOfDataPolicy,
    IntrabarPolicy,
    PaperPortfolioConfiguration,
)
from trading_desk.portfolio.errors import PortfolioStateError
from trading_desk.portfolio.fills import (
    commission,
    entry_fill_price,
    exit_fill_price,
    funding_charge,
)
from trading_desk.portfolio.fingerprints import fingerprint
from trading_desk.portfolio.journal import NullPortfolioJournal, PortfolioJournal
from trading_desk.portfolio.ledger import InMemoryPortfolioRepository, build_event
from trading_desk.portfolio.models import (
    ClosedTradeRecord,
    DailyAccounting,
    EventType,
    FillReason,
    FillSide,
    IntentRejection,
    IntentRejectionCode,
    MarketBar,
    MarketQuote,
    PaperPosition,
    PortfolioEvent,
    PortfolioState,
    PositionCloseResult,
    PositionOpenResult,
    PositionStatus,
    SimulatedFill,
)
from trading_desk.portfolio.state import account_risk_state, build_state
from trading_desk.risk.fingerprints import fingerprint as risk_fingerprint
from trading_desk.risk.models import (
    AccountRiskState,
    RiskDecision,
    RiskDecisionStatus,
    TradeCandidate,
    TradeDirection,
)

ZERO = Decimal("0")


class PaperPortfolio:
    """Local-only paper portfolio; the Risk Engine remains the approval authority."""

    def __init__(
        self,
        configuration: PaperPortfolioConfiguration | None = None,
        repository: InMemoryPortfolioRepository | None = None,
        journal: PortfolioJournal | None = None,
    ) -> None:
        self.configuration = configuration or PaperPortfolioConfiguration()
        self.repository = repository or InMemoryPortfolioRepository()
        self.journal = journal or NullPortfolioJournal()
        self._closed_trades: tuple[ClosedTradeRecord, ...] = ()

    @property
    def state(self) -> PortfolioState:
        if self.repository.state is None:
            raise PortfolioStateError("paper portfolio has not been created")
        return self.repository.state

    @property
    def events(self) -> tuple[PortfolioEvent, ...]:
        return self.repository.events

    @property
    def closed_trades(self) -> tuple[ClosedTradeRecord, ...]:
        return self._closed_trades

    def create(self, portfolio_id: str, timestamp: datetime) -> PortfolioState:
        now = _utc(timestamp)
        if self.repository.state is not None:
            raise PortfolioStateError("paper portfolio already exists")
        daily = DailyAccounting(
            trading_day=now.date().isoformat(),
            start_of_day_equity=self.configuration.initial_cash,
            realized_daily_pnl=ZERO,
            peak_equity=self.configuration.initial_cash,
            consecutive_losses=0,
        )
        state = build_state(
            portfolio_id=portfolio_id,
            timestamp=now,
            initial_cash=self.configuration.initial_cash,
            cash=self.configuration.initial_cash,
            realized_pnl=ZERO,
            positions=(),
            daily=daily,
            ledger_sequence=2,
            configuration=self.configuration,
        )
        created = build_event(
            sequence_number=1,
            event_type=EventType.PORTFOLIO_CREATED,
            timestamp=now,
            portfolio_id=portfolio_id,
            payload={"configuration_fingerprint": self.configuration.fingerprint},
            previous_event_fingerprint=None,
        )
        snapshot = build_event(
            sequence_number=2,
            event_type=EventType.STATE_SNAPSHOT_CREATED,
            timestamp=now,
            portfolio_id=portfolio_id,
            payload={"state": state},
            previous_event_fingerprint=created.event_fingerprint,
        )
        self._commit((created, snapshot), state)
        return state

    def open_position(
        self,
        decision: RiskDecision,
        candidate: TradeCandidate,
        market: MarketQuote,
        evaluation_timestamp: datetime,
        *,
        quantity: Decimal | None = None,
    ) -> PositionOpenResult:
        now = _utc(evaluation_timestamp)
        state = self._roll_daily(self.state, now)
        reasons = self._validate_intent(decision, candidate, market, state, now, quantity)
        if reasons:
            rejection = IntentRejection(
                risk_decision_id=decision.decision_id,
                timestamp=now,
                reason_codes=tuple(dict.fromkeys(reasons)),
            )
            rejected_state, events = self._events_with_snapshot(
                state,
                now,
                EventType.INTENT_REJECTED,
                {"rejection": rejection},
                risk_decision_id=decision.decision_id,
                candidate_id=candidate.candidate_id,
            )
            self._commit(events, rejected_state)
            return PositionOpenResult(accepted=False, rejection=rejection)

        assert decision.approved_intent is not None
        intent = decision.approved_intent
        approved_quantity = intent.approved_quantity
        fill_quantity = approved_quantity if quantity is None else quantity
        assert market.ask is not None
        assert market.bid is not None
        fill_price, slippage_per_unit = entry_fill_price(market.ask, self.configuration)
        entry_commission = commission(fill_price, fill_quantity, self.configuration)
        position_id = fingerprint(
            {"portfolio_id": state.portfolio_id, "risk_decision_id": decision.decision_id}
        )
        fill_id = fingerprint(
            {"position_id": position_id, "side": FillSide.ENTRY, "timestamp": now}
        )
        fill = SimulatedFill(
            fill_id=fill_id,
            position_id=position_id,
            risk_decision_id=decision.decision_id,
            side=FillSide.ENTRY,
            quantity=fill_quantity,
            reference_price=market.ask,
            slippage=slippage_per_unit,
            fill_price=fill_price,
            commission=entry_commission,
            funding=ZERO,
            timestamp=now,
            fill_reason=FillReason.ENTRY,
        )
        position = PaperPosition(
            position_id=position_id,
            instrument=candidate.instrument,
            epic=candidate.epic,
            asset_class=candidate.asset_class,
            direction=candidate.direction,
            quantity=fill_quantity,
            entry_timestamp=now,
            entry_price=fill_price,
            current_mark_timestamp=now,
            current_mark_price=market.bid,
            stop_price=intent.stop_reference,
            target_price=intent.target_reference,
            gross_unrealized_pnl=(market.bid - fill_price)
            * fill_quantity
            * market.value_per_price_unit,
            net_unrealized_pnl=(market.bid - fill_price)
            * fill_quantity
            * market.value_per_price_unit,
            accrued_funding=ZERO,
            entry_commission=entry_commission,
            entry_slippage_cost=slippage_per_unit * fill_quantity,
            current_exposure=market.bid * fill_quantity * market.value_per_price_unit,
            open_risk_amount=intent.risk_amount,
            value_per_price_unit=market.value_per_price_unit,
            maximum_favorable_excursion=ZERO,
            maximum_adverse_excursion=max(
                (fill_price - market.bid) * fill_quantity * market.value_per_price_unit, ZERO
            ),
            risk_decision_id=decision.decision_id,
            candidate_id=candidate.candidate_id,
            signal_id=candidate.signal_id,
            strategy_configuration_fingerprint=candidate.strategy_configuration_fingerprint,
            risk_configuration_fingerprint=intent.risk_configuration_fingerprint,
            status=PositionStatus.OPEN,
        )
        new_state = build_state(
            portfolio_id=state.portfolio_id,
            timestamp=now,
            initial_cash=state.initial_cash,
            cash=state.cash - entry_commission,
            realized_pnl=state.realized_pnl,
            positions=state.positions + (position,),
            daily=state.daily,
            ledger_sequence=state.ledger_sequence + 3,
            configuration=self.configuration,
        )
        accepted = self._event(
            state,
            1,
            EventType.INTENT_ACCEPTED,
            now,
            {"decision_fingerprint": decision.decision_fingerprint},
            position,
        )
        opened = build_event(
            sequence_number=state.ledger_sequence + 2,
            event_type=EventType.POSITION_OPENED,
            timestamp=now,
            portfolio_id=state.portfolio_id,
            payload={"position": position, "fill": fill},
            previous_event_fingerprint=accepted.event_fingerprint,
            position_id=position.position_id,
            risk_decision_id=decision.decision_id,
            candidate_id=candidate.candidate_id,
        )
        snapshot = build_event(
            sequence_number=state.ledger_sequence + 3,
            event_type=EventType.STATE_SNAPSHOT_CREATED,
            timestamp=now,
            portfolio_id=state.portfolio_id,
            payload={"state": new_state},
            previous_event_fingerprint=opened.event_fingerprint,
        )
        self._commit((accepted, opened, snapshot), new_state)
        return PositionOpenResult(accepted=True, position=position, fill=fill)

    def mark(self, market: MarketQuote, evaluation_timestamp: datetime) -> PortfolioState:
        now = _utc(evaluation_timestamp)
        state = self._roll_daily(self.state, now)
        position = self._open_position_for(market.epic, state)
        self._validate_quote(market, now, position.current_mark_timestamp)
        assert market.bid is not None
        gross = (
            (market.bid - position.entry_price) * position.quantity * position.value_per_price_unit
        )
        updated = position.model_copy(
            update={
                "current_mark_timestamp": market.timestamp,
                "current_mark_price": market.bid,
                "gross_unrealized_pnl": gross,
                "net_unrealized_pnl": gross,
                "current_exposure": market.bid * position.quantity * position.value_per_price_unit,
                "maximum_favorable_excursion": max(position.maximum_favorable_excursion, gross),
                "maximum_adverse_excursion": max(position.maximum_adverse_excursion, -gross),
            }
        )
        positions = tuple(
            updated if item.position_id == position.position_id else item
            for item in state.positions
        )
        daily = state.daily.model_copy(
            update={"peak_equity": max(state.daily.peak_equity, state.cash + gross)}
        )
        marked_state, events = self._events_with_snapshot(
            state,
            now,
            EventType.POSITION_MARKED,
            {"position": updated, "market_snapshot_id": market.snapshot_id},
            position=updated,
            positions=positions,
            daily=daily,
        )
        self._commit(events, marked_state)
        return marked_state

    def apply_funding(self, position_id: str, timestamp: datetime) -> PortfolioState:
        now = _utc(timestamp)
        state = self._roll_daily(self.state, now)
        position = self._position(position_id, state)
        elapsed_days = (now.date() - position.entry_timestamp.date()).days
        total = funding_charge(
            position.entry_price,
            position.quantity,
            position.value_per_price_unit,
            elapsed_days,
            self.configuration,
        )
        incremental = total - position.accrued_funding
        if incremental < ZERO:
            raise PortfolioStateError("funding timestamp predates previously applied funding")
        if incremental == ZERO:
            return state
        updated = position.model_copy(update={"accrued_funding": total})
        positions = tuple(
            updated if item.position_id == position_id else item for item in state.positions
        )
        funded_state, events = self._events_with_snapshot(
            state,
            now,
            EventType.FUNDING_APPLIED,
            {"funding": incremental, "total_funding": total},
            position=updated,
            positions=positions,
            cash=state.cash - incremental,
        )
        self._commit(events, funded_state)
        return funded_state

    def process_bar(
        self, bar: MarketBar, evaluation_timestamp: datetime
    ) -> PositionCloseResult | None:
        now = _utc(evaluation_timestamp)
        position = self._open_position_for(bar.epic, self.state)
        if not bar.tradeable or bar.low_bid is None or bar.high_bid is None:
            return None
        if bar.timestamp <= position.entry_timestamp or bar.timestamp > now:
            raise PortfolioStateError("bar chronology is invalid")
        stop_hit = bar.low_bid <= position.stop_price
        target_hit = position.target_price is not None and bar.high_bid >= position.target_price
        if stop_hit and target_hit:
            if self.configuration.intrabar_policy is IntrabarPolicy.REJECT_AMBIGUOUS:
                return None
            reason = (
                FillReason.STOP
                if self.configuration.intrabar_policy is IntrabarPolicy.ADVERSE_FIRST
                else FillReason.TARGET
            )
        elif stop_hit:
            reason = FillReason.STOP
        elif target_hit:
            reason = FillReason.TARGET
        else:
            return None
        reference = position.stop_price if reason is FillReason.STOP else position.target_price
        assert reference is not None
        quote = MarketQuote(
            snapshot_id=bar.snapshot_id,
            timestamp=bar.timestamp,
            epic=bar.epic,
            bid=reference,
            ask=max(reference, bar.close_ask) if bar.close_ask is not None else reference,
            market_status=bar.market_status,
            value_per_price_unit=position.value_per_price_unit,
        )
        return self.close_position(position.position_id, quote, now, reason=reason)

    def close_position(
        self,
        position_id: str,
        market: MarketQuote,
        evaluation_timestamp: datetime,
        *,
        reason: FillReason = FillReason.MANUAL_SIMULATED_EXIT,
    ) -> PositionCloseResult:
        now = _utc(evaluation_timestamp)
        state = self._roll_daily(self.state, now)
        position = self._position(position_id, state)
        self._validate_quote(market, now, position.current_mark_timestamp)
        if market.epic != position.epic:
            raise PortfolioStateError("exit market does not match position")
        assert market.bid is not None
        fill_price, slippage_per_unit = exit_fill_price(market.bid, self.configuration)
        exit_commission = commission(fill_price, position.quantity, self.configuration)
        gross = (
            (fill_price - position.entry_price) * position.quantity * position.value_per_price_unit
        )
        net = gross - position.entry_commission - exit_commission - position.accrued_funding
        fill = SimulatedFill(
            fill_id=fingerprint(
                {"position_id": position_id, "side": FillSide.EXIT, "timestamp": now}
            ),
            position_id=position_id,
            risk_decision_id=position.risk_decision_id,
            side=FillSide.EXIT,
            quantity=position.quantity,
            reference_price=market.bid,
            slippage=slippage_per_unit,
            fill_price=fill_price,
            commission=exit_commission,
            funding=position.accrued_funding,
            timestamp=now,
            fill_reason=reason,
        )
        closed = position.model_copy(
            update={
                "current_mark_timestamp": now,
                "current_mark_price": fill_price,
                "gross_unrealized_pnl": ZERO,
                "net_unrealized_pnl": ZERO,
                "current_exposure": ZERO,
                "open_risk_amount": ZERO,
                "status": PositionStatus.CLOSED,
            }
        )
        trade_fields = {
            "position_id": position_id,
            "risk_decision_id": position.risk_decision_id,
            "candidate_id": position.candidate_id,
            "signal_id": position.signal_id,
            "instrument": position.instrument,
            "direction": position.direction,
            "quantity": position.quantity,
            "entry_timestamp": position.entry_timestamp,
            "entry_price": position.entry_price,
            "exit_timestamp": now,
            "exit_price": fill_price,
            "gross_pnl": gross,
            "net_pnl": net,
            "entry_commission": position.entry_commission,
            "exit_commission": exit_commission,
            "funding": position.accrued_funding,
            "slippage_cost": position.entry_slippage_cost + slippage_per_unit * position.quantity,
            "holding_period": now - position.entry_timestamp,
            "exit_reason": reason,
            "maximum_favorable_excursion": position.maximum_favorable_excursion,
            "maximum_adverse_excursion": position.maximum_adverse_excursion,
            "strategy_configuration_fingerprint": position.strategy_configuration_fingerprint,
            "risk_configuration_fingerprint": position.risk_configuration_fingerprint,
            "portfolio_configuration_fingerprint": self.configuration.fingerprint,
        }
        trade_fp = fingerprint(trade_fields)
        trade = ClosedTradeRecord.model_validate(
            {**trade_fields, "trade_id": trade_fp, "trade_fingerprint": trade_fp}
        )
        positions = tuple(
            closed if item.position_id == position_id else item for item in state.positions
        )
        new_cash = state.cash + gross - exit_commission
        daily_pnl = state.daily.realized_daily_pnl + net
        consecutive = 0 if net > ZERO else state.daily.consecutive_losses + int(net < ZERO)
        daily = state.daily.model_copy(
            update={"realized_daily_pnl": daily_pnl, "consecutive_losses": consecutive}
        )
        trigger_type = {
            FillReason.STOP: EventType.STOP_TRIGGERED,
            FillReason.TARGET: EventType.TARGET_TRIGGERED,
            FillReason.SCHEDULED_EXIT: EventType.SCHEDULED_EXIT,
        }.get(reason)
        events: tuple[PortfolioEvent, ...]
        if trigger_type is None:
            closed_state, events = self._events_with_snapshot(
                state,
                now,
                EventType.POSITION_CLOSED,
                {"position": closed, "fill": fill, "trade": trade},
                position=closed,
                positions=positions,
                cash=new_cash,
                realized_pnl=state.realized_pnl + net,
                daily=daily,
            )
        else:
            closed_state = build_state(
                portfolio_id=state.portfolio_id,
                timestamp=now,
                initial_cash=state.initial_cash,
                cash=new_cash,
                realized_pnl=state.realized_pnl + net,
                positions=positions,
                daily=daily,
                ledger_sequence=state.ledger_sequence + 3,
                configuration=self.configuration,
            )
            triggered = build_event(
                sequence_number=state.ledger_sequence + 1,
                event_type=trigger_type,
                timestamp=now,
                portfolio_id=state.portfolio_id,
                payload={"reference_price": market.bid, "reason": reason},
                previous_event_fingerprint=self.events[-1].event_fingerprint,
                position_id=position.position_id,
                risk_decision_id=position.risk_decision_id,
                candidate_id=position.candidate_id,
            )
            closed_event = build_event(
                sequence_number=state.ledger_sequence + 2,
                event_type=EventType.POSITION_CLOSED,
                timestamp=now,
                portfolio_id=state.portfolio_id,
                payload={"position": closed, "fill": fill, "trade": trade},
                previous_event_fingerprint=triggered.event_fingerprint,
                position_id=position.position_id,
                risk_decision_id=position.risk_decision_id,
                candidate_id=position.candidate_id,
            )
            snapshot = build_event(
                sequence_number=state.ledger_sequence + 3,
                event_type=EventType.STATE_SNAPSHOT_CREATED,
                timestamp=now,
                portfolio_id=state.portfolio_id,
                payload={"state": closed_state},
                previous_event_fingerprint=closed_event.event_fingerprint,
            )
            events = (triggered, closed_event, snapshot)
        self._commit(events, closed_state)
        self._closed_trades += (trade,)
        self.journal.record_trade(trade)
        return PositionCloseResult(position=closed, fill=fill, trade=trade)

    def end_of_data(
        self, position_id: str, market: MarketQuote, timestamp: datetime
    ) -> PositionCloseResult | None:
        if self.configuration.end_of_data_policy is EndOfDataPolicy.LIQUIDATE_IF_TRADEABLE:
            try:
                return self.close_position(
                    position_id,
                    market,
                    timestamp,
                    reason=FillReason.FORCED_END_OF_DATA_LIQUIDATION,
                )
            except PortfolioStateError:
                pass
        now = _utc(timestamp)
        state = self._roll_daily(self.state, now)
        position = self._position(position_id, state)
        unresolved = position.model_copy(update={"status": PositionStatus.UNRESOLVED})
        positions = tuple(
            unresolved if item.position_id == position_id else item for item in state.positions
        )
        unresolved_state, events = self._events_with_snapshot(
            state,
            now,
            EventType.POSITION_UNRESOLVED,
            {"position": unresolved, "reason": "NO_VALID_EXIT_QUOTE"},
            position=unresolved,
            positions=positions,
        )
        self._commit(events, unresolved_state)
        return None

    def to_account_risk_state(
        self,
        *,
        kill_switch_active: bool = False,
        required_epics: tuple[str, ...] = (),
        required_asset_classes: tuple[str, ...] = (),
    ) -> AccountRiskState:
        return account_risk_state(
            self.state,
            kill_switch_active=kill_switch_active,
            required_epics=required_epics,
            required_asset_classes=required_asset_classes,
        )

    def _validate_intent(
        self,
        decision: RiskDecision,
        candidate: TradeCandidate,
        market: MarketQuote,
        state: PortfolioState,
        now: datetime,
        quantity: Decimal | None,
    ) -> list[IntentRejectionCode]:
        reasons: list[IntentRejectionCode] = []
        intent = decision.approved_intent
        if decision.status is not RiskDecisionStatus.APPROVED or intent is None:
            return [IntentRejectionCode.APPROVAL_NOT_APPROVED]
        expected_decision_fp = risk_fingerprint(
            decision.model_dump(mode="python", exclude={"decision_fingerprint"})
        )
        if decision.decision_fingerprint != expected_decision_fp:
            reasons.append(IntentRejectionCode.APPROVAL_FINGERPRINT_MISMATCH)
        if self.configuration.approval_expiry_enforced and not intent.is_valid_at(now):
            reasons.append(IntentRejectionCode.APPROVAL_EXPIRED)
        if (
            decision.candidate_id != candidate.candidate_id
            or intent.candidate_id != candidate.candidate_id
            or decision.signal_id != candidate.signal_id
            or intent.risk_decision_id != decision.decision_id
        ):
            reasons.append(IntentRejectionCode.INVALID_INPUT)
        if (
            decision.approved_quantity != intent.approved_quantity
            or decision.approved_entry_reference != intent.entry_reference
            or decision.approved_stop_reference != intent.stop_reference
            or decision.approved_target_reference != intent.target_reference
            or decision.risk_amount != intent.risk_amount
            or decision.notional_exposure != intent.notional_exposure
        ):
            reasons.append(IntentRejectionCode.INVALID_INPUT)
        if (
            intent.strategy_configuration_fingerprint
            != candidate.strategy_configuration_fingerprint
        ):
            reasons.append(IntentRejectionCode.STRATEGY_FINGERPRINT_MISMATCH)
        if intent.risk_configuration_fingerprint != decision.risk_configuration_fingerprint:
            reasons.append(IntentRejectionCode.RISK_FINGERPRINT_MISMATCH)
        if intent.account_snapshot_id != state.snapshot_id:
            reasons.append(IntentRejectionCode.PORTFOLIO_STATE_MISMATCH)
        if (
            intent.market_snapshot_id != market.snapshot_id
            or market.epic != intent.epic
            or candidate.epic != intent.epic
            or market.bid != candidate.bid
            or market.ask != candidate.ask
            or market.ask != intent.entry_reference
        ):
            reasons.append(IntentRejectionCode.MARKET_STATE_MISMATCH)
        requested = intent.approved_quantity if quantity is None else quantity
        if not requested.is_finite() or requested <= ZERO or requested > intent.approved_quantity:
            reasons.append(IntentRejectionCode.INVALID_QUANTITY)
        if (
            quantity is not None
            and quantity != intent.approved_quantity
            and not self.configuration.allow_partial_fills
        ):
            reasons.append(IntentRejectionCode.INVALID_QUANTITY)
        exponent = requested.as_tuple().exponent
        if isinstance(exponent, int) and exponent < -self.configuration.quantity_precision:
            reasons.append(IntentRejectionCode.INVALID_QUANTITY)
        if (
            intent.direction is not TradeDirection.LONG
            or candidate.direction is not TradeDirection.LONG
        ):
            reasons.append(IntentRejectionCode.UNSUPPORTED_DIRECTION)
        if intent.stop_reference >= intent.entry_reference:
            reasons.append(IntentRejectionCode.INVALID_STOP)
        if (
            intent.target_reference is not None
            and intent.target_reference <= intent.entry_reference
        ):
            reasons.append(IntentRejectionCode.INVALID_TARGET)
        if not market.tradeable:
            reasons.append(IntentRejectionCode.MARKET_NOT_TRADEABLE)
        if not _valid_bid_ask(market.bid, market.ask):
            reasons.append(IntentRejectionCode.INVALID_BID_ASK)
        if len(self._open_positions(state)) >= self.configuration.maximum_open_positions:
            reasons.append(IntentRejectionCode.PORTFOLIO_LIMIT_REACHED)
        same_instrument = [item for item in self._open_positions(state) if item.epic == intent.epic]
        if same_instrument and (
            not self.configuration.allow_multiple_positions_per_instrument
            or not self.configuration.allow_pyramiding
        ):
            reasons.append(IntentRejectionCode.POSITION_ALREADY_EXISTS)
        if len(same_instrument) >= self.configuration.maximum_positions_per_instrument:
            reasons.append(IntentRejectionCode.PORTFOLIO_LIMIT_REACHED)
        if self._already_consumed(decision, candidate):
            reasons.append(IntentRejectionCode.DUPLICATE_INTENT)
        if market.ask is not None:
            price, _ = entry_fill_price(market.ask, self.configuration)
            cost = price * requested * market.value_per_price_unit + commission(
                price, requested, self.configuration
            )
            available = max(state.cash - state.gross_exposure, ZERO)
            if cost > available:
                reasons.append(IntentRejectionCode.INSUFFICIENT_CASH)
        try:
            self._validate_quote(market, now, state.timestamp)
        except PortfolioStateError:
            reasons.append(IntentRejectionCode.INVALID_INPUT)
        return reasons

    def _already_consumed(self, decision: RiskDecision, candidate: TradeCandidate) -> bool:
        for event in self.events:
            if event.event_type is EventType.INTENT_ACCEPTED and (
                event.risk_decision_id == decision.decision_id
                or event.candidate_id == candidate.candidate_id
                or decision.decision_fingerprint in event.payload
            ):
                return True
        return False

    def _validate_quote(self, market: MarketQuote, now: datetime, earliest: datetime) -> None:
        if not market.tradeable:
            raise PortfolioStateError("market is not tradeable")
        if not _valid_bid_ask(market.bid, market.ask):
            raise PortfolioStateError("market bid/ask is invalid")
        if market.timestamp < earliest or market.timestamp > now:
            raise PortfolioStateError("market quote chronology is invalid")
        age = Decimal(str((now - market.timestamp).total_seconds()))
        if age > self.configuration.valuation_timestamp_tolerance_seconds:
            raise PortfolioStateError("market quote is stale")

    def _events_with_snapshot(
        self,
        state: PortfolioState,
        now: datetime,
        event_type: EventType,
        payload: object,
        *,
        position: PaperPosition | None = None,
        positions: tuple[PaperPosition, ...] | None = None,
        cash: Decimal | None = None,
        realized_pnl: Decimal | None = None,
        daily: DailyAccounting | None = None,
        risk_decision_id: str | None = None,
        candidate_id: str | None = None,
    ) -> tuple[PortfolioState, tuple[PortfolioEvent, PortfolioEvent]]:
        new_state = build_state(
            portfolio_id=state.portfolio_id,
            timestamp=now,
            initial_cash=state.initial_cash,
            cash=state.cash if cash is None else cash,
            realized_pnl=state.realized_pnl if realized_pnl is None else realized_pnl,
            positions=state.positions if positions is None else positions,
            daily=state.daily if daily is None else daily,
            ledger_sequence=state.ledger_sequence + 2,
            configuration=self.configuration,
        )
        event = build_event(
            sequence_number=state.ledger_sequence + 1,
            event_type=event_type,
            timestamp=now,
            portfolio_id=state.portfolio_id,
            payload=payload,
            previous_event_fingerprint=self.events[-1].event_fingerprint,
            position_id=position.position_id if position is not None else None,
            risk_decision_id=(
                position.risk_decision_id if position is not None else risk_decision_id
            ),
            candidate_id=(position.candidate_id if position is not None else candidate_id),
        )
        snapshot = build_event(
            sequence_number=state.ledger_sequence + 2,
            event_type=EventType.STATE_SNAPSHOT_CREATED,
            timestamp=now,
            portfolio_id=state.portfolio_id,
            payload={"state": new_state},
            previous_event_fingerprint=event.event_fingerprint,
        )
        return new_state, (event, snapshot)

    def _event(
        self,
        state: PortfolioState,
        offset: int,
        event_type: EventType,
        now: datetime,
        payload: object,
        position: PaperPosition,
    ) -> PortfolioEvent:
        return build_event(
            sequence_number=state.ledger_sequence + offset,
            event_type=event_type,
            timestamp=now,
            portfolio_id=state.portfolio_id,
            payload=payload,
            previous_event_fingerprint=self.events[-1].event_fingerprint,
            position_id=position.position_id,
            risk_decision_id=position.risk_decision_id,
            candidate_id=position.candidate_id,
        )

    def _roll_daily(self, state: PortfolioState, now: datetime) -> PortfolioState:
        if now < state.timestamp:
            raise PortfolioStateError("evaluation timestamp predates portfolio state")
        if now.date().isoformat() == state.daily.trading_day:
            return state
        return state.model_copy(
            update={
                "daily": DailyAccounting(
                    trading_day=now.date().isoformat(),
                    start_of_day_equity=state.equity,
                    realized_daily_pnl=ZERO,
                    peak_equity=max(state.daily.peak_equity, state.equity),
                    consecutive_losses=state.daily.consecutive_losses,
                )
            }
        )

    def _position(self, position_id: str, state: PortfolioState) -> PaperPosition:
        position = next((item for item in state.positions if item.position_id == position_id), None)
        if position is None or position.status is not PositionStatus.OPEN:
            raise PortfolioStateError("open paper position was not found")
        return position

    def _open_position_for(self, epic: str, state: PortfolioState) -> PaperPosition:
        positions = [item for item in self._open_positions(state) if item.epic == epic]
        if len(positions) != 1:
            raise PortfolioStateError("exactly one matching open paper position is required")
        return positions[0]

    @staticmethod
    def _open_positions(state: PortfolioState) -> tuple[PaperPosition, ...]:
        return tuple(item for item in state.positions if item.status is PositionStatus.OPEN)

    def _commit(self, events: tuple[PortfolioEvent, ...], state: PortfolioState) -> None:
        self.repository.commit(events, state)
        for event in events:
            self.journal.record_event(event)
        self.journal.record_snapshot(state)


def _valid_bid_ask(bid: Decimal | None, ask: Decimal | None) -> bool:
    return (
        bid is not None
        and ask is not None
        and bid.is_finite()
        and ask.is_finite()
        and bid > ZERO
        and ask >= bid
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("portfolio evaluation timestamp must be timezone-aware UTC")
    return value.astimezone(UTC)
