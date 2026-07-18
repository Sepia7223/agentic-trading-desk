from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trading_desk.context.models import ContextTimeframe
from trading_desk.opportunity.config import (
    DemoExplorationConfiguration,
    OpportunityEngineConfiguration,
)
from trading_desk.opportunity.engine import OpportunityEngine
from trading_desk.opportunity.models import (
    CandidateEvidence,
    OpportunityCandidate,
    default_strategy_policies,
)

NOW = datetime(2026, 7, 17, 12, tzinfo=UTC)


def evidence(**updates: object) -> CandidateEvidence:
    values: dict[str, object] = {
        "created_at": NOW,
        "cycle_id": "cycle-1",
        "instrument_id": "EUR/USD",
        "epic": "CS.D.EURUSD.CFD.IP",
        "asset_class": "FOREX",
        "timeframe": ContextTimeframe.MINUTE_5,
        "completed_bar_timestamp": NOW - timedelta(minutes=5),
        "strategy": default_strategy_policies()[0],
        "market_context_id": "context-1",
        "market_context_fingerprint": "a" * 64,
        "regime": "BULL_LOW_VOL",
        "regime_confidence": Decimal("0.90"),
        "entry_reference_price": Decimal("1.1001"),
        "proposed_stop": Decimal("1.0950"),
        "proposed_target": Decimal("1.1150"),
        "expected_holding_period": timedelta(hours=12),
        "signal_strength": Decimal("0.90"),
        "signal_confidence": Decimal("0.90"),
        "estimated_win_probability": Decimal("0.65"),
        "estimated_loss_probability": Decimal("0.35"),
        "estimated_average_gain": Decimal("2.0"),
        "estimated_average_loss": Decimal("0.5"),
        "current_bid": Decimal("1.1000"),
        "current_ask": Decimal("1.1002"),
        "spread_observed_at": NOW,
        "liquidity_score": Decimal("0.90"),
        "volatility_score": Decimal("0.80"),
        "session_score": Decimal("0.90"),
        "event_risk_score": Decimal("0.10"),
        "data_quality_score": Decimal("0.95"),
        "uncertainty_score": Decimal("0.10"),
        "correlation_groups": ("EUR_LONG", "USD_SHORT"),
        "evidence_ids": ("evidence-1",),
    }
    values.update(updates)
    return CandidateEvidence.model_validate(values)


def candidate(**updates: object) -> OpportunityCandidate:
    engine = OpportunityEngine(
        OpportunityEngineConfiguration(enabled=True),
        DemoExplorationConfiguration(enabled=True),
    )
    return engine.evaluate(evidence(**updates))
