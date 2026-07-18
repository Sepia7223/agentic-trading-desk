"""Reporting-only 30-day Demo campaign state and safety halt calculation."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from trading_desk.ig.models import Account
from trading_desk.opportunity.config import DemoCampaignConfiguration
from trading_desk.opportunity.fingerprints import fingerprint
from trading_desk.opportunity.ledger import DemoTradeLedger, DemoTradeRecord, DemoTradeStatus


class DemoCampaignSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    campaign_id: str
    campaign_name: str
    status: str
    snapshot_at: datetime
    started_at: datetime
    planned_end_at: datetime
    account_currency: str = Field(pattern=r"^(?:[A-Z]{3}|UNKNOWN)$")
    starting_balance: Decimal
    starting_equity: Decimal
    current_balance: Decimal
    current_equity: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    return_percent: Decimal
    maximum_equity: Decimal
    daily_pnl: Decimal
    weekly_drawdown: Decimal
    maximum_drawdown: Decimal
    consecutive_losses: int = Field(ge=0)
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
    execution_incidents: int = Field(ge=0)
    reconciliation_incidents: int = Field(ge=0)
    system_halts: int = Field(ge=0)
    uptime_percent: Decimal = Field(ge=0, le=100)
    entry_halted: bool
    halt_reasons: tuple[str, ...]
    stretch_objective_progress_percent: Decimal
    configuration_fingerprints: tuple[str, ...]
    last_updated_at: datetime
    snapshot_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("snapshot_at", "started_at", "planned_end_at", "last_updated_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("campaign timestamp must be UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def identity(self, info: ValidationInfo) -> Self:
        if isinstance(info.context, dict) and info.context.get("legacy_currency_migration") is True:
            return self
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
    starting_balance: Decimal | None = None,
    starting_equity: Decimal | None = None,
    account_currency: str = "UNKNOWN",
    status: str = "ACTIVE",
    submitted_trade_count: int | None = None,
) -> DemoCampaignSnapshot:
    config = configuration or DemoCampaignConfiguration()
    start = starting_balance or config.starting_balance_reference
    equity_start = starting_equity or start
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
        "status": status,
        "snapshot_at": observed_at,
        "started_at": started_at,
        "planned_end_at": started_at + timedelta(days=config.duration_days),
        "account_currency": account_currency,
        "starting_balance": start,
        "starting_equity": equity_start,
        "current_balance": current_balance,
        "current_equity": current_equity,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "return_percent": return_percent,
        "maximum_equity": maximum_equity,
        "daily_pnl": daily_pnl,
        "weekly_drawdown": weekly_drawdown_percent,
        "maximum_drawdown": drawdown,
        "consecutive_losses": consecutive_losses,
        "trade_count": submitted_trade_count
        if submitted_trade_count is not None
        else len(trade_pnls),
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
        "execution_incidents": execution_rejections,
        "reconciliation_incidents": reconciliation_incidents,
        "system_halts": system_halts,
        "uptime_percent": uptime_percent,
        "entry_halted": bool(reasons),
        "halt_reasons": tuple(reasons),
        "stretch_objective_progress_percent": return_percent
        / config.stretch_return_target_percent
        * Decimal("100"),
        "configuration_fingerprints": (config.configuration_fingerprint,),
        "last_updated_at": observed_at,
    }
    return DemoCampaignSnapshot.model_validate(
        {**fields, "snapshot_fingerprint": fingerprint(fields)}
    )


class DemoCampaignStateStore:
    """Atomic durable campaign state; a halt survives process restart."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def exists(self) -> bool:
        return self.path.is_file()

    def load(self) -> DemoCampaignSnapshot:
        if not self.path.is_file():
            raise ValueError("no persisted Demo campaign exists")
        try:
            fields = json.loads(self.path.read_text(encoding="utf-8"))
            if "account_currency" not in fields:
                fields["account_currency"] = "UNKNOWN"
                migrated = DemoCampaignSnapshot.model_validate(
                    fields, context={"legacy_currency_migration": True}
                )
                identity_fields = migrated.model_dump(
                    mode="python", exclude={"snapshot_fingerprint"}
                )
                fields = {**identity_fields, "snapshot_fingerprint": fingerprint(identity_fields)}
            return DemoCampaignSnapshot.model_validate(fields)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            raise ValueError("persisted Demo campaign state is invalid") from None

    def save(self, snapshot: DemoCampaignSnapshot) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(self.path)


