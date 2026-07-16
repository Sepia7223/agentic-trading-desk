"""Ordered fail-closed deterministic risk evaluation."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from trading_desk.risk.config import RiskConfiguration
from trading_desk.risk.exposure import notional_capacity, projected_exposure, quantity_capacity
from trading_desk.risk.fingerprints import fingerprint
from trading_desk.risk.gates import gate_result, is_non_negative, is_positive, is_sha256
from trading_desk.risk.models import (
    AccountRiskState,
    ApprovedTradeIntent,
    DailyLossPolicy,
    GateResult,
    MarketRiskState,
    RiskDecision,
    RiskDecisionStatus,
    RiskGate,
    RiskMarketStatus,
    RiskReasonCode,
    TradeCandidate,
    TradeDirection,
)
from trading_desk.risk.sizing import (
    compatible_increment,
    notional_per_unit,
    raw_quantity,
    risk_budget,
    risk_per_unit,
    round_quantity_down,
)

ZERO = Decimal("0")


class RiskEngine:
    """Pure risk authority with no clock, broker, storage, or network dependency."""

    def __init__(self, configuration: RiskConfiguration | None = None) -> None:
        self.configuration = configuration or RiskConfiguration()

    def evaluate(
        self,
        candidate: TradeCandidate,
        account: AccountRiskState,
        market: MarketRiskState,
        evaluation_timestamp: datetime,
    ) -> RiskDecision:
        if evaluation_timestamp.tzinfo is None or evaluation_timestamp.utcoffset() != UTC.utcoffset(
            evaluation_timestamp
        ):
            raise ValueError("risk evaluation timestamp must be timezone-aware UTC")
        evaluated_at = evaluation_timestamp.astimezone(UTC)
        gates: list[GateResult] = []

        integrity_reasons = self._input_integrity(candidate, account, market, evaluated_at)
        gates.append(gate_result(RiskGate.INPUT_INTEGRITY, *integrity_reasons))

        if self.configuration.kill_switch_enabled and account.kill_switch_active:
            gates.append(gate_result(RiskGate.KILL_SWITCH, RiskReasonCode.KILL_SWITCH_ACTIVE))
            return self._decision(
                candidate,
                account,
                market,
                evaluated_at,
                RiskDecisionStatus.KILL_SWITCHED,
                gates,
            )
        gates.append(gate_result(RiskGate.KILL_SWITCH))
        if integrity_reasons:
            return self._decision(
                candidate,
                account,
                market,
                evaluated_at,
                RiskDecisionStatus.INVALID_INPUT,
                gates,
            )

        configuration_reasons: list[RiskReasonCode] = []
        if not is_sha256(candidate.strategy_configuration_fingerprint):
            configuration_reasons.append(RiskReasonCode.CONFIGURATION_MISMATCH)
        required = self.configuration.required_strategy_configuration_fingerprint
        if required is not None and candidate.strategy_configuration_fingerprint != required:
            configuration_reasons.append(RiskReasonCode.CONFIGURATION_MISMATCH)
        gates.append(gate_result(RiskGate.CONFIGURATION, *configuration_reasons))
        if configuration_reasons:
            return self._decision(
                candidate,
                account,
                market,
                evaluated_at,
                RiskDecisionStatus.INVALID_INPUT,
                gates,
            )

        candidate_reasons: list[RiskReasonCode] = []
        if candidate.signal_timestamp > evaluated_at:
            candidate_reasons.append(RiskReasonCode.SIGNAL_TIMESTAMP_IN_FUTURE)
        if candidate.data_cutoff_timestamp > evaluated_at:
            candidate_reasons.append(RiskReasonCode.INVALID_INPUT)
        if evaluated_at >= candidate.candidate_expiry:
            candidate_reasons.append(RiskReasonCode.CANDIDATE_EXPIRED)
        if evaluated_at - candidate.signal_timestamp > self.configuration.maximum_candidate_age:
            candidate_reasons.append(RiskReasonCode.CANDIDATE_EXPIRED)
        gates.append(gate_result(RiskGate.CANDIDATE_FRESHNESS, *candidate_reasons))
        if candidate_reasons:
            status = (
                RiskDecisionStatus.EXPIRED
                if RiskReasonCode.CANDIDATE_EXPIRED in candidate_reasons
                else RiskDecisionStatus.INVALID_INPUT
            )
            return self._decision(candidate, account, market, evaluated_at, status, gates)

        market_freshness_reasons: list[RiskReasonCode] = []
        if market.timestamp > evaluated_at:
            market_freshness_reasons.append(RiskReasonCode.MARKET_STATE_UNKNOWN)
        elif evaluated_at - market.timestamp > self.configuration.maximum_market_data_age:
            market_freshness_reasons.append(RiskReasonCode.MARKET_DATA_STALE)
        if (
            account.timestamp > evaluated_at
            or evaluated_at - account.timestamp > self.configuration.maximum_account_state_age
        ):
            market_freshness_reasons.append(RiskReasonCode.ACCOUNT_STATE_UNKNOWN)
        if (
            candidate.signal_timestamp - market.timestamp
            > self.configuration.maximum_market_signal_lag
        ):
            market_freshness_reasons.append(RiskReasonCode.MARKET_DATA_STALE)
        gates.append(gate_result(RiskGate.MARKET_DATA_FRESHNESS, *market_freshness_reasons))
        if market_freshness_reasons:
            return self._decision(
                candidate,
                account,
                market,
                evaluated_at,
                RiskDecisionStatus.REJECTED,
                gates,
            )

        market_reasons = self._market_eligibility(candidate, market)
        gates.append(gate_result(RiskGate.MARKET_ELIGIBILITY, *market_reasons))
        if market_reasons:
            return self._decision(
                candidate,
                account,
                market,
                evaluated_at,
                RiskDecisionStatus.REJECTED,
                gates,
            )

        holding_reasons: list[RiskReasonCode] = []
        if candidate.holding_state is None:
            holding_reasons.append(RiskReasonCode.UNKNOWN_HOLDING_STATE)
        elif candidate.holding_state:
            holding_reasons.append(RiskReasonCode.POSITION_ALREADY_OPEN)
        gates.append(gate_result(RiskGate.HOLDING_STATE, *holding_reasons))
        if holding_reasons:
            return self._decision(
                candidate,
                account,
                market,
                evaluated_at,
                RiskDecisionStatus.REJECTED,
                gates,
            )

        entry_reasons = self._entry_stop(candidate, market)
        gates.append(gate_result(RiskGate.ENTRY_STOP, *entry_reasons))
        if entry_reasons:
            return self._decision(
                candidate,
                account,
                market,
                evaluated_at,
                RiskDecisionStatus.REJECTED,
                gates,
            )

        account_reasons = self._account_state(candidate, account)
        gates.append(gate_result(RiskGate.ACCOUNT_STATE, *account_reasons))
        if account_reasons:
            return self._decision(
                candidate,
                account,
                market,
                evaluated_at,
                RiskDecisionStatus.REJECTED,
                gates,
            )

        loss_reasons = self._loss_and_drawdown(account)
        gates.append(gate_result(RiskGate.LOSS_AND_DRAWDOWN, *loss_reasons))
        if loss_reasons:
            return self._decision(
                candidate,
                account,
                market,
                evaluated_at,
                RiskDecisionStatus.REJECTED,
                gates,
            )

        count_reasons = self._position_counts(candidate, account)
        gates.append(gate_result(RiskGate.POSITION_COUNTS, *count_reasons))
        if count_reasons:
            return self._decision(
                candidate,
                account,
                market,
                evaluated_at,
                RiskDecisionStatus.REJECTED,
                gates,
            )

        return self._size_and_decide(candidate, account, market, evaluated_at, gates)

    def _input_integrity(
        self,
        candidate: TradeCandidate,
        account: AccountRiskState,
        market: MarketRiskState,
        evaluated_at: datetime,
    ) -> list[RiskReasonCode]:
        reasons: list[RiskReasonCode] = []
        candidate_values = (
            candidate.entry_reference,
            candidate.stop_reference,
            candidate.bid,
            candidate.ask,
            candidate.spread_bps,
            candidate.volatility_or_atr,
        )
        if any(value is not None and not value.is_finite() for value in candidate_values):
            reasons.append(RiskReasonCode.INVALID_INPUT)
        if candidate.candidate_expiry < candidate.signal_timestamp:
            reasons.append(RiskReasonCode.INVALID_INPUT)
        if candidate.data_cutoff_timestamp > candidate.signal_timestamp:
            reasons.append(RiskReasonCode.INVALID_INPUT)
        if candidate.direction is not TradeDirection.LONG:
            reasons.append(RiskReasonCode.INVALID_INPUT)
        if (
            candidate.bid is not None
            and candidate.ask is not None
            and candidate.bid.is_finite()
            and candidate.ask.is_finite()
            and (candidate.bid <= 0 or candidate.ask <= 0 or candidate.ask < candidate.bid)
        ):
            reasons.append(RiskReasonCode.INVALID_BID_ASK)
        if (
            candidate.spread_bps is not None
            and candidate.spread_bps.is_finite()
            and candidate.spread_bps < 0
        ):
            reasons.append(RiskReasonCode.INVALID_INPUT)
        if (
            candidate.volatility_or_atr is not None
            and candidate.volatility_or_atr.is_finite()
            and candidate.volatility_or_atr < 0
        ):
            reasons.append(RiskReasonCode.INVALID_INPUT)

        known_account_values = (
            account.account_equity,
            account.available_capital,
            account.realized_daily_pnl,
            account.unrealized_pnl,
            account.current_drawdown_fraction,
            account.gross_exposure,
            account.open_risk_amount,
        )
        if any(value is not None and not value.is_finite() for value in known_account_values):
            reasons.append(RiskReasonCode.INVALID_INPUT)
        if (
            account.account_equity is not None
            and account.account_equity.is_finite()
            and account.account_equity <= 0
        ):
            reasons.append(RiskReasonCode.INSUFFICIENT_EQUITY)
        if (
            account.available_capital is not None
            and account.available_capital.is_finite()
            and account.available_capital < 0
        ):
            reasons.append(RiskReasonCode.INSUFFICIENT_AVAILABLE_CAPITAL)
        if (
            account.current_drawdown_fraction is not None
            and account.current_drawdown_fraction.is_finite()
            and account.current_drawdown_fraction < 0
        ):
            reasons.append(RiskReasonCode.INVALID_INPUT)
        if (
            account.gross_exposure is not None
            and account.gross_exposure.is_finite()
            and account.gross_exposure < 0
        ):
            reasons.append(RiskReasonCode.INVALID_INPUT)
        if (
            account.open_risk_amount is not None
            and account.open_risk_amount.is_finite()
            and account.open_risk_amount < 0
        ):
            reasons.append(RiskReasonCode.INVALID_INPUT)
        if account.open_position_count is not None and account.open_position_count < 0:
            reasons.append(RiskReasonCode.INVALID_INPUT)
        if account.consecutive_losses is not None and account.consecutive_losses < 0:
            reasons.append(RiskReasonCode.INVALID_INPUT)
        if any(
            not item.amount.is_finite() or item.amount < 0 for item in account.instrument_exposure
        ):
            reasons.append(RiskReasonCode.INVALID_INPUT)
        if any(
            not item.amount.is_finite() or item.amount < 0 for item in account.asset_class_exposure
        ):
            reasons.append(RiskReasonCode.INVALID_INPUT)
        if any(item.count < 0 for item in account.instrument_position_count):
            reasons.append(RiskReasonCode.INVALID_INPUT)

        market_values = (
            market.bid,
            market.ask,
            market.spread_bps,
            market.minimum_deal_size,
            market.quantity_increment,
            market.minimum_stop_distance,
            market.maximum_stop_distance,
            market.value_per_price_unit,
        )
        if any(value is not None and not value.is_finite() for value in market_values):
            reasons.append(RiskReasonCode.INVALID_INPUT)
        if market.timestamp > evaluated_at:
            reasons.append(RiskReasonCode.MARKET_STATE_UNKNOWN)
        return list(dict.fromkeys(reasons))

    def _market_eligibility(
        self, candidate: TradeCandidate, market: MarketRiskState
    ) -> list[RiskReasonCode]:
        reasons: list[RiskReasonCode] = []
        required_market_values = (
            market.bid,
            market.ask,
            market.spread_bps,
            market.minimum_deal_size,
            market.quantity_increment,
            market.minimum_stop_distance,
            market.maximum_stop_distance,
            market.value_per_price_unit,
        )
        if not market.state_complete or any(value is None for value in required_market_values):
            reasons.append(RiskReasonCode.MARKET_STATE_UNKNOWN)
            return reasons
        assert market.minimum_deal_size is not None
        assert market.quantity_increment is not None
        assert market.minimum_stop_distance is not None
        assert market.maximum_stop_distance is not None
        assert market.value_per_price_unit is not None
        if market.epic != candidate.epic or market.instrument != candidate.instrument:
            reasons.append(RiskReasonCode.MARKET_STATE_UNKNOWN)
        if candidate.market_status is not RiskMarketStatus.TRADEABLE:
            reasons.append(RiskReasonCode.MARKET_CLOSED)
        if market.market_status is not RiskMarketStatus.TRADEABLE:
            reasons.append(RiskReasonCode.MARKET_CLOSED)
        if candidate.market_status is not market.market_status:
            reasons.append(RiskReasonCode.MARKET_STATE_UNKNOWN)
        candidate_bid, candidate_ask = candidate.bid, candidate.ask
        if (
            candidate_bid is None
            or candidate_ask is None
            or not candidate_bid.is_finite()
            or not candidate_ask.is_finite()
            or candidate_bid <= 0
            or candidate_ask <= 0
            or candidate_ask < candidate_bid
        ):
            reasons.append(RiskReasonCode.INVALID_BID_ASK)
        market_bid, market_ask = market.bid, market.ask
        if (
            market_bid is None
            or market_ask is None
            or not market_bid.is_finite()
            or not market_ask.is_finite()
            or market_bid <= 0
            or market_ask <= 0
            or market_ask < market_bid
        ):
            reasons.append(RiskReasonCode.INVALID_BID_ASK)
        if candidate.bid != market.bid or candidate.ask != market.ask:
            reasons.append(RiskReasonCode.MARKET_STATE_UNKNOWN)
        if candidate.spread_bps != market.spread_bps:
            reasons.append(RiskReasonCode.MARKET_STATE_UNKNOWN)
        if not is_non_negative(candidate.spread_bps) or not is_non_negative(market.spread_bps):
            reasons.append(RiskReasonCode.INVALID_INPUT)
        elif (
            candidate.spread_bps > self.configuration.maximum_spread_bps
            or market.spread_bps > self.configuration.maximum_spread_bps
        ):
            reasons.append(RiskReasonCode.SPREAD_TOO_WIDE)
        if (
            not all(
                is_positive(value)
                for value in (
                    market.minimum_deal_size,
                    market.quantity_increment,
                    market.minimum_stop_distance,
                    market.maximum_stop_distance,
                    market.value_per_price_unit,
                )
            )
            or market.minimum_stop_distance > market.maximum_stop_distance
        ):
            reasons.append(RiskReasonCode.MARKET_STATE_UNKNOWN)
        return list(dict.fromkeys(reasons))

    def _entry_stop(
        self, candidate: TradeCandidate, market: MarketRiskState
    ) -> list[RiskReasonCode]:
        if not is_positive(candidate.entry_reference) or not is_positive(candidate.stop_reference):
            return [RiskReasonCode.INVALID_INPUT]
        entry = candidate.entry_reference
        stop = candidate.stop_reference
        if market.bid is None or market.ask is None or not market.bid <= entry <= market.ask:
            return [RiskReasonCode.INVALID_BID_ASK]
        if stop >= entry:
            return [RiskReasonCode.INVALID_STOP_DIRECTION]
        if candidate.target_reference is not None and (
            not candidate.target_reference.is_finite() or candidate.target_reference <= entry
        ):
            return [RiskReasonCode.INVALID_INPUT]
        if market.minimum_stop_distance is None or market.maximum_stop_distance is None:
            return [RiskReasonCode.MARKET_STATE_UNKNOWN]
        distance = entry - stop
        minimum = max(self.configuration.minimum_stop_distance, market.minimum_stop_distance)
        maximum = min(self.configuration.maximum_stop_distance, market.maximum_stop_distance)
        reasons: list[RiskReasonCode] = []
        if distance < minimum:
            reasons.append(RiskReasonCode.STOP_TOO_CLOSE)
        if distance > maximum:
            reasons.append(RiskReasonCode.STOP_TOO_FAR)
        return reasons

    def _account_state(
        self, candidate: TradeCandidate, account: AccountRiskState
    ) -> list[RiskReasonCode]:
        required: list[object | None] = [
            account.account_equity,
            account.available_capital,
            account.realized_daily_pnl,
            account.current_drawdown_fraction,
            account.gross_exposure,
            account.open_risk_amount,
            account.open_position_count,
            account.consecutive_losses,
            account.instrument_exposure_for(candidate.epic),
            account.asset_class_exposure_for(candidate.asset_class),
            account.instrument_positions_for(candidate.epic),
        ]
        if self.configuration.include_unrealized_in_daily_loss:
            required.append(account.unrealized_pnl)
        if not account.state_complete or any(value is None for value in required):
            return [RiskReasonCode.ACCOUNT_STATE_UNKNOWN]
        if not is_positive(account.account_equity):
            return [RiskReasonCode.INSUFFICIENT_EQUITY]
        if not is_non_negative(account.available_capital):
            return [RiskReasonCode.INSUFFICIENT_AVAILABLE_CAPITAL]
        return []

    def _loss_and_drawdown(self, account: AccountRiskState) -> list[RiskReasonCode]:
        assert account.account_equity is not None
        assert account.realized_daily_pnl is not None
        assert account.current_drawdown_fraction is not None
        assert account.consecutive_losses is not None
        reasons: list[RiskReasonCode] = []
        realized_loss = max(-account.realized_daily_pnl, ZERO)
        realized_limit = (
            account.account_equity * self.configuration.maximum_daily_realized_loss_fraction
        )
        if realized_loss >= realized_limit:
            reasons.append(RiskReasonCode.DAILY_REALIZED_LOSS_LIMIT_REACHED)
        if self.configuration.include_unrealized_in_daily_loss:
            assert account.unrealized_pnl is not None
            total_loss = max(-(account.realized_daily_pnl + account.unrealized_pnl), ZERO)
            total_limit = (
                account.account_equity * self.configuration.maximum_daily_total_loss_fraction
            )
            if total_loss >= total_limit:
                reasons.append(RiskReasonCode.DAILY_TOTAL_LOSS_LIMIT_REACHED)
        if (
            account.current_drawdown_fraction
            >= self.configuration.maximum_portfolio_drawdown_fraction
        ):
            reasons.append(RiskReasonCode.DRAWDOWN_LIMIT_REACHED)
        if (
            self.configuration.consecutive_loss_limit_enabled
            and account.consecutive_losses >= self.configuration.maximum_consecutive_losses
        ):
            reasons.append(RiskReasonCode.MAX_CONSECUTIVE_LOSSES_REACHED)
        return reasons

    def _position_counts(
        self, candidate: TradeCandidate, account: AccountRiskState
    ) -> list[RiskReasonCode]:
        assert account.open_position_count is not None
        instrument_count = account.instrument_positions_for(candidate.epic)
        assert instrument_count is not None
        reasons: list[RiskReasonCode] = []
        if account.open_position_count >= self.configuration.maximum_open_positions:
            reasons.append(RiskReasonCode.MAX_OPEN_POSITIONS_REACHED)
        if instrument_count >= self.configuration.maximum_positions_per_instrument:
            reasons.append(RiskReasonCode.MAX_INSTRUMENT_POSITIONS_REACHED)
        return reasons

    def _size_and_decide(
        self,
        candidate: TradeCandidate,
        account: AccountRiskState,
        market: MarketRiskState,
        evaluated_at: datetime,
        gates: list[GateResult],
    ) -> RiskDecision:
        assert account.account_equity is not None
        assert account.available_capital is not None
        assert account.gross_exposure is not None
        assert candidate.entry_reference is not None
        assert candidate.stop_reference is not None
        assert market.value_per_price_unit is not None
        assert market.quantity_increment is not None
        assert market.minimum_deal_size is not None

        budget = risk_budget(account.account_equity, self.configuration.risk_per_trade_fraction)
        gates.append(gate_result(RiskGate.RISK_BUDGET))
        per_unit_risk = risk_per_unit(
            candidate.entry_reference,
            candidate.stop_reference,
            market.value_per_price_unit,
        )
        if per_unit_risk <= 0:
            gates.append(gate_result(RiskGate.RAW_SIZING, RiskReasonCode.INVALID_STOP_DIRECTION))
            return self._decision(
                candidate,
                account,
                market,
                evaluated_at,
                RiskDecisionStatus.REJECTED,
                gates,
                risk_budget_value=budget,
            )
        proposed = raw_quantity(budget, per_unit_risk)
        gates.append(gate_result(RiskGate.RAW_SIZING))

        increment = compatible_increment(
            self.configuration.quantity_increment, market.quantity_increment
        )
        if increment is None:
            gates.append(
                gate_result(
                    RiskGate.QUANTITY_CONSTRAINTS,
                    RiskReasonCode.INVALID_QUANTITY_INCREMENT,
                )
            )
            return self._decision(
                candidate,
                account,
                market,
                evaluated_at,
                RiskDecisionStatus.REJECTED,
                gates,
                proposed_quantity=proposed,
                risk_budget_value=budget,
            )

        per_unit_notional = notional_per_unit(
            candidate.entry_reference, market.value_per_price_unit
        )
        instrument_current = account.instrument_exposure_for(candidate.epic)
        asset_current = account.asset_class_exposure_for(candidate.asset_class)
        assert instrument_current is not None
        assert asset_current is not None
        gross_headroom = notional_capacity(
            self.configuration.maximum_gross_exposure_fraction,
            account.account_equity,
            account.gross_exposure,
        )
        instrument_headroom = notional_capacity(
            self.configuration.maximum_instrument_exposure_fraction,
            account.account_equity,
            instrument_current,
        )
        asset_headroom = notional_capacity(
            self.configuration.maximum_asset_class_exposure_fraction,
            account.account_equity,
            asset_current,
        )
        caps = (
            proposed,
            self.configuration.maximum_approved_quantity,
            quantity_capacity(account.available_capital, per_unit_notional),
            quantity_capacity(gross_headroom, per_unit_notional),
            quantity_capacity(instrument_headroom, per_unit_notional),
            quantity_capacity(asset_headroom, per_unit_notional),
        )
        constrained = min(caps)
        approved = round_quantity_down(constrained, increment)
        minimum = max(self.configuration.minimum_approved_quantity, market.minimum_deal_size)
        quantity_reasons: list[RiskReasonCode] = []
        if approved < minimum:
            quantity_reasons.append(RiskReasonCode.SIZE_BELOW_MINIMUM)
            minimum_notional = minimum * per_unit_notional
            if account.available_capital < minimum_notional:
                quantity_reasons.append(RiskReasonCode.INSUFFICIENT_AVAILABLE_CAPITAL)
            if gross_headroom < minimum_notional:
                quantity_reasons.append(RiskReasonCode.GROSS_EXPOSURE_LIMIT)
            if instrument_headroom < minimum_notional:
                quantity_reasons.append(RiskReasonCode.INSTRUMENT_EXPOSURE_LIMIT)
            if asset_headroom < minimum_notional:
                quantity_reasons.append(RiskReasonCode.ASSET_CLASS_EXPOSURE_LIMIT)
        if approved > self.configuration.maximum_approved_quantity:
            quantity_reasons.append(RiskReasonCode.SIZE_ABOVE_MAXIMUM)
        gates.append(gate_result(RiskGate.QUANTITY_CONSTRAINTS, *quantity_reasons))
        if quantity_reasons:
            return self._decision(
                candidate,
                account,
                market,
                evaluated_at,
                RiskDecisionStatus.REJECTED,
                gates,
                proposed_quantity=proposed,
                risk_budget_value=budget,
            )

        trade_notional = approved * per_unit_notional
        exposure_reasons: list[RiskReasonCode] = []
        if (
            projected_exposure(account.gross_exposure, trade_notional)
            > self.configuration.maximum_gross_exposure_fraction * account.account_equity
        ):
            exposure_reasons.append(RiskReasonCode.GROSS_EXPOSURE_LIMIT)
        if (
            projected_exposure(instrument_current, trade_notional)
            > self.configuration.maximum_instrument_exposure_fraction * account.account_equity
        ):
            exposure_reasons.append(RiskReasonCode.INSTRUMENT_EXPOSURE_LIMIT)
        if (
            projected_exposure(asset_current, trade_notional)
            > self.configuration.maximum_asset_class_exposure_fraction * account.account_equity
        ):
            exposure_reasons.append(RiskReasonCode.ASSET_CLASS_EXPOSURE_LIMIT)
        gates.append(gate_result(RiskGate.EXPOSURE, *exposure_reasons))
        if exposure_reasons:
            return self._decision(
                candidate,
                account,
                market,
                evaluated_at,
                RiskDecisionStatus.REJECTED,
                gates,
                proposed_quantity=proposed,
                risk_budget_value=budget,
            )

        final_risk = approved * per_unit_risk
        final_fraction = final_risk / account.account_equity
        final_reasons: list[RiskReasonCode] = []
        if final_risk > budget or final_fraction > self.configuration.risk_per_trade_fraction:
            final_reasons.append(RiskReasonCode.SIZE_ABOVE_MAXIMUM)
        if trade_notional > account.available_capital:
            final_reasons.append(RiskReasonCode.INSUFFICIENT_AVAILABLE_CAPITAL)
        gates.append(gate_result(RiskGate.FINAL_RISK, *final_reasons))
        if final_reasons:
            return self._decision(
                candidate,
                account,
                market,
                evaluated_at,
                RiskDecisionStatus.REJECTED,
                gates,
                proposed_quantity=proposed,
                risk_budget_value=budget,
            )
        return self._decision(
            candidate,
            account,
            market,
            evaluated_at,
            RiskDecisionStatus.APPROVED,
            gates,
            proposed_quantity=proposed,
            approved_quantity=approved,
            risk_budget_value=budget,
            risk_amount=final_risk,
            risk_fraction=final_fraction,
            notional_exposure=trade_notional,
        )

    def _decision(
        self,
        candidate: TradeCandidate,
        account: AccountRiskState,
        market: MarketRiskState,
        evaluated_at: datetime,
        status: RiskDecisionStatus,
        gates: list[GateResult],
        *,
        proposed_quantity: Decimal | None = None,
        approved_quantity: Decimal | None = None,
        risk_budget_value: Decimal | None = None,
        risk_amount: Decimal | None = None,
        risk_fraction: Decimal | None = None,
        notional_exposure: Decimal | None = None,
    ) -> RiskDecision:
        reasons = tuple(dict.fromkeys(reason for result in gates for reason in result.reason_codes))
        passed = tuple(result.gate for result in gates if result.passed)
        failed = tuple(result.gate for result in gates if not result.passed)
        decision_id = self._decision_id(candidate, account, market, evaluated_at)
        intent = None
        if status is RiskDecisionStatus.APPROVED:
            assert approved_quantity is not None
            assert candidate.entry_reference is not None
            assert candidate.stop_reference is not None
            assert risk_amount is not None
            assert notional_exposure is not None
            intent = ApprovedTradeIntent(
                risk_decision_id=decision_id,
                candidate_id=candidate.candidate_id,
                instrument=candidate.instrument,
                epic=candidate.epic,
                direction=candidate.direction,
                approved_quantity=approved_quantity,
                entry_reference=candidate.entry_reference,
                stop_reference=candidate.stop_reference,
                target_reference=candidate.target_reference,
                risk_amount=risk_amount,
                notional_exposure=notional_exposure,
                approval_timestamp=evaluated_at,
                expiry_timestamp=candidate.candidate_expiry,
                strategy_configuration_fingerprint=candidate.strategy_configuration_fingerprint,
                risk_configuration_fingerprint=self.configuration.fingerprint,
                account_snapshot_id=account.snapshot_id,
                market_snapshot_id=market.snapshot_id,
            )
        fields = {
            "decision_id": decision_id,
            "candidate_id": candidate.candidate_id,
            "signal_id": candidate.signal_id,
            "decision_timestamp": evaluated_at,
            "status": status,
            "proposed_quantity": proposed_quantity,
            "approved_quantity": approved_quantity,
            "approved_entry_reference": (
                candidate.entry_reference if status is RiskDecisionStatus.APPROVED else None
            ),
            "approved_stop_reference": (
                candidate.stop_reference if status is RiskDecisionStatus.APPROVED else None
            ),
            "approved_target_reference": (
                candidate.target_reference if status is RiskDecisionStatus.APPROVED else None
            ),
            "risk_budget": risk_budget_value,
            "risk_amount": risk_amount,
            "risk_fraction": risk_fraction,
            "notional_exposure": notional_exposure,
            "daily_loss_policy": self.daily_loss_policy,
            "passed_gates": passed,
            "failed_gates": failed,
            "gate_results": tuple(gates),
            "reason_codes": reasons,
            "candidate_expiry": candidate.candidate_expiry,
            "strategy_configuration_fingerprint": candidate.strategy_configuration_fingerprint,
            "risk_configuration_fingerprint": self.configuration.fingerprint,
            "account_snapshot_id": account.snapshot_id,
            "market_snapshot_id": market.snapshot_id,
            "approved_intent": intent,
        }
        return RiskDecision.model_validate({**fields, "decision_fingerprint": fingerprint(fields)})

    def _decision_id(
        self,
        candidate: TradeCandidate,
        account: AccountRiskState,
        market: MarketRiskState,
        evaluated_at: datetime,
    ) -> str:
        payload = {
            "candidate": candidate,
            "account": account,
            "market": market,
            "risk_configuration": self.configuration,
            "evaluation_timestamp": evaluated_at,
        }
        try:
            return fingerprint(payload)
        except (TypeError, ValueError):
            return fingerprint(
                {
                    "candidate_id": candidate.candidate_id,
                    "signal_id": candidate.signal_id,
                    "account_snapshot_id": account.snapshot_id,
                    "market_snapshot_id": market.snapshot_id,
                    "risk_configuration_fingerprint": self.configuration.fingerprint,
                    "evaluation_timestamp": evaluated_at,
                    "invalid_input": True,
                }
            )

    @property
    def daily_loss_policy(self) -> DailyLossPolicy:
        if self.configuration.include_unrealized_in_daily_loss:
            return DailyLossPolicy.REALIZED_AND_UNREALIZED
        return DailyLossPolicy.REALIZED_ONLY
