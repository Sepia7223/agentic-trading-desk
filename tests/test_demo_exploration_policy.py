from opportunity_helpers import candidate
from trading_desk.opportunity.config import DemoExplorationConfiguration
from trading_desk.opportunity.exploration import authorize_for_risk


def test_exploration_is_disabled_and_requires_explicit_flag() -> None:
    item = candidate()
    assert not authorize_for_risk(
        item, DemoExplorationConfiguration(), explicit_enable=True
    ).authorized_for_risk
    assert not authorize_for_risk(
        item, DemoExplorationConfiguration(enabled=True), explicit_enable=False
    ).authorized_for_risk
    assert authorize_for_risk(
        item, DemoExplorationConfiguration(enabled=True), explicit_enable=True
    ).authorized_for_risk


def test_no_candidate_and_entry_halt_never_force_a_trade() -> None:
    config = DemoExplorationConfiguration(enabled=True)
    assert not authorize_for_risk(None, config, explicit_enable=True).authorized_for_risk
    assert not authorize_for_risk(
        candidate(), config, explicit_enable=True, entry_halted=True
    ).authorized_for_risk
