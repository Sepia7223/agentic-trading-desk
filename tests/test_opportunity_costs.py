from datetime import timedelta
from decimal import Decimal

import pytest
from tests.opportunity_helpers import NOW, evidence

from trading_desk.opportunity.costs import estimate_costs


def test_all_cost_components_are_nonzero_and_deterministic() -> None:
    costs = estimate_costs(evidence(expected_holding_period=timedelta(days=2)))
    assert costs.spread_estimate > 0
    assert costs.slippage_estimate > 0
    assert costs.commission_estimate > 0
    assert costs.funding_estimate > 0
    assert costs.uncertainty_penalty > 0
    assert costs.low_liquidity_surcharge > 0
    assert costs.event_risk_surcharge > 0
    assert costs.total_estimated_cost == sum(
        (
            costs.spread_estimate,
            costs.slippage_estimate,
            costs.commission_estimate,
            costs.funding_estimate,
            costs.uncertainty_penalty,
            costs.low_liquidity_surcharge,
            costs.event_risk_surcharge,
        ),
        Decimal("0"),
    )


def test_stale_or_missing_spread_rejected() -> None:
    with pytest.raises(ValueError):
        estimate_costs(evidence(spread_observed_at=NOW - timedelta(minutes=2)))
    with pytest.raises(ValueError):
        estimate_costs(evidence(current_bid=Decimal("1.1"), current_ask=Decimal("1.1")))
