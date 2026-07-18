"""Pure candidate construction with deterministic cost-adjusted eligibility."""

from decimal import Decimal

from trading_desk.opportunity.config import (
    DemoExplorationConfiguration,
    MarketUniverse,
    OpportunityEngineConfiguration,
)
from trading_desk.opportunity.costs import CostConfiguration, estimate_costs
from trading_desk.opportunity.fingerprints import fingerprint
from trading_desk.opportunity.models import (
    CandidateDirection,
    CandidateEvidence,
    CandidateStatus,
    ConfidenceLabel,
    OpportunityCandidate,
    OpportunityRejectionCode,
)
from trading_desk.opportunity.scoring import confidence_label, expected_values, score_opportunity


class OpportunityEngine:
    def __init__(
        self,
        configuration: OpportunityEngineConfiguration | None = None,
        exploration: DemoExplorationConfiguration | None = None,
        universe: MarketUniverse | None = None,
        costs: CostConfiguration | None = None,
    ) -> None:
        self.configuration = configuration or OpportunityEngineConfiguration()
        self.exploration = exploration or DemoExplorationConfiguration()
        self.universe = universe or MarketUniverse()
        self.cost_configuration = costs or CostConfiguration()

    def evaluate(self, evidence: CandidateEvidence) -> OpportunityCandidate:
        market = self.universe.require_enabled(evidence.instrument_id)
        reasons: list[OpportunityRejectionCode] = []
        if not self.configuration.enabled:
            reasons.append(OpportunityRejectionCode.CONFIGURATION_DISABLED)
        if evidence.epic != market.epic:
            raise ValueError("candidate epic does not match governed market")
        if evidence.timeframe not in market.supported_timeframes:
            reasons.append(OpportunityRejectionCode.UNSUPPORTED_TIMEFRAME)
        if evidence.timeframe not in evidence.strategy.supported_timeframes:
            reasons.append(OpportunityRejectionCode.UNSUPPORTED_TIMEFRAME)
        if not evidence.strategy.demo_executable:
            reasons.append(OpportunityRejectionCode.STRATEGY_NOT_EXECUTABLE)
        if (evidence.created_at - evidence.completed_bar_timestamp).total_seconds() > (
            self.configuration.maximum_candidate_age_seconds + evidence.timeframe.seconds
        ):
            reasons.append(OpportunityRejectionCode.STALE_CONTEXT)
        costs = estimate_costs(evidence, self.cost_configuration)
        midpoint = (evidence.current_bid + evidence.current_ask) / Decimal("2")
        spread_bps = (evidence.current_ask - evidence.current_bid) / midpoint * Decimal("10000")
        if spread_bps > market.maximum_acceptable_spread:
            reasons.append(OpportunityRejectionCode.SPREAD_TOO_WIDE)
        gross, net, reward_to_risk = expected_values(evidence, costs)
        score = score_opportunity(evidence, costs, net, reward_to_risk, self.configuration)
        label = confidence_label(score, self.configuration)
        if net <= self.configuration.minimum_net_expected_value:
            reasons.append(OpportunityRejectionCode.NON_POSITIVE_EXPECTED_VALUE)
        if label is ConfidenceLabel.REJECTED:
            reasons.append(OpportunityRejectionCode.DATA_QUALITY_REJECTED)
        status = CandidateStatus.REJECTED if reasons else CandidateStatus.ELIGIBLE
        multiplier = {
            ConfidenceLabel.STRONG: self.exploration.strong_risk_multiplier,
            ConfidenceLabel.STANDARD: self.exploration.standard_risk_multiplier,
            ConfidenceLabel.EXPLORATORY: self.exploration.exploratory_risk_multiplier,
            ConfidenceLabel.REJECTED: Decimal("0"),
        }[label]
        fields = {
            "created_at": evidence.created_at,
            "cycle_id": evidence.cycle_id,
            "instrument_id": evidence.instrument_id,
            "epic": evidence.epic,
            "asset_class": evidence.asset_class,
            "timeframe": evidence.timeframe,
            "completed_bar_timestamp": evidence.completed_bar_timestamp,
            "strategy_id": evidence.strategy.strategy_id,
            "strategy_version": evidence.strategy.strategy_version,
            "strategy_fingerprint": evidence.strategy.fingerprint,
            "strategy_family": evidence.strategy.family,
            "strategy_validation_states": evidence.strategy.states,
            "market_context_id": evidence.market_context_id,
            "market_context_fingerprint": evidence.market_context_fingerprint,
            "regime": evidence.regime,
            "regime_confidence": evidence.regime_confidence,
            "direction": CandidateDirection.LONG,
            "entry_reference_price": evidence.entry_reference_price,
            "proposed_stop": evidence.proposed_stop,
            "proposed_target": evidence.proposed_target,
            "expected_holding_period": evidence.expected_holding_period,
            "signal_strength": evidence.signal_strength,
            "signal_confidence": evidence.signal_confidence,
            "estimated_win_probability": evidence.estimated_win_probability,
            "estimated_loss_probability": evidence.estimated_loss_probability,
            "estimated_average_gain": evidence.estimated_average_gain,
            "estimated_average_loss": evidence.estimated_average_loss,
            "current_bid": evidence.current_bid,
            "current_ask": evidence.current_ask,
            "gross_expected_value": gross,
            "costs": costs,
            "net_expected_value": net,
            "reward_to_risk": reward_to_risk,
            "liquidity_score": evidence.liquidity_score,
            "volatility_score": evidence.volatility_score,
            "session_score": evidence.session_score,
            "event_risk_score": evidence.event_risk_score,
            "data_quality_score": evidence.data_quality_score,
            "uncertainty_score": evidence.uncertainty_score,
            "correlation_groups": evidence.correlation_groups,
            "opportunity_score": score,
            "confidence_label": label,
            "recommended_risk_multiplier": multiplier,
            "status": status,
            "rejection_reasons": tuple(dict.fromkeys(reasons)),
            "evidence_ids": evidence.evidence_ids,
        }
        identity = fingerprint(fields)
        return OpportunityCandidate.model_validate(
            {**fields, "candidate_id": identity, "candidate_fingerprint": identity}
        )
