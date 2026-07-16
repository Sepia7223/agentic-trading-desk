"""Read-only conversion of deterministic domain records into sanitizer inputs."""

from __future__ import annotations

from decimal import Decimal

from trading_desk.portfolio.models import ClosedTradeRecord, PortfolioState
from trading_desk.risk.models import RiskDecision
from trading_desk.strategy.models import TradeCandidate


def strategy_signal_context(candidate: TradeCandidate) -> dict[str, object]:
    return {
        "instrument": candidate.instrument_name,
        "strategy_variant": candidate.strategy_variant.value,
        "signal_action": candidate.action.value,
        "signal_scores": {
            "trend": candidate.baseline_trend_score,
            "momentum": candidate.baseline_momentum_score,
            "macro": candidate.macro_score,
            "total": candidate.total_baseline_score,
        },
        "regime": candidate.current_regime.value,
        "regime_probabilities": tuple(
            {
                "regime": item.regime.value,
                "probability": _decimal(item.probability),
            }
            for item in candidate.regime_probabilities
        ),
        "kalman_state": {
            "level": _optional_decimal(candidate.kalman_level),
            "slope": _optional_decimal(candidate.kalman_slope),
            "slope_uncertainty": _optional_decimal(candidate.kalman_slope_uncertainty),
            "normalized_price_deviation": _optional_decimal(candidate.normalized_price_deviation),
        },
        "gate_results": tuple(
            f"{item.name}:{'PASS' if item.passed else 'FAIL'}" for item in candidate.mandatory_gates
        ),
    }


def risk_decision_context(decision: RiskDecision, instrument: str) -> dict[str, object]:
    return {
        "instrument": instrument,
        "risk_status": decision.status.value,
        "risk_reason_codes": tuple(item.value for item in decision.reason_codes),
        "approved_quantity": decision.approved_quantity,
        "entry_price": decision.approved_entry_reference,
        "gate_results": tuple(
            f"{item.gate.value}:{'PASS' if item.passed else 'FAIL'}"
            for item in decision.gate_results
        ),
    }


def closed_trade_context(trade: ClosedTradeRecord) -> dict[str, object]:
    costs = trade.entry_commission + trade.exit_commission + trade.funding + trade.slippage_cost
    return {
        "instrument": trade.instrument,
        "entry_price": trade.entry_price,
        "exit_price": trade.exit_price,
        "gross_pnl": trade.gross_pnl,
        "net_pnl": trade.net_pnl,
        "costs": costs,
        "holding_period_seconds": Decimal(str(trade.holding_period.total_seconds())),
        "maximum_favorable_excursion": trade.maximum_favorable_excursion,
        "maximum_adverse_excursion": trade.maximum_adverse_excursion,
        "financial_outcome": (
            "PROFIT" if trade.net_pnl > 0 else "LOSS" if trade.net_pnl < 0 else "FLAT"
        ),
    }


def portfolio_state_context(state: PortfolioState) -> dict[str, object]:
    drawdown = (
        (state.daily.peak_equity - state.equity) / state.daily.peak_equity
        if state.daily.peak_equity > 0 and state.equity < state.daily.peak_equity
        else Decimal("0")
    )
    return {
        "portfolio_equity": state.equity,
        "drawdown": drawdown,
        "exposure": state.gross_exposure,
        "gross_pnl": state.realized_pnl,
        "net_pnl": state.unrealized_pnl,
        "review_metrics": {
            "positions_opened": len(state.positions),
            "positions_closed": sum(item.status.value == "CLOSED" for item in state.positions),
            "unresolved_positions": sum(
                item.status.value == "UNRESOLVED" for item in state.positions
            ),
            "realized_pnl": state.realized_pnl,
            "unrealized_pnl": state.unrealized_pnl,
            "costs": Decimal("0"),
        },
    }


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _optional_decimal(value: float | None) -> Decimal | None:
    return None if value is None else _decimal(value)
