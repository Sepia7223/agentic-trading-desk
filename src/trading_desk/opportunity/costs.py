"""Deterministic non-zero transaction-cost estimation."""

from datetime import timedelta
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from trading_desk.opportunity.fingerprints import fingerprint
from trading_desk.opportunity.models import CandidateEvidence, CostEstimate


class CostConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    maximum_spread_age_seconds: int = Field(default=60, ge=1)
    slippage_fraction_of_spread: Decimal = Field(default=Decimal("0.25"), ge=0)
    # IG FX commission and funding cannot be inferred in price units from market data.
    commission_per_unit: Decimal = Field(default=Decimal("0"), ge=0)
    funding_per_boundary: Decimal = Field(default=Decimal("0"), ge=0)
    uncertainty_surcharge_rate: Decimal = Field(default=Decimal("0.10"), ge=0)
    low_liquidity_surcharge_rate: Decimal = Field(default=Decimal("0.10"), ge=0)
    event_risk_surcharge_rate: Decimal = Field(default=Decimal("0.10"), ge=0)

    @property
    def configuration_fingerprint(self) -> str:
        return fingerprint(self)


def estimate_costs(
    evidence: CandidateEvidence, configuration: CostConfiguration | None = None
) -> CostEstimate:
    config = configuration or CostConfiguration()
    age = evidence.created_at - evidence.spread_observed_at
    if age < timedelta(0) or age.total_seconds() > config.maximum_spread_age_seconds:
        raise ValueError("observable spread is stale or from the future")
    spread = evidence.current_ask - evidence.current_bid
    if spread <= 0:
        raise ValueError("observable spread must be present and positive")
    slippage = spread * config.slippage_fraction_of_spread
    commission = config.commission_per_unit
    funding_boundaries = max(0, evidence.expected_holding_period.days)
    funding = config.funding_per_boundary * funding_boundaries
    uncertainty = spread * evidence.uncertainty_score * config.uncertainty_surcharge_rate
    liquidity = (
        spread * (Decimal("1") - evidence.liquidity_score) * config.low_liquidity_surcharge_rate
    )
    event = spread * evidence.event_risk_score * config.event_risk_surcharge_rate
    total = spread + slippage + commission + funding + uncertainty + liquidity + event
    return CostEstimate(
        spread_estimate=spread,
        slippage_estimate=slippage,
        commission_estimate=commission,
        funding_estimate=funding,
        uncertainty_penalty=uncertainty,
        low_liquidity_surcharge=liquidity,
        event_risk_surcharge=event,
        total_estimated_cost=total,
        configuration_fingerprint=config.configuration_fingerprint,
    )
