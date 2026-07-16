"""Portfolio valuation, snapshots, and Milestone 4 risk-state projection."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from trading_desk.portfolio.config import PaperPortfolioConfiguration
from trading_desk.portfolio.fingerprints import fingerprint
from trading_desk.portfolio.models import (
    DailyAccounting,
    PaperPosition,
    PortfolioState,
    PositionStatus,
)
from trading_desk.risk.models import AccountRiskState, ExposureAmount, PositionCount

ZERO = Decimal("0")


def build_state(
    *,
    portfolio_id: str,
    timestamp: datetime,
    initial_cash: Decimal,
    cash: Decimal,
    realized_pnl: Decimal,
    positions: tuple[PaperPosition, ...],
    daily: DailyAccounting,
    ledger_sequence: int,
    configuration: PaperPortfolioConfiguration,
) -> PortfolioState:
    open_positions = tuple(item for item in positions if item.status is PositionStatus.OPEN)
    unrealized = sum((item.net_unrealized_pnl for item in open_positions), ZERO)
    gross_exposure = sum((abs(item.current_exposure) for item in open_positions), ZERO)
    net_exposure = sum((item.current_exposure for item in open_positions), ZERO)
    open_risk = sum((item.open_risk_amount for item in open_positions), ZERO)
    equity = cash + unrealized
    base = {
        "portfolio_id": portfolio_id,
        "timestamp": timestamp,
        "base_currency": configuration.base_currency,
        "initial_cash": initial_cash,
        "cash": cash,
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized,
        "equity": equity,
        "gross_exposure": gross_exposure,
        "net_exposure": net_exposure,
        "open_risk_amount": open_risk,
        "open_position_count": len(open_positions),
        "positions": positions,
        "daily": daily,
        "ledger_sequence": ledger_sequence,
        "configuration_fingerprint": configuration.fingerprint,
    }
    state_fingerprint = fingerprint(base)
    return PortfolioState.model_validate(
        {**base, "snapshot_id": state_fingerprint, "state_fingerprint": state_fingerprint}
    )


def account_risk_state(
    state: PortfolioState,
    *,
    kill_switch_active: bool = False,
    required_epics: tuple[str, ...] = (),
    required_asset_classes: tuple[str, ...] = (),
) -> AccountRiskState:
    open_positions = tuple(item for item in state.positions if item.status is PositionStatus.OPEN)
    instruments = sorted({item.epic for item in open_positions} | set(required_epics))
    asset_classes = sorted(
        {item.asset_class.value for item in open_positions} | set(required_asset_classes)
    )
    instrument_exposure = tuple(
        ExposureAmount(
            key=epic,
            amount=sum(
                (item.current_exposure for item in open_positions if item.epic == epic), ZERO
            ),
        )
        for epic in instruments
    )
    asset_class_exposure = tuple(
        ExposureAmount(
            key=name,
            amount=sum(
                (
                    item.current_exposure
                    for item in open_positions
                    if item.asset_class.value == name
                ),
                ZERO,
            ),
        )
        for name in asset_classes
    )
    counts = tuple(
        PositionCount(key=epic, count=sum(item.epic == epic for item in open_positions))
        for epic in instruments
    )
    drawdown = (
        (state.daily.peak_equity - state.equity) / state.daily.peak_equity
        if state.daily.peak_equity > ZERO and state.equity < state.daily.peak_equity
        else ZERO
    )
    return AccountRiskState(
        snapshot_id=state.snapshot_id,
        timestamp=state.timestamp,
        account_equity=state.equity,
        available_capital=max(state.cash - state.gross_exposure, ZERO),
        realized_daily_pnl=state.daily.realized_daily_pnl,
        unrealized_pnl=state.unrealized_pnl,
        current_drawdown_fraction=drawdown,
        gross_exposure=state.gross_exposure,
        open_risk_amount=state.open_risk_amount,
        open_position_count=state.open_position_count,
        instrument_exposure=instrument_exposure,
        asset_class_exposure=asset_class_exposure,
        instrument_position_count=counts,
        consecutive_losses=state.daily.consecutive_losses,
        kill_switch_active=kill_switch_active,
        state_complete=True,
    )
