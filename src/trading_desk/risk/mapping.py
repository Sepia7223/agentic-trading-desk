"""Explicit strategy-to-risk boundary with no inferred financial state."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from trading_desk.risk.models import (
    AssetClass,
    RiskMarketStatus,
    TradeCandidate,
    TradeDirection,
)
from trading_desk.strategy.models import StrategyAction
from trading_desk.strategy.models import TradeCandidate as StrategyTradeCandidate


def map_strategy_candidate(
    strategy_candidate: StrategyTradeCandidate,
    *,
    candidate_id: str,
    signal_id: str,
    asset_class: AssetClass,
    candidate_expiry: datetime,
    entry_reference: Decimal | None,
    stop_reference: Decimal | None,
    target_reference: Decimal | None,
    bid: Decimal | None,
    ask: Decimal | None,
    volatility_or_atr: Decimal | None,
    market_status: RiskMarketStatus,
    holding_state: bool | None,
) -> TradeCandidate:
    """Require caller-supplied execution references rather than inventing them."""
    if strategy_candidate.action is not StrategyAction.LONG_CANDIDATE:
        raise ValueError("only LONG_CANDIDATE strategy outputs can enter risk evaluation")
    required = {
        "entry_reference": entry_reference,
        "stop_reference": stop_reference,
        "bid": bid,
        "ask": ask,
        "volatility_or_atr": volatility_or_atr,
    }
    missing = tuple(name for name, value in required.items() if value is None)
    if missing:
        raise ValueError(f"strategy-to-risk mapping requires: {', '.join(missing)}")
    return TradeCandidate(
        candidate_id=candidate_id,
        signal_id=signal_id,
        instrument=strategy_candidate.instrument_name,
        epic=strategy_candidate.epic,
        asset_class=asset_class,
        direction=TradeDirection.LONG,
        strategy_variant=strategy_candidate.strategy_variant.value,
        signal_timestamp=strategy_candidate.signal_timestamp,
        data_cutoff_timestamp=strategy_candidate.data_cutoff_timestamp,
        candidate_expiry=candidate_expiry,
        entry_reference=entry_reference,
        stop_reference=stop_reference,
        target_reference=target_reference,
        bid=bid,
        ask=ask,
        spread_bps=Decimal(str(strategy_candidate.current_spread_bps)),
        volatility_or_atr=volatility_or_atr,
        market_status=market_status,
        holding_state=holding_state,
        strategy_configuration_fingerprint=strategy_candidate.configuration_fingerprint,
    )
