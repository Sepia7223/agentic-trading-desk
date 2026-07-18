"""Deterministic bounded Opportunity scoring."""

from decimal import Decimal

from trading_desk.opportunity.config import OpportunityEngineConfiguration
from trading_desk.opportunity.models import CandidateEvidence, ConfidenceLabel, CostEstimate


def expected_values(
    evidence: CandidateEvidence, costs: CostEstimate
) -> tuple[Decimal, Decimal, Decimal]:
    gross = (
        evidence.estimated_win_probability * evidence.estimated_average_gain
        - evidence.estimated_loss_probability * evidence.estimated_average_loss
    )
    net = gross - costs.total_estimated_cost
    reward_to_risk = evidence.estimated_average_gain / evidence.estimated_average_loss
    return gross, net, reward_to_risk


def score_opportunity(
    evidence: CandidateEvidence,
    costs: CostEstimate,
    net_expected_value: Decimal,
    reward_to_risk: Decimal,
    configuration: OpportunityEngineConfiguration,
) -> Decimal:
    gain_scale = max(evidence.estimated_average_gain, Decimal("0.00000001"))
    metrics = {
        "net_expected_value": _unit((net_expected_value / gain_scale + 1) / 2),
        "signal_confidence": evidence.signal_confidence,
        "regime_compatibility": evidence.regime_confidence,
        "reward_to_risk": _unit(reward_to_risk / Decimal("3")),
        "liquidity": evidence.liquidity_score,
        "volatility": evidence.volatility_score,
        "session": evidence.session_score,
        "data_quality": evidence.data_quality_score,
        "event_safety": Decimal("1") - evidence.event_risk_score,
        "cost_efficiency": Decimal("1") - _unit(costs.total_estimated_cost / gain_scale),
        "uncertainty": Decimal("1") - evidence.uncertainty_score,
    }
    weighted = sum(
        (metrics[key] * weight for key, weight in configuration.score_weights), Decimal("0")
    )
    return _unit(weighted) * Decimal("100")


def confidence_label(
    score: Decimal, configuration: OpportunityEngineConfiguration
) -> ConfidenceLabel:
    if score >= configuration.strong_score_threshold:
        return ConfidenceLabel.STRONG
    if score >= configuration.standard_score_threshold:
        return ConfidenceLabel.STANDARD
    if score >= configuration.exploratory_score_threshold:
        return ConfidenceLabel.EXPLORATORY
    return ConfidenceLabel.REJECTED


def _unit(value: Decimal) -> Decimal:
    return min(Decimal("1"), max(Decimal("0"), value))
