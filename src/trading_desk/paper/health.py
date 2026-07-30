"""Producers for the pipeline's SystemHealth and AccountState snapshots.

Assembled from real observables: market-data freshness (age of the latest
bar), the file-based kill switches, restart-reconciliation status, and the
paper account's own arithmetic (equity, daily loss, drawdown, trade counts,
stress-based open risk). Pure functions of their inputs — the session layer
gathers the inputs, so these stay unit-testable.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from trading_desk.paper.state import (
    GLOBAL_KILL_FILE,
    INCIDENT_LOCK_FILE,
    STRATEGY_KILL_FILE,
    PaperState,
    kill_switch_active,
)
from trading_desk.pretrade.models import AccountState, SystemHealth
from trading_desk.pretrade.stress import PortfolioSnapshot, compute_stress_report


def market_data_current(
    latest_bar_date: date | None, today: date, max_staleness_days: int = 4
) -> bool:
    """Fresh if the newest bar is within a long weekend of today."""

    if latest_bar_date is None:
        return False
    return today - latest_bar_date <= timedelta(days=max_staleness_days)


def build_system_health(
    root: Path,
    *,
    latest_bar_date: date | None,
    today: date,
    reconciled: bool,
    protective_orders_ok: bool = True,
) -> SystemHealth:
    return SystemHealth(
        market_data_current=market_data_current(latest_bar_date, today),
        broker_connected=True,  # the paper broker is in-process
        account_data_reconciled=reconciled,
        positions_reconciled=reconciled,
        clock_synchronized=True,
        strategy_enabled=not kill_switch_active(root, STRATEGY_KILL_FILE),
        kill_switch_inactive=not kill_switch_active(root, GLOBAL_KILL_FILE),
        strategy_kill_switch_inactive=not kill_switch_active(root, STRATEGY_KILL_FILE),
        incident_lock_active=kill_switch_active(root, INCIDENT_LOCK_FILE),
        protective_orders_submittable=protective_orders_ok,
    )


def build_account_state(
    state: PaperState,
    equity: Decimal,
    *,
    gross_exposure: Decimal,
    net_exposure: Decimal,
    max_single_name_weight: Decimal,
    max_short_name_weight: Decimal,
) -> AccountState:
    """Open risk = the netted stress number for the CURRENT book (the
    reconciled portfolio-level risk semantics)."""

    stress = compute_stress_report(
        PortfolioSnapshot(
            gross_exposure=gross_exposure,
            net_exposure=net_exposure,
            max_single_name_weight=max_single_name_weight,
            max_short_name_weight=max_short_name_weight,
        )
    )
    return AccountState(
        equity=equity,
        daily_loss_fraction=state.daily_loss_fraction(equity),
        current_drawdown_fraction=state.drawdown_fraction(equity),
        daily_trade_count=state.trades_today,
        consecutive_losses=state.consecutive_losses,
        open_risk_fraction=stress.worst(),
    )
