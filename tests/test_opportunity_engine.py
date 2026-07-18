from decimal import Decimal

from opportunity_helpers import evidence
from trading_desk.opportunity.config import OpportunityEngineConfiguration
from trading_desk.opportunity.engine import OpportunityEngine
from trading_desk.opportunity.models import CandidateStatus, OpportunityRejectionCode
from trading_desk.opportunity.risk import to_risk_candidate


def test_disabled_engine_rejects_without_forcing_trade() -> None:
    result = OpportunityEngine().evaluate(evidence())
    assert result.status is CandidateStatus.REJECTED
    assert OpportunityRejectionCode.CONFIGURATION_DISABLED in result.rejection_reasons


def test_enabled_engine_creates_positive_long_candidate() -> None:
    result = OpportunityEngine(OpportunityEngineConfiguration(enabled=True)).evaluate(evidence())
    assert result.net_expected_value > 0
    assert result.direction.value == "LONG"


def test_spread_gate_and_risk_mapping_preserve_observed_market() -> None:
    engine = OpportunityEngine(OpportunityEngineConfiguration(enabled=True))
    wide = engine.evaluate(evidence(current_bid=Decimal("1.1000"), current_ask=Decimal("1.1020")))
    assert OpportunityRejectionCode.SPREAD_TOO_WIDE in wide.rejection_reasons
    normal = engine.evaluate(evidence())
    mapped = to_risk_candidate(normal)
    assert mapped.bid == normal.current_bid
    assert mapped.ask == normal.current_ask
    assert mapped.direction.value == "LONG"
    assert not hasattr(mapped, "quantity")