class ReadOnlyCampaignAccountSource(Protocol):
    async def get_accounts(self) -> tuple[Account, ...]: ...


class DemoCampaignService:
    def __init__(
        self,
        accounts: ReadOnlyCampaignAccountSource,
        store: DemoCampaignStateStore,
        configuration: DemoCampaignConfiguration,
        *,
        journal=None,  # type: ignore[no-untyped-def]
        ledger: DemoTradeLedger | None = None,
    ) -> None:
        self.accounts = accounts
        self.store = store
        self.configuration = configuration
        self.journal = journal
        self.ledger = ledger

    def load(self) -> DemoCampaignSnapshot:
        return self.store.load()

    def save(self, snapshot: DemoCampaignSnapshot) -> None:
        self.store.save(snapshot)

    async def refresh_runtime(self, observed_at: datetime) -> DemoCampaignSnapshot:
        if self.ledger is None:
            raise ValueError("campaign runtime requires the durable Demo trade ledger")
        return await self.refresh(observed_at, self.ledger.load().records)

    async def start(
        self, campaign_id: str, campaign_name: str, started_at: datetime
    ) -> DemoCampaignSnapshot:
        if not self.configuration.enabled:
            raise ValueError("Demo campaign configuration is disabled")
        if self.store.exists() and self.store.load().status == "ACTIVE":
            raise ValueError("an active Demo campaign already exists")
        account = _preferred(await self.accounts.get_accounts())
        equity = account.balance.balance + account.balance.profit_loss
        snapshot = campaign_snapshot(
            campaign_id=campaign_id,
            campaign_name=campaign_name,
            started_at=started_at,
            observed_at=started_at,
            current_balance=account.balance.balance,
            current_equity=equity,
            maximum_equity=equity,
            daily_pnl=Decimal("0"),
            weekly_drawdown_percent=Decimal("0"),
            consecutive_losses=0,
            configuration=self.configuration,
            starting_balance=account.balance.balance,
            starting_equity=equity,
            account_currency=account.currency,
        )
        self.store.save(snapshot)
        if self.journal is not None:
            self.journal.append_campaign_started(snapshot)
        return snapshot

    async def refresh(
        self,
        observed_at: datetime,
        records: tuple[DemoTradeRecord, ...],
    ) -> DemoCampaignSnapshot:
        previous = self.store.load()
        account = _preferred(await self.accounts.get_accounts())
        equity = account.balance.balance + account.balance.profit_loss
        closed = tuple(
            item
            for item in records
            if item.status is DemoTradeStatus.CLOSED and item.realized_pnl is not None
        )
        today = observed_at.date()
        week_start = today - timedelta(days=today.weekday())
        daily = sum(
            (item.realized_pnl or Decimal("0") for item in closed if item.trading_date == today),
            Decimal("0"),
        )
        weekly_pnl = sum(
            (
                item.realized_pnl or Decimal("0")
                for item in closed
                if week_start <= item.trading_date <= today
            ),
            Decimal("0"),
        )
        weekly_drawdown = (
            max(Decimal("0"), -weekly_pnl / previous.starting_balance * Decimal("100"))
            if previous.starting_balance > 0
            else Decimal("0")
        )
        consecutive_losses = 0
        for item in reversed(closed):
            if item.realized_pnl is not None and item.realized_pnl < 0:
                consecutive_losses += 1
            else:
                break
        snapshot = campaign_snapshot(
            campaign_id=previous.campaign_id,
            campaign_name=previous.campaign_name,
            started_at=previous.started_at,
            observed_at=observed_at,
            current_balance=account.balance.balance,
            current_equity=equity,
            maximum_equity=max(previous.maximum_equity, equity),
            daily_pnl=daily,
            weekly_drawdown_percent=weekly_drawdown,
            consecutive_losses=consecutive_losses,
            trade_pnls=tuple(item.realized_pnl for item in closed if item.realized_pnl is not None),
            submitted_trade_count=sum(
                1 for item in records if item.status is DemoTradeStatus.SUBMITTED
            ),
            estimated_costs=sum((item.estimated_cost for item in records), Decimal("0")),
            realized_costs=sum((item.observed_cost for item in records), Decimal("0")),
            execution_rejections=previous.execution_incidents,
            reconciliation_incidents=previous.reconciliation_incidents,
            system_halts=previous.system_halts,
            uptime_percent=previous.uptime_percent,
            configuration=self.configuration,
            starting_balance=previous.starting_balance,
            starting_equity=previous.starting_equity,
            account_currency=account.currency,
            status=previous.status,
        )
        if previous.entry_halted and not snapshot.entry_halted:
            snapshot = snapshot.model_copy(
                update={
                    "entry_halted": True,
                    "halt_reasons": previous.halt_reasons,
                }
            )
            fields = snapshot.model_dump(mode="python", exclude={"snapshot_fingerprint"})
            snapshot = DemoCampaignSnapshot.model_validate(
                {**fields, "snapshot_fingerprint": fingerprint(fields)}
            )
        elif snapshot.entry_halted and not previous.entry_halted:
            fields = snapshot.model_dump(mode="python", exclude={"snapshot_fingerprint"})
            fields.update(status="HALTED", system_halts=previous.system_halts + 1)
            snapshot = DemoCampaignSnapshot.model_validate(
                {**fields, "snapshot_fingerprint": fingerprint(fields)}
            )
        self.store.save(snapshot)
        if self.journal is not None:
            self.journal.append_campaign(snapshot)
        return snapshot


class DemoCampaignReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    account_currency: str = Field(pattern=r"^(?:[A-Z]{3}|UNKNOWN)$")
    starting_balance: Decimal
    current_balance: Decimal
    current_equity: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    return_percent: Decimal
    maximum_drawdown_percent: Decimal
    trade_count: int
    closed_trades: int
    wins: int
    losses: int
    win_rate: Decimal | None
    expectancy: Decimal | None
    profit_factor: Decimal | None
    average_win: Decimal | None
    average_loss: Decimal | None
    largest_win: Decimal | None
    largest_loss: Decimal | None
    average_holding_period_seconds: Decimal | None
    strategy_breakdown: tuple[tuple[str, Decimal], ...]
    instrument_breakdown: tuple[tuple[str, Decimal], ...]
    timeframe_breakdown: tuple[tuple[str, Decimal], ...]
    regime_breakdown: tuple[tuple[str, Decimal], ...]
    session_breakdown: tuple[tuple[str, Decimal], ...]
    estimated_costs: Decimal
    observed_costs: Decimal
    execution_incidents: int
    reconciliation_incidents: int
    system_halts: int
    uptime_percent: Decimal
    entry_halted: bool
    halt_reasons: tuple[str, ...]
    report_fingerprint: str = Field(min_length=64, max_length=64)


