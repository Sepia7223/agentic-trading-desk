"""Operational context mapping into the established Demo lifecycle authority."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol

from trading_desk.ig.models import Account, Direction, MarketStatus, OpenPosition
from trading_desk.lifecycle.config import LifecycleConfiguration
from trading_desk.lifecycle.fingerprints import fingerprint
from trading_desk.lifecycle.models import (
    CloseReconciliationStatus,
    DemoPositionSnapshot,
    LifecycleMarketStatus,
    LifecycleRiskState,
    PositionDirection,
    PositionStatus,
    StrategyExitState,
)
from trading_desk.lifecycle.monitor import PersistentPositionLifecycleMonitor
from trading_desk.opportunity.ledger import DemoTradeLedger, DemoTradeStatus


class StrategyInvalidationProvider(Protocol):
    async def evaluate(
        self, snapshot: DemoPositionSnapshot, now: datetime
    ) -> StrategyExitState: ...


class OperationalLifecycleContextProvider:
    def __init__(
        self,
        broker,  # type: ignore[no-untyped-def]
        *,
        ledger: DemoTradeLedger | None = None,
        invalidation_provider: StrategyInvalidationProvider | None = None,
    ) -> None:
        self.broker = broker
        self.ledger = ledger
        self._invalidation_provider = invalidation_provider
        self._accounts: tuple[Account, ...] = ()
        self.snapshots_by_position: dict[str, DemoPositionSnapshot] = {}

    async def snapshots(self, now: datetime) -> tuple[DemoPositionSnapshot, ...]:
        self._accounts = await self.broker.get_accounts()
        positions: tuple[OpenPosition, ...] = await self.broker.get_open_positions()
        results: list[DemoPositionSnapshot] = []
        for position in positions:
            execution_id = self._managed_execution_id(position, positions)
            if execution_id is None:
                continue
            snapshot = await self._snapshot(position, now, execution_id)
            results.append(snapshot)
            self.snapshots_by_position[snapshot.position_id] = snapshot
        return tuple(results)

    async def risk_state(self, snapshot: DemoPositionSnapshot, now: datetime) -> LifecycleRiskState:
        return LifecycleRiskState(
            account_snapshot_id=snapshot.account_snapshot_id,
            timestamp=now,
            state_complete=True,
        )

    async def strategy_exit(
        self, snapshot: DemoPositionSnapshot, now: datetime
    ) -> StrategyExitState:
        if self._invalidation_provider is None:
            return StrategyExitState.HOLD
        return await self._invalidation_provider.evaluate(snapshot, now)

    async def _snapshot(
        self,
        position: OpenPosition,
        now: datetime,
        source_execution_id: str,
    ) -> DemoPositionSnapshot:
        if position.direction is not Direction.BUY:
            raise ValueError("automatic lifecycle is long-only")
        details = await self.broker.get_market_details(position.market.epic)
        if details.bid is None or details.offer is None:
            raise ValueError("lifecycle market quote is unavailable")
        preferred = tuple(item for item in self._accounts if item.preferred)
        if len(preferred) != 1:
            raise ValueError("lifecycle requires one preferred Demo account")
        account = preferred[0]
        account_id = fingerprint(
            {"account": account.account_id, "balance": account.balance, "timestamp": now}
        )
        market_id = fingerprint({"market": details, "timestamp": now})
        pnl = (details.bid - position.opening_level) * position.size
        risk = (
            (position.opening_level - position.stop_level) * position.size
            if position.stop_level is not None
            else Decimal("0")
        )
        fields = {
            "position_id": position.deal_id,
            "deal_id": position.deal_id,
            "deal_reference": position.deal_reference,
            "instrument": position.market.instrument_name,
            "epic": position.market.epic,
            "asset_class": "FOREX",
            "direction": PositionDirection.LONG,
            "quantity": position.size,
            "entry_timestamp": position.created_at,
            "entry_level": position.opening_level,
            "current_bid": details.bid,
            "current_ask": details.offer,
            "current_mark": details.bid,
            "stop_level": position.stop_level,
            "target_level": position.limit_level,
            "unrealized_pnl": pnl,
            "accrued_costs": Decimal("0"),
            "current_exposure": position.size * details.bid,
            "current_risk": max(Decimal("0"), risk),
            "holding_duration": max(now - position.created_at, now - now),
            "market_status": _status(details.market_status),
            "position_status": PositionStatus.OPEN,
            "account_snapshot_id": account_id,
            "market_snapshot_id": market_id,
            "source_execution_id": source_execution_id,
            "strategy_id": "trend-regime-v1",
            "strategy_version": "1.0.0",
            "strategy_configuration_fingerprint": fingerprint("trend-regime-v1"),
            "risk_configuration_fingerprint": fingerprint("opportunity-risk"),
            "execution_configuration_fingerprint": fingerprint("demo-exploration"),
            "snapshot_timestamp": now,
            "market_timestamp": now,
            "account_timestamp": now,
        }
        identity = fingerprint(fields)
        return DemoPositionSnapshot.model_validate(
            {**fields, "snapshot_id": identity, "snapshot_fingerprint": identity}
        )

    def _managed_execution_id(
        self,
        position: OpenPosition,
        positions: tuple[OpenPosition, ...],
    ) -> str | None:
        if self.ledger is None:
            return fingerprint(position.deal_id)
        if (
            sum(
                item.market.instrument_name == position.market.instrument_name for item in positions
            )
            != 1
        ):
            return None
        matching = tuple(
            item.execution_id
            for item in self.ledger.load().records
            if item.status is DemoTradeStatus.CONFIRMED
            and item.instrument == position.market.instrument_name
            and item.execution_id is not None
        )
        unique = tuple(dict.fromkeys(matching))
        return unique[0] if len(unique) == 1 else None


class OperationalLifecyclePort:
    def __init__(
        self,
        monitor: PersistentPositionLifecycleMonitor,
        *,
        context_provider: OperationalLifecycleContextProvider | None = None,
        ledger: DemoTradeLedger | None = None,
    ) -> None:
        self.monitor_service = monitor
        self.context_provider = context_provider
        self.ledger = ledger

    async def monitor(self, observed_at: datetime) -> object:
        outcomes = await self.monitor_service.run_cycle(observed_at)
        if self.context_provider is not None and self.ledger is not None:
            for outcome in outcomes:
                result = outcome.result
                reconciliation = outcome.reconciliation
                snapshot = self.context_provider.snapshots_by_position.get(
                    outcome.decision.position_id
                )
                if (
                    result is None
                    or reconciliation is None
                    or snapshot is None
                    or reconciliation.status is not CloseReconciliationStatus.POSITION_CLOSED
                    or result.confirmed_exit_level is None
                    or result.confirmed_quantity is None
                ):
                    continue
                pnl = (
                    result.confirmed_exit_level - snapshot.entry_level
                ) * result.confirmed_quantity
                self.ledger.append(
                    self.ledger.create_record(
                        occurred_at=result.completed_at,
                        status=DemoTradeStatus.CLOSED,
                        strategy=snapshot.strategy_id,
                        instrument=snapshot.instrument,
                        timeframe="UNKNOWN",
                        regime="UNKNOWN",
                        session="DEMO",
                        candidate_id=snapshot.source_execution_id,
                        execution_id=result.close_result_id,
                        realized_pnl=pnl,
                        holding_period_seconds=Decimal(
                            str(snapshot.holding_duration.total_seconds())
                        ),
                    )
                )
        return outcomes


def enabled_lifecycle_configuration() -> LifecycleConfiguration:
    return LifecycleConfiguration(enabled=True, automatic_exit_enabled=True)


def _status(status: MarketStatus) -> LifecycleMarketStatus:
    return {
        MarketStatus.TRADEABLE: LifecycleMarketStatus.TRADEABLE,
        MarketStatus.CLOSED: LifecycleMarketStatus.CLOSED,
        MarketStatus.EDITS_ONLY: LifecycleMarketStatus.CLOSINGS_ONLY,
    }.get(status, LifecycleMarketStatus.UNKNOWN)
