"""One-way mapping from an Opportunity candidate to existing Risk authority."""

from datetime import timedelta

from trading_desk.opportunity.models import OpportunityCandidate
from trading_desk.risk.models import (
    AssetClass,
    RiskMarketStatus,
    TradeCandidate,
    TradeDirection,
)


def to_risk_candidate(candidate: OpportunityCandidate) -> TradeCandidate:
    """Map evidence only; Risk remains solely responsible for sizing and approval."""
    midpoint = (candidate.current_bid + candidate.current_ask) / 2
    spread_bps = candidate.costs.spread_estimate / midpoint * 10_000
    return TradeCandidate(
        candidate_id=candidate.candidate_id,
        signal_id=candidate.candidate_id,
        instrument=candidate.instrument_id,
        epic=candidate.epic,
        asset_class=AssetClass.FOREX,
        direction=TradeDirection.LONG,
        strategy_variant=candidate.strategy_id,
        signal_timestamp=candidate.created_at,
        data_cutoff_timestamp=candidate.completed_bar_timestamp,
        candidate_expiry=candidate.created_at + timedelta(seconds=60),
        entry_reference=candidate.entry_reference_price,
        stop_reference=candidate.proposed_stop,
        target_reference=candidate.proposed_target,
        bid=candidate.current_bid,
        ask=candidate.current_ask,
        spread_bps=spread_bps,
        volatility_or_atr=None,
        market_status=RiskMarketStatus.TRADEABLE,
        holding_state=False,
        strategy_configuration_fingerprint=candidate.strategy_fingerprint,
    )
