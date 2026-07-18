from decimal import Decimal

from tests.opportunity_helpers import candidate

from trading_desk.opportunity.models import ConfidenceLabel


def test_score_is_bounded_and_quality_sensitive() -> None:
    strong = candidate()
    weak = candidate(
        liquidity_score=Decimal("0.1"),
        data_quality_score=Decimal("0.1"),
        event_risk_score=Decimal("0.9"),
    )
    assert Decimal("0") <= strong.opportunity_score <= Decimal("100")
    assert weak.opportunity_score < strong.opportunity_score
    assert strong.confidence_label in {
        ConfidenceLabel.STRONG,
        ConfidenceLabel.STANDARD,
        ConfidenceLabel.EXPLORATORY,
    }
