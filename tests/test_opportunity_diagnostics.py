from opportunity_helpers import NOW
from trading_desk.opportunity.diagnostics import (
    ActivityCounters,
    InactivityBottleneck,
    diagnose_inactivity,
)


def test_diagnostics_are_deterministic_and_never_mutate_policy() -> None:
    counters = ActivityCounters(candidates_rejected_by_cost=4)
    first = diagnose_inactivity(NOW, "DAILY", counters)
    second = diagnose_inactivity(NOW, "DAILY", counters)
    assert first == second
    assert first.dominant_bottleneck is InactivityBottleneck.TRANSACTION_COST_TOO_HIGH
    assert not first.automatic_configuration_change
