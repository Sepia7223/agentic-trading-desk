from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading_desk.context.models import ContextTimeframe
from trading_desk.opportunity.config import (
    DemoCampaignConfiguration,
    DemoExplorationConfiguration,
    MarketUniverse,
    OpportunityEngineConfiguration,
    default_market_universe,
)


def test_disabled_demo_defaults_and_stable_fingerprints() -> None:
    config = OpportunityEngineConfiguration()
    assert not config.enabled
    assert config.environment == "DEMO"
    assert (
        config.configuration_fingerprint
        == OpportunityEngineConfiguration().configuration_fingerprint
    )
    assert len(MarketUniverse().markets) == 6


@pytest.mark.parametrize(
    "model, values",
    [
        (OpportunityEngineConfiguration, {"environment": "LIVE"}),
        (OpportunityEngineConfiguration, {"exploratory_score_threshold": Decimal("90")}),
        (DemoExplorationConfiguration, {"strong_risk_multiplier": Decimal("0.1")}),
        (DemoCampaignConfiguration, {"maximum_daily_loss_percent": Decimal("9")}),
    ],
)
def test_invalid_safety_configuration_rejected(model: type, values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        model(**values)


def test_empty_universe_and_unbounded_timeframe_are_rejected() -> None:
    with pytest.raises(ValidationError):
        MarketUniverse(markets=())
    market = default_market_universe()[0].model_copy(
        update={"supported_timeframes": (ContextTimeframe.DAY,)}
    )
    with pytest.raises(ValidationError):
        type(market).model_validate(market.model_dump(mode="python"))
