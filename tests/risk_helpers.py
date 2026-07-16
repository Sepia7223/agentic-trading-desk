from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trading_desk.risk.models import (
    AccountRiskState,
    AssetClass,
    ExposureAmount,
    MarketRiskState,
    PositionCount,
    RiskMarketStatus,
    TradeCandidate,
)

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
EPIC = "CS.D.TEST.CFD.IP"
INSTRUMENT = "Test market"
FINGERPRINT = "a" * 64


def candidate(**updates: object) -> TradeCandidate:
    values: dict[str, object] = {
        "candidate_id": "candidate-1",
        "signal_id": "signal-1",
        "instrument": INSTRUMENT,
        "epic": EPIC,
        "asset_class": AssetClass.FOREX,
        "strategy_variant": "BASELINE_KALMAN_HMM",
        "signal_timestamp": NOW - timedelta(seconds=30),
        "data_cutoff_timestamp": NOW - timedelta(seconds=30),
        "candidate_expiry": NOW + timedelta(minutes=4),
        "entry_reference": Decimal("100"),
        "stop_reference": Decimal("95"),
        "target_reference": Decimal("110"),
        "bid": Decimal("99.9"),
        "ask": Decimal("100"),
        "spread_bps": Decimal("10"),
        "volatility_or_atr": Decimal("2"),
        "market_status": RiskMarketStatus.TRADEABLE,
        "holding_state": False,
        "strategy_configuration_fingerprint": FINGERPRINT,
    }
    values.update(updates)
    return TradeCandidate.model_validate(values)


def account(**updates: object) -> AccountRiskState:
    values: dict[str, object] = {
        "snapshot_id": "account-snapshot-1",
        "timestamp": NOW - timedelta(seconds=10),
        "account_equity": Decimal("100000"),
        "available_capital": Decimal("100000"),
        "realized_daily_pnl": Decimal("0"),
        "unrealized_pnl": Decimal("0"),
        "current_drawdown_fraction": Decimal("0"),
        "gross_exposure": Decimal("0"),
        "open_risk_amount": Decimal("0"),
        "open_position_count": 0,
        "instrument_exposure": (ExposureAmount(key=EPIC, amount=Decimal("0")),),
        "asset_class_exposure": (ExposureAmount(key=AssetClass.FOREX.value, amount=Decimal("0")),),
        "instrument_position_count": (PositionCount(key=EPIC, count=0),),
        "consecutive_losses": 0,
        "kill_switch_active": False,
        "state_complete": True,
    }
    values.update(updates)
    return AccountRiskState.model_validate(values)


def market(**updates: object) -> MarketRiskState:
    values: dict[str, object] = {
        "snapshot_id": "market-snapshot-1",
        "instrument": INSTRUMENT,
        "epic": EPIC,
        "timestamp": NOW - timedelta(seconds=10),
        "market_status": RiskMarketStatus.TRADEABLE,
        "bid": Decimal("99.9"),
        "ask": Decimal("100"),
        "spread_bps": Decimal("10"),
        "minimum_deal_size": Decimal("0.01"),
        "quantity_increment": Decimal("0.01"),
        "minimum_stop_distance": Decimal("1"),
        "maximum_stop_distance": Decimal("20"),
        "value_per_price_unit": Decimal("1"),
        "state_complete": True,
    }
    values.update(updates)
    return MarketRiskState.model_validate(values)
