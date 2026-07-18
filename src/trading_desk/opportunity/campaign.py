"""Reporting-only 30-day Demo campaign state and safety halt calculation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.opportunity.config import DemoCampaignConfiguration
from trading_desk.opportunity.fingerprints import fingerprint


class DemoCampaignSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    campaign_id: str
    campaign_name: str
    snapshot_at: datetime
    started_at: datetime
    planned_end_at: datetime
    starting_balance: Decimal
    current_balance: Decimal
    current_equity: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    return_percent: Decimal
    maximum_equity: Decimal
    maximum_drawdown: Decimal
    trade_count: int = Field(ge=0)
    closed_trade_count: int = Field(ge=0)
    winning_trade_count: int = Field(ge=0)
    losing_trade_count: int = Field(ge=0)
    win_rate: Decimal | None
    profit_factor: Decimal | None
    expectancy: Decimal | None
    average_win: Decimal | None
    average_loss: Decimal | None
    largest_win: Decimal | None
    largest_loss: Decimal | None
    average_holding_period_seconds: Decimal | None
    estimated_costs: Decimal = Field(ge=0)
    realized_costs: Decimal = Field(ge=0)
    strategy_breakdown: tuple[tuple[str, Decimal], ...] = ()
    instrument_breakdown: tuple[tuple[str, Decimal], ...] = ()
    timeframe_breakdown: tuple[tuple[str, Decimal], ...] = ()
    regime_breakdown: tuple[tuple[str, Decimal], ...] = ()
    session_breakdown: tuple[tuple[str, Decimal], ...] = ()
    execution_rejections: int = Field(ge=0)
    reconciliation_incidents: int = Field(ge=0)
    system_halts: int = Field(ge=0)
    uptime_percent: Decimal = Field(ge=0, le=100)
    entry_halted: bool
    halt_reasons: tuple[str, ...]
    stretch_objective_progress_percent: Decimal
    configuration_fingerprints: tuple[str, ...]
    snapshot_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("snapshot_at", "started_at", "planned_end_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("campaign timestamp must be UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def identity(self) -> Self:
        expected = fingerprint(self.model_dump(mode="python", exclude={"snapshot_fingerprint"}))
        if self.snapshot_fingerprint != expected:
            raise ValueError("campaign snapshot fingerprint mismatch")
        return self


def campaign_snapshot(
    *,
    campaign_id: str,
    campaign_name: str,
    started_at: datetime,
    observed_at: datetime,
    current_balance: Decimal,
    current_equity: Decimal,
    maximum_equity: Decimal,
    daily_pnl: Decimal,
    weekly_drawdown_percent: Decimal,
    consecutive_losses: int,
    trade_pnls: tuple[Decimal, ...] = (),
    estimated_costs: Decimal = Decimal("0"),
    realized_costs: Decimal = Decimal("0"),
    execution_rejections: int = 0,
    reconciliation_incidents: int = 0,
    system_halts: int = 0,
    uptime_percent: Decimal = Decimal("100"),
    configuration: DemoCampaignConfiguration | None = None,
) -> DemoCampaignSnapshot:
    config = configuration or DemoCampaignConfiguration()
    start = config.starting_balance_reference
    realized = current_balance - start
    unrealized = current_equity - current_balance
    return_percent = (current_equity - start) / start * Decimal("100")
    drawdown = (
        (maximum_equity - current_equity) / maximum_equity * Decimal("100")
        if maximum_equity > 0
        else Decimal("0")
    )
    wins = tuple(item for item in trade_pnls if item > 0)
    losses = tuple(item for item in trade_pnls if item < 0)
    reasons: list[str] = []
    if daily_pnl <= -(start * config.maximum_daily_loss_percent / Decimal("100")):
        reasons.append("MAXIMUM_DAILY_LOSS")
    if weekly_drawdown_percent >= config.maximum_weekly_drawdown_percent:
        reasons.append("MAXIMUM_WEEKLY_DRAWDOWN")
    if drawdown >= config.maximum_campaign_drawdown_percent:
        reasons.append("MAXIMUM_CAMPAIGN_DRAWDOWN")
    if consecutive_losses >= config.maximum_consecutive_losses:
        reasons.append("MAXIMUM_CONSECUTIVE_LOSSES")
    if execution_rejections > config.maximum_execution_incidents:
        reasons.append("MAXIMUM_EXECUTION_INCIDENTS")
    if reconciliation_incidents > config.maximum_reconciliation_incidents:
        reasons.append("MAXIMUM_RECONCILIATION_INCIDENTS")
    fields = {
        "campaign_id": campaign_id,
        "campaign_name": campaign_name,
        "snapshot_at": observed_at,
        "started_at": started_at,
        "planned_end_at": started_at + timedelta(days=config.duration_days),
        "starting_balance": start,
        "current_balance": current_balance,
        "current_equity": current_equity,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "return_percent": return_percent,
        "maximum_equity": maximum_equity,
        "maximum_drawdown": drawdown,
        "trade_count": len(trade_pnls),
        "closed_trade_count": len(trade_pnls),
        "winning_trade_count": len(wins),
        "losing_trade_count": len(losses),
        "win_rate": Decimal(len(wins)) / Decimal(len(trade_pnls)) if trade_pnls else None,
        "profit_factor": (
            sum(wins, Decimal("0")) / abs(sum(losses, Decimal("0"))) if losses else None
        ),
        "expectancy": (
            sum(trade_pnls, Decimal("0")) / Decimal(len(trade_pnls)) if trade_pnls else None
        ),
        "average_win": sum(wins, Decimal("0")) / Decimal(len(wins)) if wins else None,
        "average_loss": sum(losses, Decimal("0")) / Decimal(len(losses)) if losses else None,
        "largest_win": max(wins) if wins else None,
        "largest_loss": min(losses) if losses else None,
        "average_holding_period_seconds": None,
        "estimated_costs": estimated_costs,
        "realized_costs": realized_costs,
        "strategy_breakdown": (),
        "instrument_breakdown": (),
        "timeframe_breakdown": (),
        "regime_breakdown": (),
        "session_breakdown": (),
        "execution_rejections": execution_rejections,
        "reconciliation_incidents": reconciliation_incidents,
        "system_halts": system_halts,
        "uptime_percent": uptime_percent,
        "entry_halted": bool(reasons),
        "halt_reasons": tuple(reasons),
        "stretch_objective_progress_percent": return_percent
        / config.stretch_return_target_percent
        * Decimal("100"),
        "configuration_fingerprints": (config.configuration_fingerprint,),
    }
    return DemoCampaignSnapshot.model_validate(
        {**fields, "snapshot_fingerprint": fingerprint(fields)}
    )