def campaign_report(
    snapshot: DemoCampaignSnapshot,
    records: tuple[DemoTradeRecord, ...],
) -> DemoCampaignReport:
    submitted = tuple(item for item in records if item.status is DemoTradeStatus.SUBMITTED)
    closed = tuple(
        item
        for item in records
        if item.status is DemoTradeStatus.CLOSED and item.realized_pnl is not None
    )
    pnls = tuple(item.realized_pnl for item in closed if item.realized_pnl is not None)
    wins = tuple(item for item in pnls if item > 0)
    losses = tuple(item for item in pnls if item < 0)
    holding = tuple(
        item.holding_period_seconds for item in closed if item.holding_period_seconds is not None
    )
    fields = {
        "account_currency": snapshot.account_currency,
        "starting_balance": snapshot.starting_balance,
        "current_balance": snapshot.current_balance,
        "current_equity": snapshot.current_equity,
        "realized_pnl": snapshot.realized_pnl,
        "unrealized_pnl": snapshot.unrealized_pnl,
        "return_percent": snapshot.return_percent,
        "maximum_drawdown_percent": snapshot.maximum_drawdown,
        "trade_count": len(submitted),
        "closed_trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": Decimal(len(wins)) / Decimal(len(closed)) if closed else None,
        "expectancy": sum(pnls, Decimal("0")) / Decimal(len(pnls)) if pnls else None,
        "profit_factor": (
            sum(wins, Decimal("0")) / abs(sum(losses, Decimal("0"))) if losses else None
        ),
        "average_win": sum(wins, Decimal("0")) / Decimal(len(wins)) if wins else None,
        "average_loss": (sum(losses, Decimal("0")) / Decimal(len(losses)) if losses else None),
        "largest_win": max(wins) if wins else None,
        "largest_loss": min(losses) if losses else None,
        "average_holding_period_seconds": (
            sum(holding, Decimal("0")) / Decimal(len(holding)) if holding else None
        ),
        "strategy_breakdown": _breakdown(closed, "strategy"),
        "instrument_breakdown": _breakdown(closed, "instrument"),
        "timeframe_breakdown": _breakdown(closed, "timeframe"),
        "regime_breakdown": _breakdown(closed, "regime"),
        "session_breakdown": _breakdown(closed, "session"),
        "estimated_costs": sum((item.estimated_cost for item in records), Decimal("0")),
        "observed_costs": sum((item.observed_cost for item in records), Decimal("0")),
        "execution_incidents": snapshot.execution_incidents,
        "reconciliation_incidents": snapshot.reconciliation_incidents,
        "system_halts": snapshot.system_halts,
        "uptime_percent": snapshot.uptime_percent,
        "entry_halted": snapshot.entry_halted,
        "halt_reasons": snapshot.halt_reasons,
    }
    return DemoCampaignReport.model_validate({**fields, "report_fingerprint": fingerprint(fields)})


def halt_campaign(
    snapshot: DemoCampaignSnapshot,
    observed_at: datetime,
    reason: str,
    *,
    execution_incident: bool = False,
    reconciliation_incident: bool = False,
) -> DemoCampaignSnapshot:
    fields = snapshot.model_dump(mode="python", exclude={"snapshot_fingerprint"})
    fields.update(
        status="HALTED",
        snapshot_at=observed_at,
        last_updated_at=observed_at,
        entry_halted=True,
        halt_reasons=tuple(dict.fromkeys((*snapshot.halt_reasons, reason))),
        system_halts=snapshot.system_halts + 1,
        execution_incidents=snapshot.execution_incidents + int(execution_incident),
        execution_rejections=snapshot.execution_rejections + int(execution_incident),
        reconciliation_incidents=(snapshot.reconciliation_incidents + int(reconciliation_incident)),
    )
    return DemoCampaignSnapshot.model_validate(
        {**fields, "snapshot_fingerprint": fingerprint(fields)}
    )


def _breakdown(records: tuple[DemoTradeRecord, ...], field: str) -> tuple[tuple[str, Decimal], ...]:
    totals: dict[str, Decimal] = {}
    for record in records:
        label = str(getattr(record, field))
        totals[label] = totals.get(label, Decimal("0")) + (record.realized_pnl or Decimal("0"))
    return tuple(sorted(totals.items()))


def _preferred(accounts: tuple[Account, ...]) -> Account:
    preferred = tuple(item for item in accounts if item.preferred)
    if len(preferred) != 1:
        raise ValueError("exactly one preferred Demo account is required")
    return preferred[0]
